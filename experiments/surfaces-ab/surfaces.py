"""Surface lifecycle for the A/B: start only what a job needs, read ground truth, stop only what the harness started.

Every `open_surface` returns a `Surface` with `.facts` (what the prompt may state: a window title, a URL, a device id),
`.read_truth()` (independent ground truth taken after the agent finished and before cleanup) and `.close()`.
Every window the harness opens goes onto the virtual agent display (space-mover, the one the product uses) and is verified
there before the run starts; a window that cannot be parked refuses the run (SetupRefused) instead of staying on the user's
screen. The computer-use arm's own windows are the facade's business (its agent browser, a `-no-window` emulator, a simulator
addressed by device id).

The harness never touches the user's Google Chrome, and refuses a Calculator or TextEdit job when that app is already
running (the user's own documents are never at risk). Live behavior of mac/android/ios is NOT exercised by the offline
tests; only the argv builders, the parking loop (with fakes) and the process-diff logic are.
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
         '/cua-driver', 'Calculator.app/', 'TextEdit.app/', 'DeviceHub.app/', 'computer_use/server.py')
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


_AGENT_DISPLAY = None
_BOOTED_BY_HARNESS = []   # simulator udids this harness booted (shut down at exit)
_HIDE_AT_EXIT = []        # app names to hide before the agent display goes away (their windows would bounce onto the user's screen)


class SetupRefused(RuntimeError):
    """A run cannot be set up safely (no agent display, a window that would stay on the user's screen, another facade running...)."""


def agent_display():
    """The same virtual agent display the product uses (space-mover), shared by both arms' harness-opened windows so they stay off the
    user's screen (2026-10-01: running the native arm on the main screen took over the user's desk). Lives for the harness process."""
    global _AGENT_DISPLAY
    if _AGENT_DISPLAY is None:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'computer_use'))
        from agent_display import AgentDisplay
        import atexit
        _AGENT_DISPLAY = AgentDisplay(mode='required')
        atexit.register(_at_exit)
    return _AGENT_DISPLAY


def _at_exit():
    for app in _HIDE_AT_EXIT:  # hide (never quit: quitting Device Hub shuts the simulator down) before its display disappears
        try:
            osa('tell application "System Events" to set visible of process "%s" to false' % app)
        except Exception:
            pass
    for udid in _BOOTED_BY_HARNESS:
        try:
            sh(['xcrun', 'simctl', 'shutdown', udid], timeout=60)
        except Exception:
            pass
    if _AGENT_DISPLAY is not None:
        try:
            _AGENT_DISPLAY.stop()
        except Exception:
            pass


def own_pids():
    """Pids of helpers the harness itself keeps for its lifetime (the agent display's `display serve`): never killed as run strays."""
    client = getattr(_AGENT_DISPLAY, 'client', None)
    proc = getattr(client, '_serve', None)
    return {proc.pid} if proc is not None and proc.poll() is None else set()


def agent_rect():
    """Current bounds of the agent display. Any failure (helper missing, untrusted, display not created) is a SetupRefused: the
    harness never falls back to the user's screen (core.Gap is a ValueError and used to abort the whole suite)."""
    try:
        r = agent_display().launch_rect()
    except Exception as error:
        raise SetupRefused('agent display unavailable: %s' % error)
    if not r:
        raise SetupRefused('agent display unavailable (no bounds)')
    return r


def _driver_windows():
    driver = str(Path.home() / '.local/bin/cua-driver')
    try:
        return json.loads(sh([driver, 'call', 'list_windows', '--json', '{}']).stdout).get('windows', [])
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return []


