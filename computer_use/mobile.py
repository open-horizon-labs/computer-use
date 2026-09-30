"""Devices (CE-FACADE-008): Android and iOS through mobile-mcp, behind the same look/do contract as a Mac window.

A device is addressed by `device` (an adb id such as emulator-5554, or an iOS simulator UDID) instead of title or pid+window_id. The facade starts
mobile-mcp itself, as a child MCP client over stdio (StdioBackend), the first time a look or do targets a device: there is no setup step, and
when Node.js is missing the answer is a typed refusal (mobile_backend_unavailable) naming what to install, never a crash.

The contract is unchanged, only the observation and the delivery differ:
  - LOOK  reads mobile_list_elements_on_screen (json) and maps it to the look shape (text, controls, inputs, toggles, dialogs, look_id).
  - DO    resolves a press/type control on a FRESH element list read immediately before acting (exact label, else refuse: control_not_found,
          control_ambiguous, control_not_pressable, destructive_control), taps by the fresh element's ref (else the centre of its fresh bounds),
          and verifies every step on another fresh list against `expect`. The tap's own "Clicked on" never counts: upstream Cua found taps
          silently dropped on a locked phone, so a tap that changed nothing is reported screen_unchanged_after_action, never done.
mobile-mcp lists every node of the screen flat, without hierarchy and without a clickable flag, so a device look has no records (record_kind none) and
where.lines is refused; a control is an element whose type is a button, switch, cell and the like, and any other element that carries the label can be
pressed by it when no button does (nested nodes of one control collapse to the outermost).
Everything the device displays is untrusted page text, exactly as in a Mac look.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import threading
from datetime import timedelta

import look as lk
from core import Gap

PACKAGE = '@mobilenext/mobile-mcp@1.0.6'
DEFAULT_COMMAND = ['npx', '-y', PACKAGE]
COMMAND_ENV = 'CUA_MOBILE_MCP'          # operator override of the command line (tests use it for a fake server); not a secret
START_TIMEOUT_S = 180.0                # the first npx run downloads the package
CALL_TIMEOUT_S = 30.0
ELEMENTS_PREFIX = 'Found these elements on screen: '
DEVICE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}')
LIST_TOKEN = 'list'                     # `look`(device="list") discovers devices; it is not a device id
TAP_DELAYS = (0.4, 0.8)                # seconds before the later verification observations after a tap (bounded, deterministic)
LOAD_DELAYS = (0.5, 1.0, 1.5, 2.0)     # after an open_url: a page takes longer to appear
SCREEN_SIGNATURE = 'device_screen'
TEXT_MAX_LINES = lk.TEXT_MAX_LINES
CONTROL_MAX = lk.CONTROL_LIST_MAX
INPUT_MAX = lk.INPUT_LIST_MAX
DIALOG_MAX = lk.DIALOG_MAX
DEVICE_LIST_MAX = 20
FOUND_MAX = 12
REFUSED = frozenset({'mobile_backend_unavailable', 'device_not_found', 'mobile_device_agent_missing', 'bad_request', 'not_supported_on_device',
                     'where_not_supported_on_device', 'look_required', 'unknown_look_id', 'look_window_mismatch', 'destructive_control', 'expect_required'})


class MobileGap(Gap):
    """A typed mobile failure: reason is the token a caller switches on; delivery says whether an action may have reached the device.
    The message is written here; raw mobile-mcp text (paths, stack traces) is never carried."""
    def __init__(self, reason, message, delivery='none'):
        super().__init__('%s: %s' % (reason, message))
        self.reason, self.delivery = reason, delivery


class _Died(Exception):
    """The mobile-mcp process is gone (internal: call() restarts it once for a read, never re-sends an action)."""


def command_from_env(env=None):
    raw = (env if env is not None else os.environ).get(COMMAND_ENV)
    return shlex.split(raw) if raw and raw.strip() else list(DEFAULT_COMMAND)


def classify(text, action=False):
    """Map mobile-mcp's answer text to a typed reason WITHOUT echoing it (it carries local paths): (reason, message, delivery)."""
    low = (text or '').lower()
    if 'agent is not installed' in low:
        return ('mobile_device_agent_missing', 'the device agent (mobile-mcp\'s on-device helper) is not installed on this device; an iOS simulator or device needs it before its screen can be read (see the mobile-mcp setup notes). Nothing was done', 'none')
    if 'not found' in low and 'device' in low:
        return ('device_not_found', 'no such device is connected; list them with `look`(device="list") and use an id from that list. Nothing was done', 'none')
    if action:
        return ('mobile_action_failed', 'mobile-mcp did not confirm the action; it may or may not have reached the device, so verify the screen before acting again', 'uncertain')
    return ('mobile_observation_failed', 'mobile-mcp could not read the device screen (is the device unlocked, booted and reachable?)', 'none')


