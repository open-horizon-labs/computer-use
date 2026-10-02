"""The agent browser (#60, CE-FACADE-009): the off-screen target of goto / open_tab / read_pages.

One Chrome for Testing process with a profile folder WE own, kept for the server's lifetime and reused (one window; new tabs, never a new
window per task). Its first window opens ON the agent display, so nothing flashes on the user's screen. Chrome restores the placement saved in the
profile over --window-position (measured live 2026-09-30: it opened on the user's built-in screen), so before every launch the profile's
saved placement is rewritten to the display's CURRENT bounds, the window is verified to lie wholly inside the display right after it
appears (else the process is quit, the saved placement deleted and the step refused agent_browser_misplaced), and with no agent display
nothing is launched (agent_display_unavailable) unless the user set CUA_AGENT_DISPLAY=off. The user's screen is never the fallback. The user's own Chrome is used only when a step says
profile: "user". The Driver binds it through browser_prepare (existing_profile) as for any Chromium: measured live 2026-09-30, Driver 0.31.0,
Chrome for Testing 154 with --remote-debugging-port=0: DevToolsActivePort is written in our own profile and the bind is exact.

Calls without task context retain the isolated browser. MCP context session=user routes browser steps to the existing user browser. CUA_AGENT_BROWSER = auto (default: the agent browser) | user (the user's own browser, as before). CUA_AGENT_BROWSER_PATH points at an installed
Chromium-family executable instead of downloading Chrome for Testing. Nothing here runs until a step needs the agent browser.
"""
import atexit
import json
import os
import re
import shutil
import signal
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
MIN_SIZE, MAX_SIZE = 200, 8000
RESIZE_MARGIN = 40.0  # points kept free on every side of the display: Chrome settles an oversize window at this inset (live 2026-10-01: asked 1920x1080, got 1880x1040), and the Driver then answers unverifiable
RESIZE_TOLERANCE = 2.0  # points: the Driver's readback (and the independent re-check) must agree with the target this closely
PROFILE_NAME = 'agent-profile'
OWNER_FILE = 'computer-use.owner'
KILL_AFTER_S = 3  # SIGTERM to the process group, then this long before SIGKILL
SESSION_FILES = ('Current Session', 'Last Session', 'Current Tabs', 'Last Tabs')  # cookies and storage stay; only what restores tabs goes
RESTORE_NEW_TAB = 5  # session.restore_on_startup: open the new tab page (never the previous session)


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


def seed_no_restore(profile):
    """Make the next start open ONE fresh tab: restore_on_startup = 5, a clean exit recorded, and the session files deleted (measured live
    2026-09-30: the profile restored its previous session and the one agent window held 6 tabs). Cookies and storage are kept."""
    profile = Path(profile)
    path = profile / 'Default' / 'Preferences'
    prefs = _load(path)
    for key, values in (('session', {'restore_on_startup': RESTORE_NEW_TAB}), ('profile', {'exit_type': 'Normal', 'exited_cleanly': True})):
        node = prefs.get(key)
        if not isinstance(node, dict):
            node = prefs[key] = {}
        node.update(values)
    _write(path, prefs)
    shutil.rmtree(profile / 'Default' / 'Sessions', ignore_errors=True)
    for name in SESSION_FILES:
        try:
            (profile / 'Default' / name).unlink()
        except OSError:
            pass