def park_windows(match, timeout=30, list_windows=_driver_windows, display=None, sleep=time.sleep, clock=time.time):
    """Move every layer-0 window that `match`es onto the agent display and VERIFY it is there (fresh listing). Returns the ids parked.
    Raises SetupRefused when no matching window appears or one is still on the user's screen at the deadline: a run never starts with
    a harness window on the user's screen (the earlier version swallowed park errors and returned, leaving the window in place)."""
    ad = display or agent_display()
    if display is None:
        agent_rect()  # measures (refreshes ad._rect) or refuses
    parked, errors = [], {}
    deadline = clock() + timeout
    mine = []
    while True:
        mine = [w for w in list_windows() if w.get('layer', 0) == 0 and (w.get('bounds') or {}).get('height', 0) > 100 and match(w)]
        outside = [w for w in mine if not ad.inside(w.get('bounds'))]
        if mine and not outside:
            return parked
        if clock() >= deadline:
            break
        for w in outside:
            try:
                ad.client.park(w['window_id'])
                if w['window_id'] not in parked:
                    parked.append(w['window_id'])
            except Exception as error:
                errors[w['window_id']] = str(error)[:120]
        sleep(1)
    if not mine:
        raise SetupRefused('no window to park appeared within %ds' % timeout)
    raise SetupRefused('window(s) %s still on the user\'s screen after parking (%s)' % ([w['window_id'] for w in outside], errors or 'no error reported'))


def chrome_argv(binary, profile_dir, url, rect):
    """Native-arm browser: a dedicated Chrome for Testing with its own throwaway profile, opened inside `rect` (the agent display's
    bounds, passed in so this stays pure). Never the user's Chrome."""
    r = rect
    return [binary, '--user-data-dir=%s' % profile_dir, '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check',
            '--disable-session-crashed-bubble', '--hide-crash-restore-bubble',
            '--window-position=%d,%d' % (r['x'] + 40, r['y'] + 40), '--window-size=%d,%d' % (r['width'] - 80, r['height'] - 80), url]


FOREIGN = ('computer_use/server.py', 'space-mover display serve', '@mobilenext/mobile-mcp', 'agent-profile')


def foreign_facades(rows, own=()):
    """Processes of ANOTHER facade session (a computer_use/server.py, its display helper, mobile-mcp, its agent browser) that are not
    the harness's own. Two facades kill each other's browser and steal the shared agent display (#91), and the stray sweep could kill
    their helpers, so a run refuses while one is up (pure)."""
    return [(p, c) for p, c in rows if p not in set(own) and any(f in c for f in FOREIGN)]


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


def killable(rows, own=()):
    """New processes to kill after a run; never the harness's own long-lived helpers (`own`: its agent display, whose death bounces
    every parked window onto the user's screen)."""
    own = set(own)
    return [(pid, cmd) for pid, cmd in rows if pid not in own and any(p in cmd for p in KILLABLE)]


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


def open_surface(task, arm, run_id, base_url, workdir, android_serial_box=None, ios_udid=None):
    """Prepare the surface for one run. `arm` is 'native' or 'computer-use'. A setup that fails part-way closes what it already
    opened (the caller never receives the Surface, so it could not) and re-raises."""
    s = Surface()
    try:
        return _open_surface(s, task, arm, run_id, base_url, workdir, ios_udid)
    except BaseException:
        s.close()
        raise


