"""The agent browser (#60, CE-FACADE-009): the default target of goto / open_tab / read_pages.

One Chrome for Testing process with a profile folder WE own, kept for the server's lifetime and reused (one window; new tabs, never a new
window per task). Its first window opens ON the agent display, so nothing flashes on the user's screen. Chrome restores the placement saved in the
profile over --window-position (measured live 2026-09-30: it opened on the user's built-in screen), so before every launch the profile's
saved placement is rewritten to the display's CURRENT bounds, the window is verified to lie wholly inside the display right after it
appears (else the process is quit, the saved placement deleted and the step refused agent_browser_misplaced), and with no agent display
nothing is launched (agent_display_unavailable) unless the user set CUA_AGENT_DISPLAY=off. The user's screen is never the fallback. The user's own Chrome is used only when a step says
profile: "user". The Driver binds it through browser_prepare (existing_profile) as for any Chromium: measured live 2026-09-30, Driver 0.31.0,
Chrome for Testing 154 with --remote-debugging-port=0: DevToolsActivePort is written in our own profile and the bind is exact.

CUA_AGENT_BROWSER = auto (default: the agent browser) | user (the user's own browser, as before). CUA_AGENT_BROWSER_PATH points at an installed
Chromium-family executable instead of downloading Chrome for Testing. Nothing here runs until a step needs the agent browser.
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

MODES = ('auto', 'user')
CACHE = Path(os.environ.get('CUA_CACHE_DIR') or Path.home() / '.cache' / 'computer-use')
INSTALL_ARGV = ['npx', '-y', '@puppeteer/browsers', 'install', 'chrome@stable']
INSTALL_TIMEOUT_S = 600
WINDOW_WAIT_S = 20
WINDOW_POLL_S = 0.5
INSET = 40
KILL_AFTER_S = 2


def placement_for(rect):
    """Chrome's browser.window_placement for a window INSET px inside the display rect {x, y, width, height}, on that display's work area."""
    return {'left': rect['x'] + INSET, 'top': rect['y'] + INSET, 'right': rect['x'] + rect['width'] - INSET, 'bottom': rect['y'] + rect['height'] - INSET,
            'maximized': False, 'work_area_left': rect['x'], 'work_area_top': rect['y'],
            'work_area_right': rect['x'] + rect['width'], 'work_area_bottom': rect['y'] + rect['height']}


def _load(path):
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def _drop_placements(node):
    """Remove every 'window_placement' key at any depth; True when something was removed."""
    removed = False
    if isinstance(node, dict):
        if 'window_placement' in node:
            del node['window_placement']
            removed = True
        for value in list(node.values()):
            removed = _drop_placements(value) or removed
    return removed


def seed_window_placement(profile, rect):
    """Write the placement into <profile>/Default/Preferences (every other key kept, file and keys created) and drop stale copies from Local State."""
    profile = Path(profile)
    prefs = _load(profile / 'Default' / 'Preferences')
    browser = prefs.get('browser')
    if not isinstance(browser, dict):
        browser = prefs['browser'] = {}
    browser['window_placement'] = placement_for(rect)
    _write(profile / 'Default' / 'Preferences', prefs)
    clear_window_placement(profile, prefs=False)


def clear_window_placement(profile, prefs=True):
    """Delete the saved placement (Default/Preferences when prefs, and any copy in Local State); files that do not exist are not created."""
    profile = Path(profile)
    targets = ([profile / 'Default' / 'Preferences'] if prefs else []) + [profile / 'Local State']
    for path in targets:
        if path.exists():
            data = _load(path)
            if _drop_placements(data):
                _write(path, data)


def misplaced(bounds, rect):
    from core import Gap
    return Gap('agent_browser_misplaced: the agent browser window opened at %s, not wholly inside the agent display %s; the browser was quit and its saved '
               'window placement deleted. Nothing was navigated.' % (bounds, rect))


def mode_from_env(environ=None):
    value = ((environ if environ is not None else os.environ).get('CUA_AGENT_BROWSER') or 'auto').strip().lower()
    return value if value in MODES else 'auto'


def unavailable(reason, command=None):
    from core import Gap
    hint = ' Install it yourself with: %s, or set CUA_AGENT_BROWSER_PATH to a Chromium executable, or CUA_AGENT_BROWSER=user.' % ' '.join(command or INSTALL_ARGV + ['--path', str(CACHE / 'browsers')])
    return Gap('agent_browser_unavailable: %s.%s Nothing was opened.' % (reason, hint))


def find_installed(root):
    """The Chrome for Testing executable under a @puppeteer/browsers install folder, or None."""
    root = Path(root)
    if not root.exists():
        return None
    patterns = ('chrome/*/chrome-mac-*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
                'chrome/*/chrome-linux*/chrome')
    for pattern in patterns:
        found = sorted(root.glob(pattern))
        if found:
            return found[-1]
    return None


class AgentBrowser:
    def __init__(self, mode=None, path=None, cache=None, popen=subprocess.Popen, run=subprocess.run, sleep=time.sleep, clock=time.monotonic, which=shutil.which):
        self.mode = mode if mode in MODES else mode_from_env()
        self.path = path if path is not None else (os.environ.get('CUA_AGENT_BROWSER_PATH') or None)
        self.cache = Path(cache or CACHE)
        self.popen, self.run, self.sleep, self.clock, self.which = popen, run, sleep, clock, which
        self.proc = None
        self.window_id = None
        self.launches = 0

    # ---- executable ----
    def executable(self):
        if self.path:
            p = Path(self.path)
            if p.is_dir() and p.suffix == '.app':  # a .app bundle: its main binary
                candidates = sorted((p / 'Contents' / 'MacOS').glob('*'))
                p = candidates[0] if candidates else p
            if not p.exists():
                raise unavailable('CUA_AGENT_BROWSER_PATH does not exist: %s' % self.path)
            return p
        found = find_installed(self.cache / 'browsers')
        if found:
            return found
        return self._install()

    def _install(self):
        command = INSTALL_ARGV + ['--path', str(self.cache / 'browsers')]
        if not self.which('npx'):
            raise unavailable('Chrome for Testing is not installed and npx (Node.js) is missing', command)
        try:
            done = self.run(command, capture_output=True, text=True, timeout=INSTALL_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise unavailable('installing Chrome for Testing failed (%s)' % type(error).__name__, command)
        found = find_installed(self.cache / 'browsers') if done.returncode == 0 else None
        if not found:
            raise unavailable('installing Chrome for Testing failed (exit %s)' % done.returncode, command)
        return found

    # ---- launch ----
    def argv(self, exe, rect=None):
        """The launch command. With the agent display's bounds the window is placed 40 px inside it, so it never appears on the user's screen."""
        args = [str(exe), '--user-data-dir=%s' % (self.cache / 'agent-profile'), '--remote-debugging-port=0',
                '--no-first-run', '--no-default-browser-check']
        if rect:
            args += ['--window-position=%d,%d' % (rect['x'] + 40, rect['y'] + 40), '--window-size=%d,%d' % (rect['width'] - 80, rect['height'] - 80)]
        return args + ['about:blank']

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _launch(self, rect):
        exe = self.executable()
        (self.cache / 'agent-profile').mkdir(parents=True, exist_ok=True)
        if rect and not self.alive():  # our Chrome is not running: its saved placement would override the flags, so rewrite it first
            seed_window_placement(self.cache / 'agent-profile', rect)
        proc = self.popen(self.argv(exe, rect), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.launches += 1
        if not self.alive():  # a launch that finds the profile in use forwards to the running instance and exits: the first process stays ours
            self.proc = proc
        return self.proc

    def _window(self, f):
        """(window_id, title, bounds) of the agent browser's titled window, preferring the remembered one."""
        f.windows()  # starts the Driver session
        raws = f._read('list_windows', lambda: f.driver.call('list_windows', {'session': f.session})).get('windows', [])
        mine = [w for w in raws if w.get('pid') == self.proc.pid and w.get('title') and w.get('window_id') is not None and w.get('layer', 0) == 0]
        if not mine:
            return None
        pick = next((w for w in mine if w['window_id'] == self.window_id), mine[0])
        return pick['window_id'], pick['title'], pick.get('bounds')

    def window(self, f):
        """(pid, window_id) of the one agent browser window: reused while it exists; started (parked on the agent display) only when none does."""
        if self.alive():
            seen = self._window(f)
            if seen:
                self.window_id = seen[0]
                return self.proc.pid, seen[0]
        rect = f.agent.launch_rect()  # the display's current bounds; no display: refused here before anything is launched (None only for CUA_AGENT_DISPLAY=off)
        self._launch(rect)
        deadline = self.clock() + WINDOW_WAIT_S
        seen = None
        while True:
            seen = self._window(f) if self.alive() else None
            if seen or self.clock() >= deadline or not self.alive():
                break
            self.sleep(WINDOW_POLL_S)
        if not seen:
            self.stop()
            raise unavailable('the agent browser started but showed no window in %ds' % WINDOW_WAIT_S)
        if rect is not None and not f.agent.inside(seen[2]):  # never leave a window on another display up, and do not rely on parking it afterwards
            self.stop()
            clear_window_placement(self.cache / 'agent-profile')
            raise misplaced(seen[2], rect)
        self.window_id = seen[0]
        f.window_created(seen[0], seen[1], seen[2])
        return self.proc.pid, seen[0]

    def stop(self):
        proc, self.proc, self.window_id = self.proc, None, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=KILL_AFTER_S)
            except Exception:
                proc.kill()
                try:
                    proc.wait(timeout=KILL_AFTER_S)
                except Exception:
                    pass
