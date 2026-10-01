"""Surface lifecycle for the A/B: start only what a job needs, read ground truth, stop only what the harness started.

Every `open_surface` returns a `Surface` with `.facts` (what the prompt may state: a window title, a URL, a device id),
`.read_truth()` (independent ground truth taken after the agent finished and before cleanup) and `.close()`.
Nothing is activated on the user's behalf except where the native arm's premise requires a visible window (Chrome for
Testing, the Android emulator window, Simulator.app): those open on the main screen, which is what native use implies.
The computer-use arm opens nothing on the user's screen: its web pages use the facade's own agent browser on the agent
display, its emulator runs `-no-window`, and its iOS job addresses the simulator by device id.

The harness never touches the user's Google Chrome, and refuses a Calculator or TextEdit job when that app is already
running (the user's own documents are never at risk). Live behavior of mac/android/ios is NOT exercised by the offline
tests; only the argv builders and the process-diff logic are.
"""
import glob
import os
import json
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import tasks

CHROME_GLOB = str(Path.home() / '.cache/computer-use/browsers/chrome/*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing')
SDK = Path(os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT') or Path.home() / 'Library/Android/sdk')
# Process command-line patterns that mean "something this harness or the arms may have started" (diffed before/after every run).
WATCH = ('Google Chrome for Testing.app/', 'qemu-system', '/emulator/emulator', 'space-mover', '@mobilenext/mobile-mcp', 'mobilecli', 'Simulator.app/',
         '/cua-driver', 'Calculator.app/', 'TextEdit.app/')
# Of the new ones, these are killed when they outlive the run (anything else is only reported).
KILLABLE = ('Google Chrome for Testing.app/', 'space-mover', '@mobilenext/mobile-mcp', 'mobilecli', 'qemu-system', '/emulator/emulator')


def sh(argv, timeout=30, check=False):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=check)


def osa(script, timeout=20):
    return sh(['osascript', '-e', script], timeout=timeout).stdout.strip()


def chrome_binary():
    found = sorted(glob.glob(CHROME_GLOB))
    if not found:
        raise RuntimeError('Chrome for Testing not found under ~/.cache/computer-use/browsers (run scripts/setup_facade.sh)')
    return found[-1]


def chrome_argv(binary, profile_dir, url):
    """Native-arm browser: a dedicated Chrome for Testing with its own throwaway profile, on the main screen. Never the user's Chrome."""
    return [binary, '--user-data-dir=%s' % profile_dir, '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check',
            '--disable-session-crashed-bubble', '--hide-crash-restore-bubble', url]


def emulator_argv(avd, headless):
    exe = str(SDK / 'emulator' / 'emulator')
    return [exe, '-avd', avd, '-no-snapshot', '-no-audio', '-no-boot-anim'] + (['-no-window'] if headless else [])


def processes():
    """[(pid, command)] of every process matching WATCH."""
    out = sh(['ps', '-axo', 'pid=,command=']).stdout
    rows = []
    for line in out.splitlines():
        pid, _, cmd = line.strip().partition(' ')
        if cmd.startswith('claude') or ' --strict-mcp-config' in cmd:
            continue  # the agent process itself carries the prompt text, which may mention these names
        if pid.isdigit() and int(pid) != os.getpid() and any(p in cmd for p in WATCH):
            rows.append((int(pid), cmd.strip()))
    return rows


def new_processes(before, after):
    """Processes in `after` whose pid was not in `before` (pure)."""
    known = {pid for pid, _ in before}
    return [(pid, cmd) for pid, cmd in after if pid not in known]


def killable(rows):
    return [(pid, cmd) for pid, cmd in rows if any(p in cmd for p in KILLABLE)]


def kill_pids(pids, wait_s=4.0):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline and any(_alive(p) for p in pids):
        time.sleep(0.2)
    for pid in pids:
        if _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def app_running(name):
    return bool(osa('tell application "System Events" to (name of processes) contains "%s"' % name) == 'true')


class Surface:
    def __init__(self, facts=None):
        self.facts = facts or {}
        self._closers = []

    def on_close(self, fn):
        self._closers.append(fn)

    def read_truth(self):
        return {}

    def close(self):
        errors = []
        for fn in reversed(self._closers):
            try:
                fn()
            except Exception as error:
                errors.append(str(error))
        self._closers = []
        return errors


def _wait_title(timeout=15):
    time.sleep(min(timeout, 2.5))  # Chrome needs a moment to paint its first frame before the agent looks


def grant_browser(title, timeout=20):
    """The one-time CDP grant (browser_prepare existing_profile) on the native arm's own Chrome for Testing window, so both
    arms start from the same consent state: computer-use performs this step itself for its agent browser (browser.bind).
    Without it the native agent's browser_set_input_files is refused browser_consent_required (2026-10-01 upload run)."""
    driver = str(Path.home() / '.local/bin/cua-driver')
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = sh([driver, 'call', 'list_windows', '--json', '{}']).stdout
        try:
            wins = [w for w in json.loads(out).get('windows', []) if (w.get('title') or '').startswith(title) and w.get('layer', 0) == 0]
        except ValueError:
            wins = []
        if wins:
            w = wins[0]
            r = sh([driver, 'call', 'browser_prepare', '--json', json.dumps({'pid': w['pid'], 'window_id': w['window_id'], 'strategy': {'kind': 'existing_profile'}})], timeout=60)
            return {'granted': r.returncode == 0, 'detail': (r.stdout or r.stderr)[:200]}
        time.sleep(1)
    return {'granted': False, 'detail': 'window titled %r not listed' % title}