def _open_surface(s, task, arm, run_id, base_url, workdir, ios_udid=None):
    spec = tasks.TASKS[task]
    surface = spec['surface']
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
            proc = subprocess.Popen(chrome_argv(chrome_binary(), profile, url, agent_rect()), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            s.on_close(lambda: shutil.rmtree(profile, ignore_errors=True))
            s.on_close(lambda: kill_pids([proc.pid] + [p for p, c in processes() if profile in c]))
            _wait_title()
            # --window-position is a request, not a guarantee: verify (and park) before the agent is told the window exists.
            s.facts['parked'] = park_windows(lambda w, pid=proc.pid: w.get('pid') == pid)
        return s
    if surface == 'mac':
        app = spec['app']
        if app_running(app):
            raise RuntimeError('%s is already running: refusing to touch the user\'s %s state; quit it and rerun' % (app, app))
        s.facts = {'app': app}
        sh(['open', '-g', '-a', app])
        time.sleep(2)
        s.on_close(lambda: osa('tell application "%s" to quit' % app))  # registered first so it runs last, after any document close
        # Both arms: the harness opened this window, so it goes onto the agent display whichever tool drives it (the computer-use arm's
        # Calculator used to stay on the user's screen while the native arm's was parked).
        s.facts['parked'] = park_windows(lambda w, app=app: (w.get('app_name') or '') == app)
        if task == 'calculator':
            s.read_truth = lambda: tasks.CALC_ANSWER
        if task == 'textedit':
            def read_doc():
                n = osa('tell application "TextEdit" to count documents')
                return {'doc_text': osa('tell application "TextEdit" to get text of document 1') if n.isdigit() and int(n) > 0 else None}
            s.read_truth = read_doc
            s.on_close(lambda: osa('tell application "TextEdit" to close every document saving no'))
        return s
    if surface == 'android':
        if sh(['adb', 'devices']).stdout.count('emulator-'):
            raise RuntimeError('an Android emulator is already running: the harness only runs its own; stop it and rerun')
        proc = subprocess.Popen(emulator_argv(tasks.ANDROID_AVD, headless=(arm == 'computer-use')), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        s.on_close(lambda: kill_pids([proc.pid] + [p for p, c in processes() if tasks.ANDROID_AVD in c]))  # first, so a failed boot still cleans up
        serial = wait_android_boot(proc)
        s.facts = {'device': tasks.ANDROID_AVD, 'serial': serial}
        s.read_truth = lambda: tasks.android_truth(serial=serial)
        s.on_close(lambda: sh(['adb', '-s', serial, 'emu', 'kill']))
        if arm == 'native':  # the emulator window, onto the agent display
            s.facts['parked'] = park_windows(lambda w, pid=proc.pid: w.get('pid') == pid or 'qemu' in (w.get('app_name') or '').lower() or 'Emulator' in (w.get('app_name') or ''))
        return s
    if surface == 'ios':
        udid = ios_udid or booted_iphone()
        s.facts = {'device': udid, 'app': None}
        s.read_truth = lambda: tasks.ios_truth(udid)
        s.on_close(lambda: sh(['xcrun', 'simctl', 'terminate', udid, 'com.apple.Preferences']))
        if arm == 'native':
            hub = '/Applications/Xcode.app/Contents/Applications/DeviceHub.app'
            app_name = 'Device Hub' if Path(hub).exists() else 'Simulator'
            was_running = app_running(app_name)
            sh(['open', '-g', '-a', hub if app_name == 'Device Hub' else 'Simulator'])
            if was_running:  # a previous harness hid it at exit (never quit: that shuts the simulator down); unhide without activating
                osa('tell application "System Events" to set visible of process "%s" to true' % app_name)
            for _ in range(30):  # the 2026-10-01 run handed the agent a Simulator with no window yet
                if (osa('tell application "System Events" to count windows of process "%s"' % app_name) or '0').strip() not in ('', '0'):
                    break
                time.sleep(1)
            names = ('Device Hub', 'DeviceHub') if app_name == 'Device Hub' else ('Simulator',)
            s.facts['app'] = app_name
            s.facts['parked'] = park_windows(lambda w: (w.get('app_name') or '') in names)
            if not was_running and app_name not in _HIDE_AT_EXIT:
                _HIDE_AT_EXIT.append(app_name)
            # Quitting Device Hub shuts the simulator down (2026-10-01), so leave it running; its window stays on the agent display.
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
    if m:
        return m.group(1)
    any_ = re.search(r'iPhone 17 Pro \(([0-9A-F-]{36})\) \(Shutdown\)', sh(['xcrun', 'simctl', 'list', 'devices']).stdout)
    if not any_:
        raise RuntimeError('no iPhone 17 Pro simulator')
    sh(['xcrun', 'simctl', 'boot', any_.group(1)], timeout=120)
    _BOOTED_BY_HARNESS.append(any_.group(1))  # the harness booted it, so the harness shuts it down at exit
    sh(['xcrun', 'simctl', 'bootstatus', any_.group(1), '-b'], timeout=240)
    return any_.group(1)