class StdioBackend:
    """mobile-mcp as a child MCP client over stdio, owned by one thread with its own event loop. Started on first use, kept for the process lifetime,
    restarted once when it died (read-only calls only: an action is never re-sent), closed by close()."""

    def __init__(self, command=None, env=None, which=shutil.which, start_timeout=START_TIMEOUT_S):
        self.command = list(command) if command else command_from_env()
        self.env, self.which, self.start_timeout = env, which, start_timeout
        self.starts = 0
        self._lock = threading.RLock()
        self._thread = None
        self._box = None

    # -- lifecycle ------------------------------------------------------------------------------------------------------------------
    def _child_env(self):
        env = dict(os.environ if self.env is None else self.env)
        env.setdefault('MOBILEMCP_DISABLE_TELEMETRY', '1')  # mobile-mcp posts usage events unless told not to; the operator can set it to an empty string to allow them
        return env

    def _alive(self):
        return bool(self._thread and self._thread.is_alive() and self._box and not self._box['dead'].is_set() and 'session' in self._box)

    def _unavailable(self, why):
        return MobileGap('mobile_backend_unavailable', why)

    def _start(self):
        exe = self.command[0]
        if self.which(exe) is None:
            if exe == 'npx':
                raise self._unavailable('Node.js (npx) was not found on PATH; install Node.js 18 or newer (https://nodejs.org) and call again: the facade starts @mobilenext/mobile-mcp itself, there is nothing else to set up')
            raise self._unavailable('the configured %s command %r was not found on PATH' % (COMMAND_ENV, exe))
        ready = threading.Event()
        box = {'dead': None, 'loop': None, 'stop': None, 'error': None}
        async def main():
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            box['loop'] = asyncio.get_running_loop()
            box['dead'] = asyncio.Event()
            box['stop'] = asyncio.Event()
            box['dead_flag'] = False
            try:
                params = StdioServerParameters(command=self.command[0], args=self.command[1:], env=self._child_env())
                with open(os.devnull, 'w') as quiet:
                    async with stdio_client(params, errlog=quiet) as (read, write):
                        async with ClientSession(read, write) as session:
                            await asyncio.wait_for(session.initialize(), self.start_timeout)
                            box['session'] = session
                            ready.set()
                            await box['stop'].wait()
            except BaseException as error:  # noqa: BLE001 - reported as a typed refusal by the starter
                box['error'] = error
            finally:
                box['dead'].set()
                ready.set()
        thread = threading.Thread(target=lambda: asyncio.run(main()), name='mobile-mcp', daemon=True)
        thread.start()
        self._thread, self._box = thread, box
        self.starts += 1
        if not ready.wait(self.start_timeout + 5) or 'session' not in box:
            error = box.get('error')
            self._teardown()
            raise self._unavailable('mobile-mcp (%s) did not start%s; check that npx can fetch it (network) and that Node.js is 18 or newer' % (PACKAGE, (' (%s)' % type(error).__name__) if error else ' in time'))

    def _teardown(self):
        box, thread = self._box, self._thread
        self._box = self._thread = None
        if not box or not thread:
            return
        loop = box.get('loop')
        try:
            if loop and box.get('stop') is not None and not loop.is_closed():
                loop.call_soon_threadsafe(box['stop'].set)
        except RuntimeError:
            pass
        thread.join(10)

    def close(self):
        with self._lock:
            self._teardown()

    # -- calls ----------------------------------------------------------------------------------------------------------------------
    def _invoke(self, tool, args, timeout):
        box = self._box
        async def run():
            call = asyncio.ensure_future(box['session'].call_tool(tool, args, read_timeout_seconds=timedelta(seconds=timeout)))
            dead = asyncio.ensure_future(box['dead'].wait())
            try:
                done, _ = await asyncio.wait({call, dead}, timeout=timeout + 5, return_when=asyncio.FIRST_COMPLETED)
            finally:
                if not call.done() and not dead.done():
                    pass
            if call in done:
                dead.cancel()
                try:
                    return call.result()
                except Exception as error:  # the transport broke under the call, or mobile-mcp answered an MCP-level error
                    if box['dead'].is_set() or type(error).__name__ in ('ClosedResourceError', 'BrokenResourceError', 'EndOfStream'):
                        raise _Died()
                    raise
            call.cancel()
            dead.cancel()
            if dead in done:
                raise _Died()
            raise TimeoutError(tool)
        future = asyncio.run_coroutine_threadsafe(run(), box['loop'])
        try:
            result = future.result(timeout + 10)
        except (_Died, TimeoutError):
            raise
        except Exception as error:  # noqa: BLE001
            if type(error).__name__ == 'McpError' and 'closed' in str(error).lower():
                raise _Died()
            raise MobileGap('mobile_observation_failed' if tool.startswith(('mobile_list', 'mobile_get')) else 'mobile_action_failed',
                            'mobile-mcp answered an error to %s (%s)' % (tool, type(error).__name__), 'none' if tool.startswith(('mobile_list', 'mobile_get')) else 'uncertain')
        text = '\n'.join(getattr(c, 'text', '') for c in (result.content or []) if getattr(c, 'type', '') == 'text')
        return text, bool(getattr(result, 'isError', False))

    def call(self, tool, args, mutating=False, timeout=CALL_TIMEOUT_S):
        """(text, is_error). Raises MobileGap. A dead process is restarted ONCE and a read-only call re-sent; an action is never re-sent."""
        with self._lock:
            if not self._alive():
                self._teardown()
                self._start()
            try:
                return self._invoke(tool, args, timeout)
            except _Died:
                self._teardown()
                if mutating:
                    raise MobileGap('mobile_action_failed', 'the mobile-mcp process exited during the action; it may or may not have reached the device, so verify the screen before acting again', 'uncertain')
                self._start()  # the one restart
                try:
                    return self._invoke(tool, args, timeout)
                except (_Died, TimeoutError):
                    self._teardown()
                    raise self._unavailable('mobile-mcp exited again right after it was restarted')
            except TimeoutError:
                self._teardown()  # a hung child is killed; the next call starts a fresh one
                raise MobileGap('mobile_backend_timeout', 'mobile-mcp did not answer %s within %ds%s' % (tool, timeout, '; the action may have reached the device' if mutating else ''), 'uncertain' if mutating else 'none')


# -- element mapping ---------------------------------------------------------------------------------------------------------------------

ANDROID_CONTROL = re.compile(r'(?:Button|ImageButton|ToggleButton|CheckBox|RadioButton|Switch|SwitchCompat|Spinner|Chip|TabView|MenuItemView|ActionMenuItemView)')
IOS_CONTROL = frozenset({'Button', 'Link', 'Switch', 'Toggle', 'Tab', 'Cell', 'MenuItem', 'Key'})
TOGGLE_KINDS = frozenset({'CheckBox', 'RadioButton', 'Switch', 'SwitchCompat', 'ToggleButton', 'Toggle'})
ANDROID_INPUT = re.compile(r'.*EditText|AutoCompleteTextView|MultiAutoCompleteTextView|SearchAutoComplete')
IOS_INPUT = frozenset({'TextField', 'SecureTextField', 'SearchField', 'TextView'})
PLAIN_TEXT = frozenset({'TextView', 'StaticText', 'Text', 'CheckedTextView', 'Label', 'Heading'})
SECRET = re.compile(r'secure|password|passcode|pin', re.I)
DIALOG_IDS = frozenset({'parentPanel'})
DIALOG_KINDS = frozenset({'Alert', 'Sheet', 'Dialog', 'Popover'})


