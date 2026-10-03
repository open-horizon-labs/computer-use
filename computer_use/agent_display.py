"""Agent display policy (#60, CE-FACADE-009): windows the facade creates, and windows of agent-owned apps, are parked on a headless
virtual display so nothing the agent drives sits on the user's screen.

CUA_AGENT_DISPLAY: off | auto (default) | required. auto parks when the helper works and otherwise continues with a one-line note;
required refuses the window-creating step (typed reason) when it cannot park. The display starts lazily on the first window that needs
parking and lives for the server's lifetime. Shared apps (Chrome, Finder, ...) are never moved; foreground routes are not touched here.
Parking is Accessibility position + bounds verification in the helper (spaces_client); it never activates or fronts anything.
"""
import fnmatch
import os
import time

MODES = ('off', 'auto', 'required')
# App names (as the Driver lists them) or bundle ids; fnmatch patterns, case-insensitive. Chrome itself is shared and absent on purpose.
DEFAULT_AGENT_APPS = ('qemu-system-*', 'Android Emulator', 'Simulator', 'Google Chrome Beta', 'Google Chrome Canary', 'Chromium',
                      'Google Chrome for Testing', 'com.apple.iphonesimulator', 'com.google.Chrome.beta', 'com.google.Chrome.canary',
                      'org.chromium.Chromium')


def mode_from_env(environ=None):
    value = ((environ if environ is not None else os.environ).get('CUA_AGENT_DISPLAY') or 'auto').strip().lower()
    return value if value in MODES else 'auto'


def apps_from_env(environ=None):
    raw = (environ if environ is not None else os.environ).get('CUA_AGENT_APPS')
    return tuple(a.strip() for a in raw.split(',') if a.strip()) if raw is not None else DEFAULT_AGENT_APPS


def _refused(reason):
    from core import Gap
    return Gap('agent_display_unavailable: %s; nothing was opened or moved (CUA_AGENT_DISPLAY=required; set auto or off to continue without parking)' % reason)


