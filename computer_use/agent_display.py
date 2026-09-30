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
        self.tried = set()    # window ids already handled (parked or refused): a window is parked at most once
        self.pending = {}     # what this call did, for the response summary (take_report)

    def owned(self, window):
        names = [str(window.get(k)) for k in ('app_name', 'bundle_id') if window.get(k)]
        return any(fnmatch.fnmatchcase(n.lower(), p.lower()) for n in names for p in self.apps)

    def _ensure(self):
        if self.failure:
            raise RuntimeError(self.failure)
        try:
            if self.client is None:
                import spaces_client
                self.client = spaces_client.SpaceMover()
            self.display = self.client.ensure_agent_display()
        except Exception as error:
            self.failure = '%s: %s' % (getattr(error, 'code', type(error).__name__), str(error)[:80])
            raise RuntimeError(self.failure)

    def _park(self, window_id):
        """Park one window. True when parked; False when skipped (auto, with the reason noted). required raises a refusal."""
        if self.mode == 'off' or window_id in self.tried:
            return False
        self.tried.add(window_id)
        try:
            self._ensure()
            self._park_retrying(window_id)
        except Exception as error:
            reason = str(error) if isinstance(error, RuntimeError) else '%s: %s' % (getattr(error, 'code', type(error).__name__), str(error)[:80])
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

    def created(self, window_id, title=None):
        """A window this facade just created: call once it exists and its title is known (no title: not parked, never guessed at), before any
        look or act on it. Only windows the facade created are passed here; the user's windows never are."""
        if not title:
            return False
        return self._park(window_id)

    def observed(self, windows):
        """Windows first seen in an inventory: park those of agent-owned apps that are on the user's screen. Everything else is untouched."""
        if self.mode == 'off':
            return
        for w in windows:
            if w.get('window_id') is not None and w.get('is_on_screen') is not False and self.owned(w):
                self._park(w['window_id'])

    def take_report(self):
        report, self.pending = self.pending, {}
        return report

    def stop(self):
        if self.client is not None and hasattr(self.client, 'stop'):
            self.client.stop()
        self.display = None