def _text(value):
    return lk.clean(value) if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ''


def _num(value):
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def normalize(raw, index):
    """One mobile-mcp element (json) in the form the look and the plan use. Fields: type, text, label, name, value, identifier, coordinates
    {x,y,width,height}, ref, and only when non-default focused, selected, checked, enabled=false."""
    box = raw.get('coordinates') if isinstance(raw.get('coordinates'), dict) else {}
    full = str(raw.get('type') or '')
    android = '.' in full
    kind = re.sub(r'^XCUIElementType', '', full.rsplit('.', 1)[-1])
    text, label, name, value = (_text(raw.get(k)) for k in ('text', 'label', 'name', 'value'))
    ident = _text(raw.get('identifier'))
    tail = re.split(r'[/:]', ident)[-1] if ident else ''
    if (android and ANDROID_INPUT.fullmatch(kind)) or (not android and kind in IOS_INPUT):
        role = 'input'
    elif (android and ANDROID_CONTROL.fullmatch(kind)) or (not android and kind in IOS_CONTROL):
        role = 'control'
    else:
        role = 'text'
    names = list(dict.fromkeys(n for n in (text, label, name) if n))
    return {'i': index, 'ref': raw.get('ref') if isinstance(raw.get('ref'), str) and raw.get('ref') else None, 'type': full, 'kind': kind, 'android': android, 'role': role,
            'text': text, 'label': label, 'name': name, 'value': value, 'id': ident, 'id_tail': tail, 'names': names,
            'enabled': raw.get('enabled') is not False, 'checked': raw.get('checked') is True, 'selected': raw.get('selected') is True, 'focused': raw.get('focused') is True,
            'toggle': kind in TOGGLE_KINDS, 'secret': kind == 'SecureTextField' or bool(role == 'input' and SECRET.search(tail)),
            'bounds': (_num(box.get('x')), _num(box.get('y')), _num(box.get('width')), _num(box.get('height')))}


def parse_elements(text):
    if not isinstance(text, str) or not text.startswith(ELEMENTS_PREFIX):
        reason, message, delivery = classify(text)
        raise MobileGap(reason, message, delivery)
    try:
        raw = json.loads(text[len(ELEMENTS_PREFIX):])
    except ValueError:
        raise MobileGap('mobile_observation_failed', 'mobile-mcp answered an element list that is not JSON')
    if not isinstance(raw, list):
        raise MobileGap('mobile_observation_failed', 'mobile-mcp answered an element list that is not a list')
    return [normalize(r, i) for i, r in enumerate(raw) if isinstance(r, dict)]


def label_of(e):
    """What the control is called: its text, else its accessibility label / content-desc, else its name; a button with none falls back to its resource id."""
    return (e['names'][0] if e['names'] else '') or (e['id_tail'] if e['role'] in ('control', 'input') else '')


def content_of(e):
    if e['secret']:
        return '(hidden)' if (e['value'] or e['text']) else ''
    return e['value'] or (e['text'] if e['role'] == 'input' else '')


def inside(inner, outer):
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    return ow > 0 and oh > 0 and ix >= ox - 1 and iy >= oy - 1 and ix + iw <= ox + ow + 1 and iy + ih <= oy + oh + 1


def area(e):
    return e['bounds'][2] * e['bounds'][3]


def live(e):
    return e['enabled'] and area(e) > 0


def platform_of(els):
    return 'android' if any(e['android'] for e in els) else ('ios' if els else None)


def tagged_line(e):
    name = e['names'][0] if e['names'] else ''
    if not name:
        return None
    if e['kind'] in PLAIN_TEXT:
        return name
    return ('image: ' if e['kind'].endswith('ImageView') or e['kind'] in ('Image', 'Icon') else 'group: ') + name


def dialog_roots(els):
    return [e for e in els if (e['id_tail'] in DIALOG_IDS and e['id'].startswith('android:id/')) or (not e['android'] and e['kind'] in DIALOG_KINDS)]


def analyze(els):
    """Structure of one element list, no model: dialogs, page text, controls, inputs, toggles. Nothing here is a record: the list has no hierarchy."""
    members, dialogs = set(), []
    for root in dialog_roots(els):
        inner = [e for e in els if e['i'] > root['i'] and inside(e['bounds'], root['bounds'])]
        members |= {root['i']} | {e['i'] for e in inner}
        lines = []
        for e in inner:
            line = tagged_line(e) if e['role'] == 'text' else None
            if line and line not in lines:
                lines.append(line)
        dialogs.append({'controls': [label_of(e)[:40] for e in inner if e['role'] == 'control' and e['enabled'] and label_of(e)],
                        'lines': [lk.cut(x)[0] for x in lines[:lk.LINE_MAX_LINES]]})
    rest = [e for e in els if e['i'] not in members]
    plain = {lk.norm(e['names'][0]) for e in rest if e['role'] == 'text' and e['kind'] in PLAIN_TEXT and e['names']}
    text = []
    for e in rest:
        if e['role'] != 'text':
            continue
        line = tagged_line(e)
        if not line or (e['kind'] not in PLAIN_TEXT and lk.norm(e['names'][0]) in plain):
            continue  # a group or image that only repeats a text shown as text
        if line not in text:
            text.append(line)
    controls = list(dict.fromkeys(label_of(e)[:40] for e in rest if e['role'] == 'control' and e['enabled'] and label_of(e) and area(e) > 0))
    disabled = list(dict.fromkeys(label_of(e)[:40] for e in rest if e['role'] == 'control' and not e['enabled'] and label_of(e)))
    inputs = [{'label': (e['label'] or e['name'] or e['id_tail'])[:40], 'value': content_of(e)[:30]} for e in rest if e['role'] == 'input']
    toggles = [{'label': label_of(e)[:40], 'state': 'checked' if (e['checked'] or e['value'] in ('1', 'true', 'on')) else 'unchecked'} for e in rest if e['role'] == 'control' and e['toggle'] and label_of(e)]
    state = sorted([e['kind'], label_of(e), str(e['enabled']), str(e['checked']), str(e['selected']), str(e['focused']), content_of(e) if e['role'] == 'input' else ''] for e in els if e['role'] in ('control', 'input'))
    return {'dialogs': dialogs, 'text': text, 'controls': controls, 'disabled': disabled, 'inputs': inputs, 'toggles': toggles, 'control_state': state,
            'counts': {'elements': len(els), 'controls': sum(1 for e in els if e['role'] == 'control')}}