class AgentDisplay:
    RETRIES, RETRY_DELAY_S = 12, 0.5  # a window Chrome just made can be missing from its AX window list for a moment (live, #60)

    def __init__(self, mode=None, apps=None, client=None, sleep=time.sleep):
        self.sleep = sleep
        self.mode = mode if mode in MODES else mode_from_env()
        self.apps = tuple(apps) if apps is not None else apps_from_env()
        self.client = client  # a spaces_client.SpaceMover (or a fake); created on first need
        self.display = None
        self.failure = None   # why the display is unavailable (cached: the helper is not respawned on every call)
        self._rect = None     # {x, y, width, height} of the agent display, once known
        self.tried = set()    # window ids already handled (parked or refused): a window is parked at most once
        self.pending = {}     # what this call did, for the response summary (take_report)

    def owned(self, window):
        names = [str(window.get(k)) for k in ('app_name', 'bundle_id') if window.get(k)]
        return any(fnmatch.fnmatchcase(n.lower(), p.lower()) for n in names for p in self.apps)

    @staticmethod
    def _reason(error):
        return str(error) if isinstance(error, RuntimeError) else '%s: %s' % (getattr(error, 'code', type(error).__name__), str(error)[:80])

    def _ensure(self):
        if self.failure:
            raise RuntimeError(self.failure)
        try:
            if self.client is None:
                backend = os.environ.get('CUA_DISPLAY_BACKEND', 'space-mover')
                if backend == 'spaceo':
                    from spaceo_display import SpaceODisplay
                    self.client = SpaceODisplay()
                elif backend == 'space-mover':
                    import spaces_client
                    self.client = spaces_client.SpaceMover()
                else:
                    raise RuntimeError('unknown CUA_DISPLAY_BACKEND; nothing was started')
            self.display = self.client.ensure_agent_display()
        except Exception as error:
            self.failure = self._reason(error)
            raise RuntimeError(self.failure)

    def _measure(self):
        """The agent display's CURRENT bounds, read from the helper every time (never an x remembered from an earlier run: the layout moves)."""
        self._ensure()
        for d in self.client.displays():
            if int(d.get('id', -1)) == int(self.display):
                self._rect = {k: int(d[k]) for k in ('x', 'y', 'width', 'height')}
                return self._rect
        self._rect = None
        raise RuntimeError('agent display %s is not in the display list' % self.display)

    def rect(self):
        """Bounds {x, y, width, height} of the agent display, starting it if needed; None when off or unavailable (auto notes it). required refuses."""
        if self.mode == 'off':
            return None
        try:
            return self._measure()
        except Exception as error:
            if self.mode == 'required':
                raise _refused(self._reason(error))
            self.pending.setdefault('note', 'agent_display: unavailable (%s)' % self._reason(error))
            return None

    def launch_rect(self):
        """Bounds to launch a window into, for every mode but an explicit off (None): no display, no launch. The user's screen is never the fallback."""
        if self.mode == 'off':
            return None
        try:
            return self._measure()
        except Exception as error:
            from core import Gap
            raise Gap('agent_display_unavailable: %s; nothing was opened, because the agent browser never opens on your screen. Fix the agent display '
                      '(python -m computer_use doctor), or set CUA_AGENT_DISPLAY=off yourself to accept windows on your own screen.' % self._reason(error))

    def inside(self, bounds):
        """True when the WHOLE window (Driver bounds {x, y, width, height}) lies inside the agent display: any overlap with another display is False."""
        r = self._rect
        if not r or not isinstance(bounds, dict):
            return False
        try:
            x, y, w, h = bounds['x'], bounds['y'], bounds['width'], bounds['height']
        except (KeyError, TypeError):
            return False
        return r['x'] <= x and r['y'] <= y and x + w <= r['x'] + r['width'] and y + h <= r['y'] + r['height']

    on_display = inside

    def _fresh(self):
        """Re-read the display bounds before a containment check; a helper that cannot answer leaves the window to be parked (and refused there)."""
        try:
            self._measure()
        except Exception:
            self._rect = None

    def _park(self, window_id):
        """Park one window. True when parked; False when skipped (auto, with the reason noted). required raises a refusal."""
        if self.mode == 'off' or window_id in self.tried:
            return False
        self.tried.add(window_id)
        try:
            self._ensure()
            self._park_retrying(window_id)
        except Exception as error:
            reason = self._reason(error)
            if self.mode == 'required':
                self.tried.discard(window_id)
                raise _refused(reason)
            self.pending.setdefault('note', 'agent_display: unavailable (%s)' % reason)
            return False
        self.pending['parked'] = True
        return True

    def _park_retrying(self, window_id):
        for attempt in range(self.RETRIES):
            try:
                return self.client.park(window_id)
            except Exception as error:
                detail = getattr(error, 'detail', None) or {}
                missing = 'window_not_found' in (detail.get('code') or '') or 'window_not_found' in str(error)
                if not missing or attempt == self.RETRIES - 1:
                    raise
                self.sleep(self.RETRY_DELAY_S)

    def created(self, window_id, title=None, bounds=None):
        """A window this facade just created: call once it exists and its title is known (no title: not parked, never guessed at), before any
        look or act on it. Only windows the facade created are passed here; the user's windows never are."""
        if not title:
            return False
        self._fresh() if self.mode != 'off' else None
        if self.on_display(bounds):  # opened on the agent display already (launch position): nothing to move
            self.tried.add(window_id)
            return True
        return self._park(window_id)

    def observed(self, windows):
        """Windows first seen in an inventory: park those of agent-owned apps that are on the user's screen. Everything else is untouched."""
        if self.mode == 'off':
            return
        for w in windows:
            if w.get('window_id') is not None and w.get('is_on_screen') is not False and self.owned(w):
                self._fresh()
                if self.on_display(w.get('bounds')):
                    self.tried.add(w['window_id'])
                else:
                    self._park(w['window_id'])

    def take_report(self):
        report, self.pending = self.pending, {}
        return report

    def stop(self):
        if self.client is not None and hasattr(self.client, 'stop'):
            self.client.stop()
        self.display = None
