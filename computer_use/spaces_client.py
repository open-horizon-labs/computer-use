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
# Keep uncertain owners and their pipes alive even if a task drops its client.
# Process exit still releases a display: this is containment, not OS cancellation.
RETAINED_OWNERS = []


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
    def __init__(self, binary=None, fallback_space=None, build_timeout=180, call_timeout=30, serve_timeout=10, fault_path=None, stop_timeout=5, owner_scan=None):
        self.binary = Path(binary or os.environ.get('CUA_SPACE_MOVER') or DEFAULT_BINARY)
        self.fallback_space = fallback_space
        self.build_timeout = build_timeout
        self.call_timeout = call_timeout
        self.serve_timeout = serve_timeout
        self.stop_timeout = stop_timeout
        self.fault_path = Path(fault_path) if fault_path is not None else Path(os.environ.get('CUA_CACHE_DIR') or Path.home() / '.cache' / 'computer-use') / 'display-fault.json'
        self._fault = None
        self._journal_fd = None
        self._serve = None
        self._display = None
        from display_owners import known_display_owners
        self.owner_scan = owner_scan or known_display_owners

    def _check_fault(self):
        if self._fault or (self._journal_fd is None and self.fault_path.exists()):
            raise SpaceMoverUnavailable('display lifecycle blocked; inspect %s and retained owners before operator recovery' % self.fault_path,
                                        self._fault or {'code': 'display_lifecycle_blocked'})

    def _write_state(self, state):
        payload = json.dumps(state).encode()
        os.lseek(self._journal_fd, 0, os.SEEK_SET)
        os.write(self._journal_fd, payload)
        os.ftruncate(self._journal_fd, len(payload))
        os.fsync(self._journal_fd)

    def _claim_lifecycle(self):
        """A pending record survives a controller crash and excludes other display creators."""
        try:
            self.fault_path.parent.mkdir(parents=True, exist_ok=True)
            self._journal_fd = os.open(self.fault_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            self._write_state({'code': 'display_lifecycle_pending', 'controller_pid': os.getpid(), 'owner_pid': None})
        except OSError as error:
            self._fault = {'code': 'display_lifecycle_blocked', 'persistence_error': type(error).__name__}
            raise SpaceMoverUnavailable('cannot claim durable display lifecycle record; nothing was opened', self._fault)

    def _latch(self, reason):
        self._fault = {'code': 'display_lifecycle_uncertain', 'reason': reason,
                       'owner_pid': self._serve.pid if self._serve else None, 'display_id': self._display}
        if self._serve is not None and self._serve not in RETAINED_OWNERS:
            RETAINED_OWNERS.append(self._serve)
        try:
            if self._journal_fd is not None:
                self._write_state(self._fault)
            else:
                self.fault_path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.fault_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as out:
                    json.dump(self._fault, out)
                    out.flush()
                    os.fsync(out.fileno())
        except FileExistsError:
            pass
        except OSError as error:
            self._fault['persistence_error'] = type(error).__name__
        raise SpaceMoverUnavailable(reason, self._fault)

    def _ready_line(self):
        """Bound both time and bytes; select followed by readline can hang on a partial line."""
        deadline = time.monotonic() + self.serve_timeout
        data = bytearray()
        fd = self._serve.stdout.fileno()
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                break
            part = os.read(fd, 4096)
            if not part:
                break
            data.extend(part)
            if len(data) > 16384:
                self._latch('display serve exceeded its startup output limit')
            if b'\n' in data:
                return bytes(data).split(b'\n', 1)[0]
        self._latch('display serve did not report a complete display record in time')

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
        self._check_fault()
        if self._serve is not None and self._serve.poll() is None and self._display is not None:
            return self._display
        if self._serve is not None:
            self._latch('display owner exited unexpectedly; no replacement was started')
        if self.owner_scan():
            raise SpaceMoverUnavailable('other known display owners are present; inspect them before creation, no automatic signals')
        binary = self.ensure_binary()
        self._claim_lifecycle()
        try:
            self._serve = subprocess.Popen([str(binary), 'display', 'serve', '--width', str(width), '--height', str(height)],
                                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self._write_state({'code': 'display_lifecycle_active', 'controller_pid': os.getpid(), 'owner_pid': self._serve.pid})
            line = self._ready_line()
        except OSError:
            self._latch('display startup transport or journal failed; no automatic retry')
        try:
            info = json.loads(line)
            valid = isinstance(info, dict) and info.get('created') is True and info.get('active') is True and type(info.get('id')) is int and info['id'] > 0
        except (ValueError, UnicodeError, RecursionError):
            valid = False
        if not valid:
            self._latch('display serve returned an invalid or unverified display record')
        self._display = info['id']
        return self._display

    def stop(self):
        proc = self._serve
        if proc is None:
            return
        if self._fault:
            return  # operator recovery owns uncertain teardown; never signal automatically
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=self.stop_timeout)
            except subprocess.TimeoutExpired:
                self._latch('display owner did not exit during teardown; retained without kill or retry')
            except OSError:
                self._latch('display owner teardown transport failed; retained without retry')
        if proc.stdout:
            proc.stdout.close()
        if self._display is not None:
            try:
                removed = self._retirement_verified()
            except Exception:
                removed = False
            if not removed:
                self._latch('display removal could not be independently verified after owner exit')
        if self._journal_fd is not None:
            try:
                held, current = os.fstat(self._journal_fd), self.fault_path.stat()
                if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
                    self._latch('display lifecycle record changed during ownership')
                self.fault_path.unlink()
                os.close(self._journal_fd)
                self._journal_fd = None
            except OSError:
                self._latch('could not clear verified display lifecycle record')
        self._serve, self._display = None, None

    def _retirement_verified(self):
        inventory = self.run('displays', '--online')
        remaining = inventory.get('displays')
        if inventory.get('inventory') != 'online' or not isinstance(remaining, list) or len(remaining) >= 64:
            return False
        if not all(isinstance(d, dict) and type(d.get('id')) is int and d['id'] > 0 for d in remaining):
            return False
        ids = [d['id'] for d in remaining]
        return len(ids) == len(set(ids)) and self._display not in ids

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
