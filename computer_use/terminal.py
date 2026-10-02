"""Agent-owned TUIs through terminal-use 1.4.1's PTY/emulator driver.

One private daemon per facade task; no attachment to an unrelated GUI terminal.
Rendered cells are evidence, never shell stdout or inferred GUI controls. Writes
are never retried. A fresh read verifies a new, non-echo postcondition afterward.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import tempfile
import time
import uuid

from core import Gap

VERSION = '1.4.1'
DEFAULT_DRIVER = Path.home() / '.local/share/computer-use/terminal-use' / VERSION / 'tu'
SGR = re.compile(r'\x1b\[[0-9;]*m')
MAX_REPLY = 512 * 1024
KEYS = {'enter': b'\r', 'tab': b'\t', 'escape': b'\x1b', 'space': b' ', 'backspace': b'\x7f',
        'delete': b'\x1b[3~', 'insert': b'\x1b[2~', 'pageup': b'\x1b[5~', 'pagedown': b'\x1b[6~', 'shift+tab': b'\x1b[Z'}
KEYS.update({name: ('\x1bO' + suffix).encode() for name, suffix in
             zip(('up', 'down', 'right', 'left', 'home', 'end', 'f1', 'f2', 'f3', 'f4'), 'ABCDHFPQRS')})
KEYS.update({'f%d' % (i + 5): ('\x1b[%d~' % code).encode() for i, code in enumerate((15, 17, 18, 19, 20, 21, 23, 24))})


def key_bytes(name):
    if not isinstance(name, str):raise Gap('bad_request: press needs control=<one named key>')
    if name.lower() in KEYS:return list(KEYS[name.lower()])
    if re.fullmatch(r'Ctrl\+[A-Za-z]', name, re.I):return [ord(name[-1].lower()) - 96]
    if re.fullmatch(r'Alt\+[ -~]', name, re.I):return list(('\x1b' + name[-1]).encode())
    if len(name) == 1 and name.isprintable():return list(name.encode())
    raise Gap('bad_request: unsupported terminal key; use a character, Enter, Escape, Tab, Shift+Tab, arrows, Home/End, PageUp/Down, F1-F12 or Ctrl/Alt+letter')


def left(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:raise Gap('terminal_deadline: observation/action budget exhausted')
    return min(5.0, remaining)


class TuDriver:
    def __init__(self, executable=None):
        self.executable = str(executable or os.environ.get('CUA_TERMINAL_DRIVER') or DEFAULT_DRIVER)
        self.process = None
        self.directory = None
        self.env = None

    def start(self, deadline):
        if self.process is not None:
            if self.process.poll() is not None:raise Gap('terminal_driver_lost: private daemon exited; no automatic replacement')
            return
        if not Path(self.executable).is_file():
            raise Gap('terminal_driver_missing: run python3 scripts/install_terminal.py in the runtime checkout')
        try:
            version = subprocess.run([self.executable, '--version'], capture_output=True, timeout=left(deadline), check=True).stdout.decode().strip()
            if version != 'tu ' + VERSION:raise Gap('terminal_driver_version: expected terminal-use ' + VERSION)
            self.directory = tempfile.TemporaryDirectory(prefix='cua-tu-', dir='/tmp')
            self.env = {**os.environ, 'XDG_RUNTIME_DIR': self.directory.name}
            self.process = subprocess.Popen([self.executable, 'daemon', 'start'], env=self.env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            while not (Path(self.directory.name) / 'tu.sock').exists():
                left(deadline)
                if self.process.poll() is not None:raise Gap('terminal_driver_lost: private daemon could not start')
                time.sleep(0.02)
        except (OSError, subprocess.SubprocessError):
            raise Gap('terminal_driver_unavailable: could not start the installed terminal driver') from None

    def request(self, payload, deadline):
        if self.process is None or self.process.poll() is not None:
            raise Gap('terminal_driver_lost: private daemon is unavailable; do not replay input')
        try:
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(left(deadline))
                sock.connect(str(Path(self.directory.name) / 'tu.sock'))
                sock.sendall(json.dumps(payload).encode() + b'\n')
                with sock.makefile('rb') as stream:data = stream.readline(MAX_REPLY + 1)
            if len(data) > MAX_REPLY or not data.endswith(b'\n'):raise ValueError()
            result = json.loads(data)
            if not isinstance(result, dict) or not isinstance(result.get('type'), str):raise ValueError()
        except (OSError, ValueError):
            raise Gap('terminal_transport_failed: no complete driver response; reconcile before any further input') from None
        if result['type'] == 'Error':raise Gap('terminal_driver_refused: driver refused this session request')
        return result

    def png(self, name, deadline):
        if self.process is None or self.process.poll() is not None:raise Gap('terminal_driver_lost: private daemon exited')
        renderer = None
        try:
            # The upstream CLI can auto-start an empty daemon if the original
            # dies mid-capture. Confine and reap its children, and never accept
            # that replacement as this task's original terminal.
            renderer = subprocess.Popen([self.executable, 'screenshot', '--name', name, '--png', '--stdout'], env=self.env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            data, _ = renderer.communicate(timeout=left(deadline))
            if self.process.poll() is not None:raise Gap('terminal_driver_lost: private daemon exited during capture')
            if renderer.returncode:raise Gap('screen_capture_unavailable: terminal renderer failed')
            return data
        except (OSError, subprocess.SubprocessError):
            raise Gap('screen_capture_unavailable: terminal renderer did not return an image') from None
        finally:
            if renderer is not None:
                try:os.killpg(renderer.pid, signal.SIGKILL)
                except ProcessLookupError:pass
                renderer.communicate()

    def close(self):
        if self.process is not None:
            try:self.request({'type': 'Shutdown'}, time.monotonic() + 2)
            except Gap:pass
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        if self.directory is not None:self.directory.cleanup()
        self.process = self.directory = None


class Terminal:
    def __init__(self, driver=None):
        self.driver = driver or TuDriver()
        self.sessions = {}
        self.looks = {}

    def close(self):
        self.driver.close()
        self.sessions.clear();self.looks.clear()

    def request(self, kind, name, deadline, **args):
        return self.driver.request({'type': kind, 'name': name, **args}, deadline)

    def session(self, name):
        if not isinstance(name, str) or name not in self.sessions:
            raise Gap('terminal_not_found: use a terminal ID created by this task; existing GUI tabs are not PTY sessions')
        return self.sessions[name]

    def read(self, name, deadline):
        owned = self.session(name)
        status = self.request('Status', name, deadline)
        if status.get('type') != 'Status' or status.get('name') != name or type(status.get('pid')) is not int:
            raise Gap('terminal_identity_mismatch: driver returned another terminal')
        if owned['pid'] is not None and status['pid'] != owned['pid']:
            raise Gap('terminal_identity_mismatch: terminal process was replaced')
        owned['pid'] = status['pid']  # also reconciles an uncertain launch of this private unique name
        cells = self.request('ScreenshotCells', name, deadline)
        cursor = self.request('Cursor', name, deadline)
        rows, cols = cells.get('rows'), cells.get('cols')
        ansi = cells.get('rows_ansi')
        if (cells.get('type') != 'ScreenshotCells' or type(rows) is not int or type(cols) is not int or
                not 1 <= rows <= 80 or not 1 <= cols <= 240 or not isinstance(ansi, list) or len(ansi) != rows or
                any(not isinstance(s, str) for s in ansi) or cursor.get('type') != 'Cursor' or
                type(cursor.get('row')) is not int or type(cursor.get('col')) is not int or
                not 0 <= cursor['row'] < rows or not 0 <= cursor['col'] < cols or
                status.get('size') != {'cols': cols, 'rows': rows} or type(status.get('alive')) is not bool):
            raise Gap('terminal_snapshot_invalid: inconsistent terminal grid or cursor')
        # Source-generated SGR survives separately; ANSI bytes are never executed
        # by the facade. Comparison includes styling so color-only changes matter.
        lines = [SGR.sub('', row).rstrip() for row in ansi]
        snapshot = {'terminal': name, 'pid': status['pid'], 'rows': rows, 'cols': cols,
            'cursor': {'row': cursor['row'], 'col': cursor['col']}, 'lines': lines, 'ansi_rows': ansi,
            'alive': status['alive'], 'exit_code': status.get('exit_code')}
        snapshot['fingerprint'] = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        return snapshot

    def show(self, state, max_bytes=6000):
        if type(max_bytes) is not int or not 1000 <= max_bytes <= 30000:raise Gap('bad_request: max_bytes must be 1000..30000')
        token = 'term_lk_' + uuid.uuid4().hex
        self.looks[token] = (state['terminal'], state['fingerprint'])
        while len(self.looks) > 32:self.looks.pop(next(iter(self.looks)))
        lines = [{'row': i, 'text': text} for i, text in enumerate(state['lines']) if text]
        # Preserve nondefault style evidence for TUIs whose selection is color-only.
        styled = [{'row': i, 'ansi': text.rstrip()} for i, text in enumerate(state['ansi_rows']) if text.replace('\x1b[0m', '') != SGR.sub('', text)]
        result = {'status': 'ok', 'terminal': state['terminal'], 'look_id': token, 'source': 'terminal_use',
            'untrusted_page_text': True, 'rows': state['rows'], 'cols': state['cols'], 'cursor': state['cursor'],
            'alive': state['alive'], 'exit_code': state['exit_code'], 'lines': lines, 'styled_rows': styled,
            'truncated': {'lines': 0, 'styled_rows': 0}, 'coverage': 'visible_grid_only'}
        while len(json.dumps(result).encode()) > max_bytes and (styled or lines):
            key = 'styled_rows' if styled else 'lines'
            result[key].pop();result['truncated'][key] += 1
        return result

    def look(self, name, max_bytes=6000, screen=False):
        deadline = time.monotonic() + 10
        if name == 'list':return {'status': 'ok', 'terminals': list(self.sessions), 'source': 'terminal_use', 'untrusted_page_text': True}
        state = self.read(name, deadline)
        result = self.show(state, max_bytes)
        if screen:
            from screen import validate_image
            data = self.driver.png(name, deadline)
            width, height = validate_image(data, 'image/png')
            # Rendering is a separate sample: do not imply the PNG and text are atomic.
            result['image'] = {'width': width, 'height': height, 'source': 'terminal_use_renderer', 'sample': 'after_text', 'action_binding': False}
            result['_screen_image'] = {'data': base64.b64encode(data).decode(), 'mimeType': 'image/png'}
        return result

    @staticmethod
    def validate(name, steps, expect, budget_s, look_id):
        if expect is not None or not isinstance(steps, list) or not 1 <= len(steps) <= 20:
            raise Gap('bad_request: terminal actions need 1..20 steps and top-level expect=null')
        if type(budget_s) not in (int, float) or not 0 < budget_s <= 20:raise Gap('bad_request: terminal budget_s must be 0..20 seconds')
        normalized = []
        for i, raw in enumerate(steps):
            if not isinstance(raw, dict):raise Gap('bad_request: terminal step must be an object')
            step = {k: v for k, v in raw.items() if v is not None}
            kind = step.get('do')
            allowed = {'launch': {'argv', 'cwd', 'width', 'height'}, 'press': {'control'}, 'type': {'text'}, 'verify': set(), 'close': set()}
            if not isinstance(kind, str) or kind not in allowed or set(step) - ({'do', 'expect', 'goal'} | allowed[kind]):
                raise Gap('bad_request: terminal supports launch(argv,cwd), press(control=key), type(text), verify, close only')
            if 'expect' in step and (not isinstance(step['expect'], str) or not step['expect'].strip() or len(step['expect']) > 500):
                raise Gap('bad_request: expect must be concise literal terminal text')
            if kind == 'launch':
                argv, cwd = step.get('argv'), step.get('cwd')
                if name != 'new' or i != 0 or not isinstance(argv, list) or not 1 <= len(argv) <= 64 or any(not isinstance(s, str) or '\0' in s or len(s) > 4096 for s in argv) or not argv[0]:
                    raise Gap('bad_request: launch is first, terminal=new, with explicit argv')
                if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
                    raise Gap('bad_request: terminal launch requires an existing absolute cwd')
                for key, low, high, default in (('width', 20, 240, 100), ('height', 5, 80, 30)):
                    value = step.get(key, default)
                    if type(value) is not int or not low <= value <= high:raise Gap('bad_request: terminal cell dimensions are out of range')
                    step[key] = value
            elif name == 'new' and i == 0:raise Gap('bad_request: terminal=new needs launch first')
            if kind == 'press':step['_keys'] = key_bytes(step.get('control'))
            if kind == 'type' and (not isinstance(step.get('text'), str) or not step['text'] or len(step['text']) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in step['text'])):
                raise Gap('bad_request: type requires printable literal text; send control keys with press')
            if kind == 'verify' and 'expect' not in step:raise Gap('expect_required: terminal verify needs expect')
            if kind == 'close' and (i != len(steps) - 1 or 'expect' in step):raise Gap('bad_request: close is final and has no expect')
            if i < len(steps) - 1 and 'expect' not in step:raise Gap('expect_required: nonfinal terminal steps need expect')
            normalized.append(step)
        if name != 'new' and any(s['do'] != 'verify' for s in normalized) and not look_id:
            raise Gap('look_required: terminal input needs the look_id from this terminal')
        return normalized

    def do(self, name, steps, expect=None, look_id=None, budget_s=20):
        steps = self.validate(name, steps, expect, budget_s, look_id)
        if name != 'new':self.session(name)
        if look_id is not None and (look_id not in self.looks or self.looks[look_id][0] != name):
            raise Gap('terminal_look_mismatch: use a look_id from this exact terminal in this task')
        deadline = time.monotonic() + budget_s
        rows = [];delivery = 'none';state = None
        try:
            for step in steps:
                kind = step['do'];delivery = 'none'
                if kind == 'launch':
                    if len(self.sessions) >= 8:raise Gap('terminal_capacity: at most eight terminals per task')
                    self.driver.start(deadline)
                    name = 'term_' + uuid.uuid4().hex
                    self.sessions[name] = {'pid': None, 'typed': ''}
                    delivery = 'uncertain'
                    result = self.request('Run', name, deadline, command=step['argv'][0], args=step['argv'][1:],
                        cwd=step['cwd'], size={'cols': step['width'], 'rows': step['height']},
                        scrollback=1000, env=[], term='xterm-256color', shell=False)
                    if result.get('type') != 'SessionCreated' or result.get('name') != name or type(result.get('pid')) is not int:
                        raise Gap('terminal_identity_mismatch: launch response did not identify the requested session')
                    self.sessions[name]['pid'] = result['pid'];delivery = 'sent'
                    before = ''
                else:
                    state = self.read(name, deadline)
                    if look_id and self.looks[look_id][1] != state['fingerprint']:
                        return {**self.show(state), 'status': 'refused', 'reason': 'terminal_changed_since_look', 'delivery': 'none', 'steps': rows}
                    before = '\n'.join(state['lines'])
                    if not state['alive'] and kind in ('press', 'type'):raise Gap('terminal_exited: process exited; no input sent')
                    if kind != 'verify':
                        delivery = 'uncertain'
                        if kind == 'type':self.sessions[name]['typed'] = (self.sessions[name]['typed'] + step['text'])[-8192:]
                        payload = {'keys': step['_keys']} if kind == 'press' else {'text': step['text']} if kind == 'type' else {}
                        answer = self.request({'press': 'Press', 'type': 'Type', 'close': 'Kill'}[kind], name, deadline, **payload)
                        if answer.get('type') != 'Ok':raise Gap('terminal_delivery_unverified: driver did not acknowledge input')
                        delivery = 'sent'
                    if kind == 'close':
                        inventory = self.driver.request({'type': 'List'}, deadline)
                        if inventory.get('type') != 'SessionList' or not isinstance(inventory.get('sessions'), list) or any(not isinstance(s, dict) or s.get('name') == name for s in inventory['sessions']):
                            raise Gap('terminal_close_unverified: session removal was not observed')
                        del self.sessions[name]
                        for token, (owner, _) in list(self.looks.items()):
                            if owner == name:del self.looks[token]
                        rows.append({'do': kind, 'status': 'done'})
                        return {'status': 'done', 'terminal': name, 'closed': True, 'steps': rows, 'delivery': delivery}
                target = step.get('expect')
                # Input can echo late, including after a later Enter. Keep a
                # bounded history rather than treating the next press as proof.
                echo = kind != 'verify' and target is not None and target in self.sessions[name]['typed']
                preexisting = kind != 'verify' and target is not None and target in before
                while True:
                    state = self.read(name, deadline)
                    satisfied = target is not None and target in '\n'.join(state['lines']) and not echo and not preexisting
                    if satisfied or target is None or echo or preexisting or not state['alive'] or deadline - time.monotonic() < 0.2:break
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
                status = ('observed' if kind == 'verify' else 'done') if satisfied else 'delivered_unverified' if delivery == 'sent' else 'unverified'
                shown = self.show(state);look_id = shown['look_id']
                rows.append({'do': kind, 'status': status})
                if not satisfied:
                    return {**shown, 'status': status, 'steps': rows, 'delivery': delivery,
                            'reason': 'terminal_postcondition_unverified', 'hint': 'Current rendered screen is returned. Reconcile it before choosing further input; silence and echoed text are not success.'}
            return {**shown, 'status': status, 'steps': rows, 'delivery': delivery}
        except Gap as error:
            return {'status': 'failed' if delivery != 'none' else 'refused', 'reason': str(error).split(':', 1)[0],
                    'terminal': name, 'delivery': delivery, 'steps': rows, 'message': str(error),
                    'hint': 'Call look on this terminal to reconcile; no input was automatically retried.'}


def backend(f):
    if f._terminal is None:f._terminal = Terminal()
    return f._terminal


def check_target(f, *other):
    if any(value is not None for value in other):raise Gap('bad_request: terminal is a separate target; use terminal steps without desktop/device selectors or fields')
    if f.on_behalf:raise Gap('terminal_context_unsupported: headless terminals use an isolated task context; existing user terminal windows use title or pid+window_id through Cua Driver')


def refusal(error):
    return {'status': 'refused', 'reason': str(error).split(':', 1)[0], 'message': str(error), 'delivery': 'none'}