def signature(els):
    """The screen as it reads: a change in any element's name, content, state or place changes it."""
    return json.dumps([[e['type'], e['names'], e['value'], e['id'], e['enabled'], e['checked'], e['selected'], e['focused'], e['bounds']] for e in els], ensure_ascii=False, sort_keys=True)


NOTE_FLAT = ('a device look has no records: mobile-mcp lists the screen flat, without hierarchy or a clickable flag. Press by the exact label of a control '
             '(a button, switch or cell first, else any element that carries the label); where.lines is not available')


def check_device(device):
    if not isinstance(device, str) or not DEVICE_ID.fullmatch(device):
        raise Gap('bad_request: device is the id `look`(device="list") shows (an adb id such as emulator-5554, or an iOS simulator UDID)')


# -- discovery ---------------------------------------------------------------------------------------------------------------------------

class Mobile:
    """The facade's view of mobile-mcp: typed reads and actions over any backend with call(tool, args, mutating) -> (text, is_error) and close()."""
    def __init__(self, backend=None):
        self.backend = backend

    def _backend(self):
        if self.backend is None:
            self.backend = StdioBackend()
        return self.backend

    def close(self):
        if self.backend is not None:
            try:
                self.backend.close()
            except Exception:  # noqa: BLE001 - closing must never raise at shutdown
                pass

    def devices(self):
        text, error = self._backend().call('mobile_list_available_devices', {})
        try:
            rows = json.loads(text).get('devices') if not error else None
        except (ValueError, AttributeError):
            rows = None
        if not isinstance(rows, list):
            raise MobileGap('mobile_observation_failed', 'mobile-mcp could not list devices')
        return [{k: _text(d.get(k))[:60] for k in ('id', 'name', 'platform', 'type', 'version', 'state') if d.get(k) is not None} for d in rows if isinstance(d, dict)][:DEVICE_LIST_MAX]

    def elements(self, device):
        text, error = self._backend().call('mobile_list_elements_on_screen', {'device': device, 'format': 'json'})
        return parse_elements(text)

    def _act(self, tool, args, ok_prefix):
        text, error = self._backend().call(tool, args, mutating=True)
        if error or not (text or '').startswith(ok_prefix):
            reason, message, delivery = classify(text, action=True)
            raise MobileGap(reason, message, delivery)

    def tap(self, device, element):
        """By the ref of the element read a moment ago when mobile-mcp gave one (valid while the screen has not changed), else the centre of its fresh bounds."""
        x, y, w, h = element['bounds']
        args = {'device': device, 'ref': element['ref']} if element['ref'] else {'device': device, 'x': x + w // 2, 'y': y + h // 2}
        self._act('mobile_click_on_screen_at_coordinates', args, 'Clicked on')

    def type_keys(self, device, text):
        self._act('mobile_type_keys', {'device': device, 'text': text, 'submit': False}, 'Typed text')

    def open_url(self, device, url):
        self._act('mobile_open_url', {'device': device, 'url': url}, 'Opened URL')


def bridge(f):
    if getattr(f, '_mobile', None) is None:
        f._mobile = Mobile()
    return f._mobile


def discovery(f):
    """`look`(device="list"): the devices mobile-mcp sees beside the Mac windows the Driver sees. Read-only."""
    out = {'status': 'ok', 'untrusted_page_text': True, 'notice': lk.NOTICE, 'devices': [], 'windows': []}
    try:
        out['devices'] = bridge(f).devices()
    except MobileGap as gap:
        out['devices_unavailable'] = {'reason': gap.reason, 'message': str(gap)}
    try:
        out['windows'] = [{k: w[k] for k in ('app_name', 'title') if k in w} for w in f.windows()['windows']][:30]
    except Exception as error:  # noqa: BLE001 - the Mac side being down must not hide the devices
        out['windows_unavailable'] = {'reason': f._do_reason(str(error)) if isinstance(error, Gap) else type(error).__name__}
    out['hint'] = 'Pass device=<an id from devices> to `look` and `do` to work on a phone or emulator, or title=<a window title> for a Mac window.'
    return out


# -- look --------------------------------------------------------------------------------------------------------------------------------

def look(f, device, fields=None, max_records=40, max_bytes=6000, focus=None, max_lines=6, line_chars=60):
    """Read-only look at a device screen, or device="list" for discovery. Same response shape as a window look (no records)."""
    t0 = f.clock()
    try:
        if device == LIST_TOKEN:
            return discovery(f)
        lk.check_look_args(None, max_records, max_bytes, focus, max_lines, line_chars)
        check_device(device)
        if fields is not None:
            raise Gap('not_supported_on_device: fields (the extraction model) read records, and a device screen has none')
        els = bridge(f).elements(device)
        terms = lk.focus_terms(focus)
        a = analyze(els)
        shown, lost = [], 0
        for line in a['text']:
            text, was_cut = lk.cut(line, line_chars)
            shown.append(text)
            lost += int(was_cut)
        match = (lambda line: not terms or any(t in lk.norm(line) for t in terms))
        kept_text = [t for t in shown if match(t)]
        kept_controls = [c for c in a['controls'] if match(c)]
        notes = [NOTE_FLAT]
        if not els:
            notes.append('the device listed no elements: it may be locked, asleep or showing a secure screen; nothing was read')
        lost += max(0, len(kept_text) - TEXT_MAX_LINES)
        response = {'status': 'ok', 'untrusted_page_text': True, 'notice': lk.NOTICE, 'window': {'title': device, 'device': device, 'platform': platform_of(els)},
                    'look_id': None, 'record_kind': 'none', 'records': [], 'text': kept_text[:TEXT_MAX_LINES], 'dialogs': a['dialogs'][:DIALOG_MAX], 'controls': kept_controls[:CONTROL_MAX]}
        if a['disabled']:
            response['disabled_controls'] = a['disabled'][:CONTROL_MAX]
        if a['inputs']:
            response['inputs'] = a['inputs'][:INPUT_MAX]
        if a['toggles']:
            response['toggles'] = a['toggles'][:INPUT_MAX]
        if terms:
            response['focus'] = {'terms': terms[:8], 'matched': len(kept_text) + len(kept_controls), 'filtered_out': len(shown) - len(kept_text) + len(a['controls']) - len(kept_controls)}
        response['counts'] = {'records': 0, 'controls': a['counts']['controls'], 'page_controls': len(a['controls']), 'non_page_controls': max(0, a['counts']['controls'] - len(a['controls'])), 'elements': a['counts']['elements']}
        response['sources'] = {'device': True, 'mobile_mcp': PACKAGE}
        def closing_notes(cut, lines):
            out = list(notes)
            if cut:
                out.append('%d items did not fit max_bytes=%d and are not shown; pass focus=<words> to narrow the look or raise max_bytes' % (cut, max_bytes))
            if lines:
                out.append('lines were cut or omitted: at most %d lines of %d characters are shown (pass line_chars to see more)' % (TEXT_MAX_LINES, line_chars))
            return out
        def measured():  # the COMPLETE response with the worst-case closing notes, timings and counters: max_bytes bounds THIS
            return len(json.dumps({**response, 'look_id': 'lk_0000000000', 'truncated': {'records': 0, 'lines': 999, 'bytes': 999}, 'notes': closing_notes(999, 999), 'ms_by_stage': {'observe': 99999, 'total': 999999}}))
        bytes_cut = 0
        while measured() > max_bytes and (response['text'] or response['controls'] or response.get('inputs') or response.get('toggles') or response['dialogs']):
            for key in ('text', 'controls', 'toggles', 'inputs', 'dialogs'):
                if response.get(key):
                    response[key] = response[key][:-1]
                    bytes_cut += 1
                    break
        notes = closing_notes(bytes_cut, lost)
        response['look_id'] = lk.look_id_of([a['text']], device, [], a['control_state'])
        response['truncated'] = {'records': 0, 'lines': lost, 'bytes': bytes_cut}
        response['notes'] = notes
        f.looks[(device, 'device', response['look_id'])] = {'device': device, 'created': f.clock(), 'n': 0}
        while len(f.looks) > 8:
            f.looks.pop(next(iter(f.looks)))
        total = round((f.clock() - t0) * 1000)
        response['ms_by_stage'] = {'observe': total, 'total': total}
        f.event('look', route='device', records=0, look_id=response['look_id'], ms=total)
        return response
    except MobileGap as gap:
        return {'status': 'refused' if gap.reason in REFUSED else 'failed', 'reason': gap.reason, 'message': str(gap), **({} if gap.reason in REFUSED else {'retryable': True}),
                'hint': 'Nothing was done to the device. Fix the cause in the message, then call `look` again.'}
    except Gap as gap:
        reason = f._do_reason(str(gap))
        return {'status': 'refused', 'reason': reason, 'message': lk.safe_message(reason, str(gap))}


# -- do ----------------------------------------------------------------------------------------------------------------------------------

DEVICE_STEP_KEYS = frozenset({'do', 'goal', 'control', 'control_match', 'text', 'expect', 'allow_destructive', 'url'})
DEVICE_KINDS = ('press', 'type', 'verify', 'goto')
DEVICE_HINTS = {
    'mobile_backend_unavailable': 'The device backend (mobile-mcp) could not run; nothing was done. Tell the user what the message says to install or fix; do not retry.',
    'device_not_found': 'No such device; nothing was done. Call `look` with device="list", then `do` with an id from it.',
    'mobile_device_agent_missing': 'The device needs mobile-mcp\'s on-device agent before its screen can be read; nothing was done. Tell the user; do not retry.',
    'mobile_observation_failed': 'The device screen could not be read, nothing was tapped by this step. Check the device is unlocked and reachable, then call `do` again.',
    'mobile_action_failed': 'The device action was not confirmed and may have reached the device (see delivery). Call `look` to read the screen before acting again.',
    'mobile_backend_timeout': 'The device backend did not answer in time (see delivery). Call `look` to read the screen before acting again.',
    'screen_unchanged_after_action': 'Step %(n)d\'s action was sent but the screen did not change and its expect was not seen: the tap may have been dropped (a locked or sleeping device, a covered control). Do not repeat it blindly: call `look` to read the screen, unlock the device if needed, then call `do` with the remaining steps.',
    'focus_not_on_field': 'After the tap the keyboard focus is on another field, so nothing was typed by step %(n)d. Call `look`, then `do` with the exact label of the field you mean.',
    'control_not_found': 'No control on the device screen matches step %(n)d (found.controls lists the buttons); nothing was tapped by this step. Call `look`, then `do` with the exact label from it.',
    'control_ambiguous': 'Several elements on the device screen carry step %(n)d\'s label; nothing was guessed or tapped. Use a longer exact label (see `look`), or control_match=prefix only if you mean it.',
    'control_not_pressable': 'The element of step %(n)d is present but disabled or has no size right now; nothing was tapped by this step. Call `look`, then `do` with the steps from step %(n)d on.',
    'toggle_state_unseen': 'Step %(n)d presses a switch or checkbox, which flips its CURRENT state, and this plan carries no look_id of a look that saw that state; nothing was tapped by this step. Call `look`, then `do` with its look_id and an expect naming the resulting state.',
}


def unsupported(steps):
    """Steps the device path does not run, refused before anything is read or tapped."""
    if not isinstance(steps, list):
        return
    for n, raw in enumerate(steps, 1):
        if not isinstance(raw, dict):
            continue
        kind = raw.get('do')
        if raw.get('where') is not None:
            raise Gap('where_not_supported_on_device: step %d where filters records, and a device screen has none (mobile-mcp lists it flat); press by the exact label of the control (see the controls in `look`(device=...))' % n)
        if kind in ('confirm', 'open_tab', 'close_tab', 'read_pages') or (kind == 'press' and raw.get('menu') is not None):
            raise Gap('not_supported_on_device: step %d (%s) is for a Mac window; on a device use press, type, verify and goto' % (n, kind if raw.get('menu') is None else 'press menu'))
        extra = sorted(k for k, v in raw.items() if v is not None and k not in DEVICE_STEP_KEYS)
        if extra:
            raise Gap('bad_request: step %d (%s) does not take %s on a device' % (n, kind, ', '.join(extra)))


def names_match(e, wanted, prefix, use_id=False):
    want = lk.norm(wanted)
    pool = e['names'] + ([e['id_tail']] if use_id and e['id_tail'] else [])
    exact = any(lk.norm(n) == want for n in pool)
    return exact, (not exact and prefix and any(lk.norm(n).startswith(want + ' ') for n in pool))


def collapse(matches):
    """Nested nodes of ONE control (a nav item frame and the label inside it) are one match: keep the outermost; anything else stays."""
    toggles = [m for m in matches if m['toggle']]
    if toggles:  # a row that carries its own switch: the switch is what flips, so a container around it is not a second candidate
        matches = toggles + [m for m in matches if not m['toggle'] and not any(inside(t['bounds'], m['bounds']) for t in toggles)]
    keep = []
    for m in matches:
        nested = any(o is not m and inside(m['bounds'], o['bounds']) and (area(o) > area(m) or (area(o) == area(m) and o['i'] < m['i'])) for o in matches)
        if not nested:
            keep.append(m)
    return keep


def resolve(els, wanted, prefix, tiers, use_id=False):
    """(element, None) for exactly one live match, else (None, {reason, ...}). Tiers are tried in order; a tier with any match decides."""
    for tier in tiers:
        pool = [e for e in els if tier(e)]
        exact = [e for e in pool if names_match(e, wanted, prefix, use_id)[0]]
        found = exact or [e for e in pool if names_match(e, wanted, prefix, use_id)[1]]
        found = collapse(found)
        if not found:
            continue
        ok = [e for e in found if live(e)]
        if len(ok) == 1:
            return ok[0], None
        return None, {'reason': 'control_ambiguous' if len(ok) > 1 else 'control_not_pressable', 'count': len(ok) or len(found)}
    return None, {'reason': 'control_not_found'}


def expect_check(after, before, expect, typed=None, target=None):
    """The device twin of Facade._expect_check: case-insensitive exact, else contains, each required in exactly ONE text-bearing NON-control element (static
    text, status text, field content other than the typed target). Absence is unknown, never failed. Presence that proves nothing is `unproven`: the text
    was there before the action, it is the text just typed, or it is a control's label."""
    needle = lk.norm(expect)
    skip = (target['kind'], target['id'], tuple(target['names'])) if target else None
    def strings(e):
        return [s for s in e['names'] + [e['value'], e['text']] if s]
    def bearing(els):
        return [e for e in els if e['role'] != 'control' and (e['kind'], e['id'], tuple(e['names'])) != skip]
    def hits(els, exact):
        seen = set()
        for e in bearing(els):
            for s in strings(e):
                if (lk.norm(s) == needle) if exact else (needle in lk.norm(s)):
                    seen.add((e['bounds'], lk.norm(s)))
                    break
        return len(seen)
    if typed is not None and (needle in lk.norm(typed) or lk.norm(typed) in needle):
        return {'status': 'unknown', 'route': 'device_expect', 'reason': 'expect_echoes_typed_text', 'unproven': True}
    if any(e['role'] == 'control' and any(lk.norm(n) == needle for n in e['names']) for e in after):
        return {'status': 'unknown', 'route': 'device_expect', 'reason': 'expect_is_a_control_label', 'unproven': True}
    if before is not None and hits(before, False) > 0:
        return {'status': 'unknown', 'route': 'device_expect', 'reason': 'expect_present_before_action', 'unproven': True}
    exact, loose = hits(after, True), hits(after, False)
    if exact == 1 or (exact == 0 and loose == 1):
        return {'status': 'satisfied', 'route': 'device_expect_' + ('exact' if exact else 'contains')}
    return {'status': 'unknown', 'route': 'device_expect', 'reason': 'expect_ambiguous' if max(exact, loose) > 1 else 'absence_not_proven'}


def abort_hit(els, needle):
    needle = lk.norm(needle)
    return any(e['role'] != 'control' and any(needle in lk.norm(s) for s in e['names'] + [e['value']]) for e in els)


class Run:
    """One device plan: the bridge, the clock, and the bounded fresh-observation and verification helpers every step shares."""
    def __init__(self, f, device, budget_s, t0):
        self.f, self.device, self.budget_s, self.t0 = f, device, budget_s, t0
        self.mob = bridge(f)
        self.last = None

    def elements(self):
        self.last = self.mob.elements(self.device)
        return self.last

    def over(self):
        return self.f.clock() - self.t0 > 3 * self.budget_s

    def verify(self, expect, before, delays, typed=None, target=None):
        """Observe a FRESH list until expect is proven, it cannot be (unproven), or the bounded delays run out. Returns (check, last list)."""
        check, after = {'status': 'unknown', 'route': 'device_expect', 'reason': 'absence_not_proven'}, None
        for n, delay in enumerate((0.0,) + tuple(delays)):
            if n and (self.over()):
                break
            if delay:
                self.f.sleep(delay)
            after = self.elements()
            check = expect_check(after, before, expect, typed, target)
            if check['status'] == 'satisfied' or check.get('unproven'):
                break
        return check, after

    def settle(self, step, before, delays, typed=None, target=None, extra=None):
        """The action was delivered. No expect: delivered_unverified (the last step only). With expect: done only when a fresh screen proves it."""
        result = {'delivery': 'delivered', **(extra or {})}
        expect = step.get('expect')
        if not expect:
            return {**result, 'status': 'delivered_unverified'}
        try:
            check, after = self.verify(expect, before, delays, typed, target)
        except MobileGap as gap:
            return {**result, 'status': 'failed', 'reason': gap.reason, 'message': str(gap)}
        result['verification'] = {k: check.get(k) for k in ('status', 'route', 'reason') if check.get(k)}
        if check['status'] == 'satisfied':
            return {**result, 'status': 'done'}
        if after is not None and before is not None and signature(after) == signature(before) and not check.get('unproven'):
            return {**result, 'status': 'stopped', 'reason': 'screen_unchanged_after_action', 'delivery': 'uncertain'}
        return {**result, 'status': 'stopped', 'reason': 'delivery_unverified'}


def not_found_payload(els, roles):
    return {'found': {'controls': list(dict.fromkeys(label_of(e)[:30] for e in els if e['role'] in roles and label_of(e) and live(e)))[:FOUND_MAX]}}


def destructive(step, element, literal):
    """The destructive floor, on the LITERAL label (validated before the plan runs) and again on the RESOLVED element's every name."""
    import plan as planmod
    for name in list(element['names']) + [literal]:
        bad = planmod.destructive_verbs(name)
        if bad and not planmod.allowed(step.get('allow_destructive'), name):
            return {'status': 'refused', 'reason': 'destructive_control', 'delivery': 'none',
                    'message': 'destructive_control: the control %r resolved on the device is destructive (%s); goal text never authorizes it. Only the step itself can: add allow_destructive=%r (its exact label) if the user asked for it' % (name[:40], ', '.join(bad), name[:40])}
    return None


def step_press(x, step):
    before = x.elements()
    target, problem = resolve(before, step['control'], step.get('control_match') == 'prefix', (lambda e: e['role'] == 'control', lambda e: e['role'] == 'text'))
    if problem:
        return {'status': 'refused' if problem['reason'] != 'control_not_pressable' else 'stopped', 'delivery': 'none', **not_found_payload(before, ('control',)),
                'reason': problem['reason'], **({'control_count': problem['count']} if problem['reason'] == 'control_ambiguous' else {}),
                'message': '%s: %s' % (problem['reason'], 'no element on the device screen carries that exact label' if problem['reason'] == 'control_not_found' else 'nothing was tapped')}
    refusal = destructive(step, target, step['control'])
    if refusal:
        return refusal
    if target['toggle'] and step.get('_look_id') is None:
        return {'status': 'stopped', 'reason': 'toggle_state_unseen', 'delivery': 'none'}
    selected = {'description': ('%s: %s' % (target['kind'], label_of(target)))[:120]}
    try:
        x.mob.tap(x.device, target)
    except MobileGap as gap:
        return {'status': 'failed', 'reason': gap.reason, 'delivery': gap.delivery, 'message': str(gap), 'selected': selected}
    return x.settle(step, before, TAP_DELAYS, extra={'selected': selected})


def field_in(els, target):
    """The typed-into field in a fresh list: same kind and identifier, the nearest to where it was."""
    tx, ty, tw, th = target['bounds']
    pool = [e for e in els if e['role'] == 'input' and e['kind'] == target['kind'] and e['id'] == target['id']]
    return min(pool, key=lambda e: abs(e['bounds'][0] - tx) + abs(e['bounds'][1] - ty), default=None)


def step_type(x, step):
    before = x.elements()
    target, problem = resolve(before, step['control'], step.get('control_match') == 'prefix', (lambda e: e['role'] == 'input',), use_id=True)
    if problem:
        return {'status': 'refused' if problem['reason'] != 'control_not_pressable' else 'stopped', 'delivery': 'none', 'reason': problem['reason'],
                'found': {'controls': list(dict.fromkeys((e['label'] or e['name'] or e['id_tail'])[:30] for e in before if e['role'] == 'input' and live(e)))[:FOUND_MAX]},
                **({'control_count': problem['count']} if problem['reason'] == 'control_ambiguous' else {}),
                'message': '%s: %s' % (problem['reason'], 'no text field on the device screen carries that exact label' if problem['reason'] == 'control_not_found' else 'nothing was typed')}
    refusal = destructive(step, target, step['control'])
    if refusal:
        return refusal
    selected = {'description': ('%s: %s' % (target['kind'], label_of(target)))[:120]}
    try:
        x.mob.tap(x.device, target)  # focus the field: a fresh list must show the focus on it before any key is typed
        focus = x.elements()
    except MobileGap as gap:
        return {'status': 'failed', 'reason': gap.reason, 'delivery': gap.delivery if gap.reason != 'mobile_observation_failed' else 'uncertain', 'message': str(gap), 'selected': selected}
    mine = field_in(focus, target)
    others = [e for e in focus if e['focused'] and e is not mine]
    if (mine is None or not mine['focused']) and others:
        return {'status': 'stopped', 'reason': 'focus_not_on_field', 'delivery': 'delivered', 'selected': selected}
    try:
        x.mob.type_keys(x.device, step['text'])
    except MobileGap as gap:
        return {'status': 'failed', 'reason': gap.reason, 'delivery': 'uncertain' if gap.delivery == 'none' else gap.delivery, 'message': str(gap), 'selected': selected}
    return x.settle(step, before, TAP_DELAYS, typed=step['text'], target=target, extra={'selected': selected})


def step_goto(x, step):
    before = x.elements()
    try:
        x.mob.open_url(x.device, step['url'])
    except MobileGap as gap:
        return {'status': 'failed', 'reason': gap.reason, 'delivery': gap.delivery, 'message': str(gap)}
    return x.settle(step, before, LOAD_DELAYS)


def step_verify(x, step):
    check, after = x.verify(step['expect'], None, ())
    result = {'delivery': 'none', 'verification': {k: check.get(k) for k in ('status', 'route', 'reason') if check.get(k)}}
    if check['status'] == 'satisfied':
        return {**result, 'status': 'observed'}
    return {**result, 'status': 'stopped', 'reason': 'not_verified'}


STEPS = {'press': step_press, 'type': step_type, 'goto': step_goto, 'verify': step_verify}


def summary_of(els, device):
    a = analyze(els)
    return {'title': device, 'text': [lk.cut(t)[0] for t in a['text'][:6]], 'controls': [c[:30] for c in a['controls'][:12]]}


def run_plan(f, goal, device, steps, look_id, abort_if, budget_s, expect, single):
    import plan as planmod
    def refuse(gap):
        reason = f._do_reason(str(gap))
        f.event('do_plan', status='refused', reason=reason, steps=0)
        return {'status': 'refused', 'reason': reason, 'message': lk.safe_message(reason, str(gap)), 'steps': [], 'delivery': 'none', 'follow_up_needed': True,
                'hint': DEVICE_HINTS.get(reason) or 'Correct the plan as the message says and call `do` again; nothing was done.'}
    try:
        unsupported(steps)
        plan_steps = planmod.validate(f, goal, None, -1, -1, steps, look_id, abort_if, budget_s, expect, single)
        if look_id is not None and not any(key[0] == device and key[2] == look_id for key in f.looks):
            raise Gap('look_window_mismatch: no `look` of THIS device returned that look_id; call `look`(device=...) and use its look_id')
    except Gap as gap:
        return refuse(gap)
    x = Run(f, device, budget_s, f.clock())
    entries, delivery, failed = [], 'none', None
    for n, step in enumerate(plan_steps, 1):
        remaining = 3 * budget_s - (f.clock() - x.t0)
        if remaining <= 0:
            failed = {'n': n, 'reason': 'budget_exceeded', 'status': 'stopped'}
            entries.append({'n': n, 'do': step['do'], 'status': 'stopped', 'reason': 'budget_exceeded', 'ms': 0})
            break
        began = f.clock()
        step['_look_id'] = look_id
        try:
            result = STEPS[step['do']](x, step)
        except MobileGap as gap:
            result = {'status': 'refused' if gap.reason in REFUSED else 'failed', 'reason': gap.reason, 'message': str(gap), 'delivery': gap.delivery}
        status = result['status']
        entry = {'n': n, 'do': step['do'], 'status': status, 'ms': round((f.clock() - began) * 1000)}
        for key in ('reason', 'selected', 'verification'):
            if result.get(key):
                entry[key] = result[key]
        if result.get('delivery') not in (None, 'none'):
            delivery = 'delivered' if result['delivery'] == 'delivered' or delivery == 'delivered' else 'uncertain'
        ok = status in ('done', 'observed') or (status == 'delivered_unverified' and n == len(plan_steps))
        if not ok:
            if result.get('message'):
                entry['message'] = lk.safe_message(result.get('reason'), result['message'])
            for key in ('found', 'control_count'):
                if key in result:
                    entry[key] = result[key]
            failed = {'n': n, 'reason': result.get('reason') or status, 'status': status}
        entries.append(entry)
        if ok and abort_if and x.last is not None and abort_hit(x.last, abort_if):
            failed = {'n': n, 'reason': 'abort_if_matched', 'status': 'aborted'}
            break
        if not ok:
            break
    ran_actions = any(e['do'] != 'verify' and e['status'] in ('done', 'delivered_unverified') for e in entries)
    if failed is None:
        status = 'delivered_unverified' if entries[-1]['status'] == 'delivered_unverified' else ('done' if ran_actions else 'observed')
    elif failed['status'] == 'aborted':
        status = 'aborted'
    elif failed['status'] == 'refused' and delivery == 'none':
        status = 'refused'
    elif failed['status'] == 'failed':
        status = 'failed'
    else:
        status = 'stopped'
    response = {'status': status, **({'failed_step': failed['n'], 'reason': failed['reason']} if failed else {}), 'steps': entries, 'delivery': delivery,
                'follow_up_needed': status not in ('done', 'observed')}
    if x.last is not None:
        response['summary'] = summary_of(x.last, device)
    if failed:
        text = DEVICE_HINTS.get(failed['reason'])
        response['hint'] = (text % {'n': failed['n']}) if text else planmod.hint_for(failed['reason'], failed['n'], delivery == 'delivered')
        if failed['reason'] == 'abort_if_matched':
            response['hint'] = 'abort_if text appeared after step %d, so the plan stopped; steps up to it ran. Report it to the user or call `look` to see the screen.' % failed['n']
    elif status == 'delivered_unverified':
        response['hint'] = 'The last action was delivered but no expect was given, so nothing was checked. Do not act again. To check, call `do` with steps=[{do:"verify", expect:<screen text that should be visible now>}].'
    if status == 'failed':
        response['retryable'] = delivery == 'none'
    f.event('do_plan', status=status, steps=len(entries), delivery=delivery, reason=(failed or {}).get('reason'))
    return planmod._fit(response)


def do(f, goal, device, title, pid, window_id, records, operation, text, expect, accept_unknown, budget_s, confirm, control, treat_as_match, near, steps, look_id, abort_if):
    """`do` on a device. A single step (goal + control + expect) is a one-step plan; the answer is the plan's answer."""
    def refuse(message):
        return {'status': 'refused', 'reason': f._do_reason(message), 'message': message, 'steps': [], 'delivery': 'none', 'follow_up_needed': True, 'hint': 'Correct the call as the message says; nothing was done.'}
    try:
        check_device(device)
        if device == LIST_TOKEN:
            raise Gap('bad_request: device="list" is for `look`; pass a device id from it')
        if title is not None or pid is not None or window_id is not None:
            raise Gap('bad_request: give device, or title or pid+window_id, not both')
    except Gap as gap:
        return refuse(str(gap))
    if steps is not None:
        return run_plan(f, goal, device, steps, look_id, abort_if, budget_s, expect, {})
    try:
        used = [k for k, v in (('records', records), ('confirm', confirm), ('accept_unknown', accept_unknown), ('treat_as_match', treat_as_match), ('near', near)) if v is not None]
        if used:
            raise Gap('not_supported_on_device: %s belong to a Mac window; on a device pass control or steps' % ', '.join(used))
        if operation == 'verify':
            one = {'do': 'verify', 'expect': expect}
        elif operation == 'type_text':
            one = {'do': 'type', 'control': control, 'text': text, 'expect': expect}
        else:
            one = {'do': 'press', 'control': control, 'expect': expect}
        if operation != 'verify' and (not isinstance(control, str) or not control.strip()):
            raise Gap('bad_request: a device call needs control (the exact label) or steps')
    except Gap as gap:
        return refuse(str(gap))
    return run_plan(f, goal, device, [{k: v for k, v in one.items() if v is not None}], look_id, abort_if, budget_s, None, {})