def open_surface(task, arm, run_id, base_url, workdir, android_serial_box=None, ios_udid=None):
    """Prepare the surface for one run. `arm` is 'native' or 'computer-use'."""
    spec = tasks.TASKS[task]
    surface = spec['surface']
    s = Surface()
    if surface == 'web':
        url = spec['url'] if 'url' in spec else '%s%s?run=%s' % (base_url, spec['route'], run_id)
        title = spec['title'].format(run=run_id)
        s.facts = {'url': url, 'title': title}
        if task == 'upload':
            path = Path(workdir) / UPLOAD_DIR
            path.mkdir(parents=True, exist_ok=True)
            info = prepare_upload_file(path)
            s.facts['file'] = info['path']
            s.upload = info
            s.read_truth = lambda info=info: {'filename': info['filename'], 'size': info['size'], 'sha256': info['sha256']}
        if task == 'compare':
            s.read_truth = lambda: {'name': 'Quillon Arc Lamp', 'price': '36.75'}
        if task == 'wikipedia':
            value = tasks.wikipedia_truth()  # fetched BEFORE the run, so a page edited mid-run cannot change what was asked
            s.read_truth = lambda value=value: value
        if arm == 'native':
            profile = tempfile.mkdtemp(prefix='cua-ab-chrome-')
            proc = subprocess.Popen(chrome_argv(chrome_binary(), profile, url), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            s.on_close(lambda: shutil.rmtree(profile, ignore_errors=True))
            s.on_close(lambda: kill_pids([proc.pid] + [p for p, c in processes() if profile in c]))
            _wait_title()
            s.facts['browser_grant'] = grant_browser(title)
        return s
    if surface == 'mac':
        app = spec['app']
        if app_running(app):
            raise RuntimeError('%s is already running: refusing to touch the user\'s %s state; quit it and rerun' % (app, app))
        s.facts = {'app': app}
        sh(['open', '-g', '-a', app])
        time.sleep(2)
        if task == 'calculator':
            s.read_truth = lambda: tasks.CALC_ANSWER
        if task == 'textedit':
            def read_doc():
                n = osa('tell application "TextEdit" to count documents')
                return {'doc_text': osa('tell application "TextEdit" to get text of document 1') if n.isdigit() and int(n) > 0 else None}
            s.read_truth = read_doc
            s.on_close(lambda: osa('tell application "TextEdit" to close every document saving no'))
        s.on_close(lambda: osa('tell application "%s" to quit' % app))
        return s
    if surface == 'android':
        if sh(['adb', 'devices']).stdout.count('emulator-'):
            raise RuntimeError('an Android emulator is already running: the harness only runs its own; stop it and rerun')
        proc = subprocess.Popen(emulator_argv(tasks.ANDROID_AVD, headless=(arm == 'computer-use')), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        serial = wait_android_boot(proc)
        s.facts = {'device': tasks.ANDROID_AVD, 'serial': serial}
        s.read_truth = lambda: tasks.android_truth(serial=serial)
        s.on_close(lambda: sh(['adb', '-s', serial, 'emu', 'kill']))
        s.on_close(lambda: kill_pids([proc.pid] + [p for p, c in processes() if tasks.ANDROID_AVD in c]))
        return s
    if surface == 'ios':
        udid = ios_udid or booted_iphone()
        s.facts = {'device': udid}
        s.read_truth = lambda: tasks.ios_truth(udid)
        s.on_close(lambda: sh(['xcrun', 'simctl', 'terminate', udid, 'com.apple.Preferences']))
        if arm == 'native':
            hub = '/Applications/Xcode.app/Contents/Applications/DeviceHub.app'
            app_name = 'Device Hub' if Path(hub).exists() else 'Simulator'
            was_running = app_running(app_name)
            sh(['open', '-a', hub if app_name == 'Device Hub' else 'Simulator'])
            for _ in range(30):  # the 2026-10-01 run handed the agent a Simulator with no window yet
                if (osa('tell application "System Events" to count windows of process "%s"' % app_name) or '0').strip() not in ('', '0'):
                    break
                time.sleep(1)
            if not was_running:
                s.on_close(lambda: osa('tell application "%s" to quit' % app_name))
        return s
    raise ValueError(surface)


UPLOAD_DIR = 'upload'


def prepare_upload_file(directory):
    """A deterministic text file of tasks.UPLOAD_SIZE bytes; returns {path, filename, size, sha256}."""
    import hashlib
    body = ('Invoice 4471 scan, page 1\n' * 200).encode()[:tasks.UPLOAD_SIZE]
    path = Path(directory) / tasks.UPLOAD_NAME
    path.write_bytes(body)
    return {'path': str(path), 'filename': tasks.UPLOAD_NAME, 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}


def wait_android_boot(proc, timeout=240):
    deadline = time.monotonic() + timeout
    serial = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError('emulator exited early (%s)' % proc.returncode)
        m = re.search(r'(emulator-\d+)\s+device', sh(['adb', 'devices']).stdout)
        if m:
            serial = m.group(1)
            if sh(['adb', '-s', serial, 'shell', 'getprop', 'sys.boot_completed']).stdout.strip() == '1':
                time.sleep(3)
                return serial
        time.sleep(2)
    raise RuntimeError('emulator did not finish booting in %ds' % timeout)


def booted_iphone():
    out = sh(['xcrun', 'simctl', 'list', 'devices', 'booted']).stdout
    m = re.search(r'iPhone 17 Pro \(([0-9A-F-]{36})\) \(Booted\)', out)
    if not m:
        raise RuntimeError('no booted iPhone 17 Pro simulator')
    return m.group(1)
