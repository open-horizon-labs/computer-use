"""Client for the space-mover helper (issue #60): park one window away from the user's Space.

Primary: a headless virtual display (`space-mover display serve`, a child process that must stay alive) and
`move --display` (Accessibility position, verified by CGWindowList bounds). Fallback, only when configured:
`move --space` (Mission Control drag, visible for about a second). Not wired into look/do yet.

Typed errors: SpaceMoverUnavailable (space_mover_unavailable), SpaceMoverUntrusted (space_mover_untrusted),
WindowNotMoved (window_not_moved). Exit codes of the binary: 0 ok, 1 move refused/unverified, 2 usage, 3 not
trusted for Accessibility, 4 unavailable.
"""
import json
import os
import select
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = ROOT / 'scripts' / 'build_space_mover.sh'
DEFAULT_BINARY = ROOT / 'computer_use' / 'spaces' / 'bin' / 'space-mover'


class SpaceMoverError(Exception):
    code = 'space_mover_error'

    def __init__(self, message, detail=None):
        super().__init__(message)
        self.detail = detail or {}


class SpaceMoverUnavailable(SpaceMoverError):
    code = 'space_mover_unavailable'


class SpaceMoverUntrusted(SpaceMoverError):
    code = 'space_mover_untrusted'


class WindowNotMoved(SpaceMoverError):
    code = 'window_not_moved'


def title_matches(candidate, title):
    """Mission Control shortens long titles in the middle with an ellipsis; mirrors titleMatches in space-mover.swift.

    A shortened candidate matches when its prefix (at least 8 characters) and suffix agree with the title."""
    if candidate is None:
        return False
    if candidate == title:
        return True
    if '…' not in candidate:
        return False
    prefix, suffix = candidate.split('…', 1)
    if len(prefix) < 8:
        return False
    if not title.startswith(prefix):
        return False
    return suffix == '' or (len(title) >= len(suffix) and title.endswith(suffix))


def select_thumbnail(thumbnails, title, bundle_id, active_space):
    """Mirror of selectThumbnail: returns ('found', thumb) | ('none', None) | ('ambiguous', None).

    thumbnails: dicts with AXIdentifier ('<bundle id>.space.<space id>' on macOS 26+) and AXTitle."""
    found = None
    for t in thumbnails:
        ident = t.get('AXIdentifier') or ''
        tail = ident.rsplit('.space.', 1)[-1] if '.space.' in ident else ''
        space = int(tail) if tail.isdigit() else None
        modern = space is not None
        same_app = not modern or (bundle_id is not None and ident.startswith(bundle_id + '.space.'))
        if title_matches(t.get('AXTitle'), title) and same_app and (not modern or space == active_space):
            if found is not None:
                return 'ambiguous', None
            found = t
    return ('found', found) if found is not None else ('none', None)


class SpaceMover:
    def __init__(self, binary=None, fallback_space=None, build_timeout=180, call_timeout=30, serve_timeout=10):
        self.binary = Path(binary or os.environ.get('CUA_SPACE_MOVER') or DEFAULT_BINARY)
        self.fallback_space = fallback_space
        self.build_timeout = build_timeout
        self.call_timeout = call_timeout
        self.serve_timeout = serve_timeout
        self._serve = None
        self._display = None

    def ensure_binary(self):
        if self.binary.exists():
            return self.binary
        if self.binary != DEFAULT_BINARY or not BUILD_SCRIPT.exists():
            raise SpaceMoverUnavailable(f'space-mover binary missing: {self.binary}')
        try:
            done = subprocess.run([str(BUILD_SCRIPT)], capture_output=True, text=True, timeout=self.build_timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise SpaceMoverUnavailable(f'building space-mover failed: {e}')
        if done.returncode != 0 or not self.binary.exists():
            raise SpaceMoverUnavailable('building space-mover failed: ' + done.stderr[-500:])
        return self.binary

    def run(self, *args):
        """Run a command; returns the parsed JSON. Exit 1 returns the JSON (a refused move); others raise."""
        binary = self.ensure_binary()
        try:
            done = subprocess.run([str(binary), *map(str, args)], capture_output=True, text=True, timeout=self.call_timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise SpaceMoverUnavailable(f'space-mover did not run: {e}')
        try:
            data = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise SpaceMoverUnavailable(f'space-mover gave no JSON (exit {done.returncode}): {done.stderr[-300:]}')
        if done.returncode == 3:
            raise SpaceMoverUntrusted(data.get('reason') or 'Accessibility not granted to the helper', data)
        if done.returncode not in (0, 1):
            raise SpaceMoverUnavailable(data.get('reason') or f'space-mover exit {done.returncode}', data)
        return data

    def trusted(self):
        try:
            return bool(self.run('trusted').get('trusted'))
        except SpaceMoverUntrusted:
            return False

    def spaces(self):
        return self.run('spaces')['spaces']

    def displays(self):
        return self.run('displays')['displays']

    def ensure_agent_display(self, width=1920, height=1080):
        """Start `display serve` once as a child and cache its display id. The display lives while the child does."""
        if self._serve is not None and self._serve.poll() is None and self._display is not None:
            return self._display
        binary = self.ensure_binary()
        self._serve = subprocess.Popen([str(binary), 'display', 'serve', '--width', str(width), '--height', str(height)],
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        ready, _, _ = select.select([self._serve.stdout], [], [], self.serve_timeout)
        line = self._serve.stdout.readline() if ready else ''
        try:
            info = json.loads(line)
        except ValueError:
            self.stop()
            raise SpaceMoverUnavailable('display serve did not report a display in time')
        if not info.get('created') or not info.get('active'):
            self.stop()
            raise SpaceMoverUnavailable(info.get('reason') or 'virtual display was not created', info)
        self._display = int(info['id'])
        return self._display

    def stop(self):
        proc, self._serve, self._display = self._serve, None, None
        if proc is None:
            return
        if proc.stdout:
            proc.stdout.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def park(self, window_id):
        """Move a window to the agent display and verify; fall back to the configured Space only if set."""
        display = self.ensure_agent_display()
        result = self.run('move', '--window-id', window_id, '--display', display)
        if result.get('moved'):
            return result
        if self.fallback_space is None:
            raise WindowNotMoved(result.get('reason') or 'window was not moved', result)
        result2 = self.run('move', '--window-id', window_id, '--space', self.fallback_space)
        if result2.get('moved'):
            return result2
        raise WindowNotMoved(result2.get('reason') or 'window was not moved', result2)