def scan_processes():
    """[(pid, command)] of every process, from `ps -axo pid,command`."""
    try:
        out = subprocess.run(['ps', '-axo', 'pid,command'], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines()[1:]:
        pid, _, command = line.strip().partition(' ')
        if pid.isdigit():
            found.append((int(pid), command.strip()))
    return found


def identify_process(pid):
    """(start time, command line) of a live process, or None: what tells a live owner from a pid the OS has reused."""
    try:
        out = subprocess.run(['ps', '-o', 'lstart=,command=', '-p', str(pid)], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    line = out.strip('\n')
    if not line.strip():
        return None
    return line[:24].strip(), line[24:].strip()


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
    def __init__(self, mode=None, path=None, cache=None, popen=subprocess.Popen, run=subprocess.run, sleep=time.sleep, clock=time.monotonic, which=shutil.which,
                 killpg=os.killpg, kill=os.kill, scan=scan_processes, identify=identify_process, getpid=os.getpid):
        self.real_launch = popen is subprocess.Popen  # focus is read and restored only around a real launch, never in tests with fakes
        self.mode = mode if mode in MODES else mode_from_env()
        self.path = path if path is not None else (os.environ.get('CUA_AGENT_BROWSER_PATH') or None)
        self.cache = Path(cache or CACHE)
        self.popen, self.run, self.sleep, self.clock, self.which = popen, run, sleep, clock, which
        self.killpg, self.kill, self.scan, self.identify, self.getpid = killpg, kill, scan, identify, getpid
        self.base_profile = self.cache / PROFILE_NAME
        self.profile = self.base_profile  # the profile this server uses: the shared one, or agent-profile-<pid> when another live server owns it
        self.separate = False
        self.claimed = False  # until a launch claimed the profile, nothing under it is ours to kill
        self.proc = None
        self.pgid = None
        self._atexit = False
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
        args = [str(exe), '--user-data-dir=%s' % self.profile, '--remote-debugging-port=0',
                '--no-first-run', '--no-default-browser-check', '--disable-session-crashed-bubble', '--hide-crash-restore-bubble']
        if rect:
            args += ['--window-position=%d,%d' % (rect['x'] + 40, rect['y'] + 40), '--window-size=%d,%d' % (rect['width'] - 80, rect['height'] - 80)]
        return args + ['about:blank']

    def front_app(self):
        """pid of the user's frontmost app before a launch, or None (best effort, read-only)."""
        if not getattr(self, 'real_launch', False):
            return None
        try:
            out = subprocess.run(['lsappinfo', 'front'], capture_output=True, text=True, timeout=3).stdout.strip()
            info = subprocess.run(['lsappinfo', 'info', '-only', 'pid', out], capture_output=True, text=True, timeout=3).stdout if out else ''
            m = re.search(r'\bpid\s*=\s*(\d+)', info)
            return int(m.group(1)) if m else None
        except Exception:
            return None

    def restore_front(self, pid):
        """Give focus back to the app that had it when Chrome took it on launch; never touches it when Chrome did not take focus."""
        if not pid or not self.proc or pid == self.proc.pid:
            return
        now = self.front_app()
        if now is None or now == pid:
            return
        try:
            subprocess.run(['osascript', '-e', 'tell application "System Events" to set frontmost of (first process whose unix id is %d) to true' % pid],
                     capture_output=True, text=True, timeout=5)
        except Exception:
            pass

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _launch(self, rect, f=None):
        exe = self.executable()
        if not self.alive():
            self._claim_profile(f)  # never kills a browser whose owner server is alive; stale ones are recovered
        profile = self.profile
        if not self.alive():
            self._write_owner(None)
            seed_no_restore(profile)
            if rect:  # its saved placement would override the flags, so rewrite it first
                seed_window_placement(profile, rect)
        self._front_before = self.front_app()  # Chrome activates itself on launch (measured 2026-10-01: it took focus from Zoom)
        proc = self.popen(self.argv(exe, rect), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)  # own process group
        self.launches += 1
        if not self._atexit:
            self._atexit = True
            atexit.register(self.stop)
        if not self.alive():  # a launch that finds the profile in use forwards to the running instance and exits: the first process stays ours
            self.proc, self.pgid = proc, proc.pid  # start_new_session: the group id is the pid
            self._write_owner(proc.pid)
        return self.proc

    # ---- kill ----
    def _ours(self, profile=None):
        """[pid] of every process whose command line names this exact user-data-dir (never this process; agent-profile-<pid> is not agent-profile)."""
        mark = re.compile(re.escape(str(profile or self.profile)) + r'(?![^\s])')
        return [pid for pid, command in self.scan() if mark.search(command) and pid != self.getpid()]

    # ---- ownership (#91): a lock file in the profile names the owning server ----
    def _identity(self, pid=None):
        pid = self.getpid() if pid is None else pid
        found = self.identify(pid)
        return {'pid': pid, 'start': found[0], 'command': found[1]} if found else {'pid': pid, 'start': None, 'command': None}

    def _read_owner(self, profile):
        try:
            data = json.loads((Path(profile) / OWNER_FILE).read_text())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and isinstance(data.get('pid'), int) else None

    def _is_me(self, owner):
        mine = self._identity()
        return owner['pid'] == mine['pid'] and owner.get('start') == mine['start'] and owner.get('command') == mine['command']

    def _owner_alive(self, profile):
        """True only when the lock names ANOTHER server that is running now: same pid with the same start time and command line (a reused pid is not the owner)."""
        owner = self._read_owner(profile)
        if not owner or self._is_me(owner):
            return False
        found = self.identify(owner['pid'])
        return bool(found and owner.get('start') == found[0] and owner.get('command') == found[1])

    def _write_owner(self, browser_pid):
        mine = self._identity()
        mine['browser_pid'] = browser_pid
        try:
            Path(self.profile).mkdir(parents=True, exist_ok=True)
            (Path(self.profile) / OWNER_FILE).write_text(json.dumps(mine))
        except OSError:
            pass

    def _claim_profile(self, f):
        """Choose the profile for this launch. A live owner other than us keeps its profile and its browser untouched and we use agent-profile-<ourpid>;
        a dead or absent owner means whatever uses that profile is stale and is recovered. Per-server profiles of dead servers are removed."""
        self._clean_dead_profiles()
        self.profile, self.separate = self.base_profile, False
        if self._owner_alive(self.base_profile):
            self.profile, self.separate = self.cache / ('%s-%d' % (PROFILE_NAME, self.getpid())), True
            self._event(f, 'agent_browser_separate_profile', owner_pid=self._read_owner(self.base_profile)['pid'], profile=str(self.profile))
        self.profile.mkdir(parents=True, exist_ok=True)
        self.claimed = True
        self._recover_stale(f)

    def _clean_dead_profiles(self):
        for path in sorted(self.cache.glob(PROFILE_NAME + '-*')):
            owner = self._read_owner(path)
            if not path.is_dir() or (self.separate and path == self.profile) or self._owner_alive(path) or (owner and self._is_me(owner)):
                continue
            for pid in self._ours(path):  # only what uses that dead server's own profile
                self._signal_pid(pid, signal.SIGKILL)
            shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    def _event(f, name, **fields):
        try:
            f.event(name, **fields)
        except Exception:
            pass

    def _signal_group(self, pgid, sig):
        try:
            self.killpg(pgid, sig)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False

    def _signal_pid(self, pid, sig):
        try:
            self.kill(pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def _recover_stale(self, f):
        if not self.claimed:
            return
        stale = self._ours()
        if not stale:
            return
        try:
            f.event('agent_browser_recovered_stale', pids=stale[:50])
        except Exception:
            pass
        for pid in stale:
            self._signal_pid(pid, signal.SIGTERM)
        deadline = self.clock() + KILL_AFTER_S
        while self._ours() and self.clock() < deadline:
            self.sleep(0.1)
        self._kill_survivors()

    def _kill_survivors(self):
        if not self.claimed:
            return
        for pid in self._ours():
            self._signal_pid(pid, signal.SIGKILL)

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
        self._launch(rect, f)
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
            clear_window_placement(self.profile)
            raise misplaced(seen[2], rect)
        self.window_id = seen[0]
        f.window_created(seen[0], seen[1], seen[2])
        self.restore_front(getattr(self, '_front_before', None))
        return self.proc.pid, seen[0]

    # ---- resize (#78) ----
    @staticmethod
    def _frame(value):
        try:
            return {k: float(value[k]) for k in ('x', 'y', 'width', 'height')}
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _close(frame, target):
        return frame is not None and all(abs(frame[k] - target[k]) <= RESIZE_TOLERANCE for k in target)

    def _set_frame(self, f, pid, window_id, frame):
        import browser
        return browser._call(f, 'set_window_frame', {'pid': pid, 'window_id': window_id, **frame})

    def resize(self, f, ctx, width, height, profile=None):
        """Resize ONLY the agent browser window (never a window of another app or the user's browser), keeping it wholly inside the agent display.
        Done only when the Driver confirms the effect with a readback within RESIZE_TOLERANCE of the (clamped) target AND a fresh window listing agrees and
        lies inside the display; else a typed Gap. Returns {pid, window_id, width, height, x, y, clamped}."""
        from core import Gap
        not_ours = Gap('resize_not_agent_window: only the agent browser window can be resized; that window is not it. Nothing was resized.')
        agent_ok = profile == 'agent' or (profile is None and self.mode == 'auto')
        if not agent_ok or (ctx.get('pid') is not None and (not self.alive() or ctx['pid'] != self.proc.pid)):
            raise not_ours
        seen = self._window(f) if self.alive() else None
        if not seen:
            raise Gap('resize_no_agent_window: the agent browser has no window; nothing was resized.')
        if ctx.get('window_id') is not None and ctx['window_id'] != seen[0]:
            raise not_ours
        window_id, before = seen[0], self._frame(seen[2])
        rect = f.agent.launch_rect()
        if rect is None or before is None:
            raise Gap('resize_unverified: the agent display or the window bounds are unknown, so the window cannot be kept inside the display; nothing was resized.')
        area = {'x': rect['x'] + RESIZE_MARGIN, 'y': rect['y'] + RESIZE_MARGIN, 'width': rect['width'] - 2 * RESIZE_MARGIN, 'height': rect['height'] - 2 * RESIZE_MARGIN}
        w, h = min(width, area['width']), min(height, area['height'])
        x = min(max(before['x'], area['x']), area['x'] + area['width'] - w)
        y = min(max(before['y'], area['y']), area['y'] + area['height'] - h)
        target = {'x': x, 'y': y, 'width': w, 'height': h}
        try:
            value = self._set_frame(f, self.proc.pid, window_id, target)
        except Gap as error:
            text = str(error)
            if text.startswith('Driver refused:'):
                code = re.sub(r'[^a-z0-9_]', '', text.split(':', 1)[1].strip().lower())[:60] or 'unknown'
                raise Gap('resize_refused: the Driver refused to resize the window (%s); nothing was resized.' % code)
            raise Gap('resize_unverified: the Driver call failed, so the window may have been resized.')
        value = value if isinstance(value, dict) else {}
        readback = next((self._frame(value[k]) for k in ('readback', 'frame', 'bounds') if isinstance(value.get(k), dict)), None)
        evidence = value.get('evidence') if isinstance(value.get('evidence'), list) else []
        read_back = any(isinstance(e, dict) and e.get('kind') == 'value_readback' for e in evidence)  # Driver 0.31 answers {effect: confirmed, evidence: [{kind: value_readback}]}, no frame
        if value.get('effect') != 'confirmed' or not (read_back or readback) or (readback and not self._close(readback, target)):
            raise Gap('resize_unverified: the Driver did not confirm the new size with a readback; the window may have changed.')
        after = self._window(f)
        rect = f.agent.launch_rect()  # the display layout is read again: containment is checked against the display as it is now
        now = after[2] if after and after[0] == window_id else None
        if rect is None or not self._close(self._frame(now), target) or not f.agent.inside(now):
            try:
                self._set_frame(f, self.proc.pid, window_id, before)  # best effort: put it back where it was
            except Gap:
                pass
            raise Gap('resize_outside_display: the window is not wholly inside the agent display after resizing (or its listed bounds differ from the readback).')
        for key in [k for k in f.looks if k[0] == self.proc.pid and k[1] == window_id]:
            del f.looks[key]  # a look of the old width must not bind to the reflowed page
        f.latest.pop((self.proc.pid, window_id), None)
        return {'pid': self.proc.pid, 'window_id': window_id, 'x': x, 'y': y, 'width': w, 'height': h, 'clamped': (w, h) != (width, height)}

    def stop(self):
        """Quit the WHOLE browser: SIGTERM to the process group, up to KILL_AFTER_S for it to go, then SIGKILL to the group; then any process still
        carrying our user-data-dir (a helper outside the group, or what a forwarded launch left) is killed by pid. The first process is not the only
        one (23 stayed alive after shutdown, measured live 2026-09-30), so the leader exiting proves nothing."""
        proc, pgid = self.proc, self.pgid
        self.proc, self.pgid, self.window_id = None, None, None
        if pgid is not None:
            if self._signal_group(pgid, signal.SIGTERM) or (proc is not None and proc.poll() is None):
                if proc is not None and proc.poll() is None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                deadline = self.clock() + KILL_AFTER_S
                while self.clock() < deadline and self._signal_group(pgid, 0):
                    self.sleep(0.1)
                self._signal_group(pgid, signal.SIGKILL)
                if proc is not None and proc.poll() is None:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        self._kill_survivors()
        self._release_profile()

    def _release_profile(self):
        self.claimed = False
        """Give the profile up: a per-server profile is removed, the shared one loses only OUR lock (never another server's)."""
        owner = self._read_owner(self.profile)
        if self.separate:
            shutil.rmtree(self.profile, ignore_errors=True)
            self.separate, self.profile = False, self.base_profile
        elif owner and self._is_me(owner):
            try:
                (self.profile / OWNER_FILE).unlink()
            except OSError:
                pass
