"""Devices (CE-FACADE-008): Android and iOS through mobile-mcp, behind the same look/do contract as a Mac window.

A device is addressed by `device` (exactly the id `look(device="list")` shows: an emulator's AVD name, a phone's adb serial, or an iOS simulator UDID) instead of title or pid+window_id. The facade starts
mobile-mcp itself, as a child MCP client over stdio (StdioBackend), the first time a look or do targets a device: there is no setup step, and
when Node.js is missing the answer is a typed refusal (mobile_backend_unavailable) naming what to install, never a crash.

The contract is unchanged, only the observation and the delivery differ:
  - LOOK  reads mobile_list_elements_on_screen (json) and maps it to the look shape (text, controls, inputs, toggles, dialogs, look_id).
  - DO    resolves a press/type control on a FRESH element list read immediately before acting (exact label, else refuse: control_not_found,
          control_ambiguous, control_not_pressable, destructive_control), taps by the fresh element's ref (else the centre of its fresh bounds),
          and verifies every step on another fresh list against `expect`. The tap's own "Clicked on" never counts: upstream Cua found taps
          silently dropped on a locked phone, so a tap that changed nothing is reported screen_unchanged_after_action, never done.
mobile-mcp lists every node of the screen flat, without hierarchy and without a clickable flag, so the records of a device look are DERIVED from element
geometry (derive_records): elements whose vertical extents overlap form one row, and a row is a record only when it holds at least one control. `where.lines`
then works exactly as on a Mac window (a look_id of a look of this device, the page must still read the same, one match binds) and is refused
where_not_supported_on_device only when the look found no records. A control is an element whose type is a button, switch, cell and the like, and any other
element that carries the label can be pressed by it when no button does (nested nodes of one control collapse to the outermost).

iOS: a simulator or device answers "Agent is not installed" until mobile-mcp's on-device agent is installed. mobile-mcp has no tool for that; the agent is
installed by its CLI (`npx -y mobilecli@1.0.16 agent install --device <id>`), which the facade runs ONCE, bounded, when a read is refused
mobile_device_agent_missing, and then retries the read ONCE. A failed install is the same typed refusal naming the exact command; nothing loops.
Everything the device displays is untrusted page text, exactly as in a Mac look.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from datetime import timedelta

import look as lk
from core import Gap

PACKAGE = '@mobilenext/mobile-mcp@1.0.6'
DEFAULT_COMMAND = ['npx', '-y', PACKAGE]
AGENT_PACKAGE = 'mobilecli@1.0.16'      # the CLI mobile-mcp 1.0.6 is built on (its @mobilenext/mobilecli-* binary is 1.0.16); it owns `agent install`
AGENT_INSTALL_TIMEOUT_S = 300.0        # the install builds nothing on a simulator but downloads the agent; bounded, never looped
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
COLD_START_S = 15.0                    # an empty device list this soon after the backend started is not trusted (#69: simulators appear a few seconds later)
COLD_RETRY_S = 2.0                     # the wait before asking again; at most COLD_RETRIES times, never a loop
COLD_RETRIES = 2
FOUND_MAX = 12
APPS_PREFIX = 'Found these apps on device: '
APP_ENTRY = re.compile(r'(.+?) \(([A-Za-z0-9_][A-Za-z0-9_.\-]*)\)(?:, |$)', re.S)   # "Name (package), Name (package)": a name may hold commas or parentheses
SWIPE_FRACTION = 2                      # a swipe inside a named container travels half of the container's extent from its centre, so it stays inside
REFUSED = frozenset({'mobile_backend_unavailable', 'device_not_found', 'mobile_device_agent_missing', 'bad_request', 'not_supported_on_device',
                     'where_not_supported_on_device', 'look_required', 'unknown_look_id', 'look_window_mismatch', 'destructive_control', 'expect_required',
                     'app_ambiguous', 'app_not_found', 'within_ambiguous', 'within_not_found'})


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


def agent_install_command(device):
    return ['npx', '-y', AGENT_PACKAGE, 'agent', 'install', '--device', device]


def install_agent(device, run=subprocess.run, which=shutil.which, platform=None):
    """Install mobile-mcp's on-device (iOS) agent with its CLI, once and bounded. Returns None on success; raises MobileGap('mobile_device_agent_missing')
    naming the exact command when Xcode or Node.js is missing or the command fails or times out. Raw output (paths, stack traces) is never carried."""
    command = agent_install_command(device)
    shown = ' '.join(command)
    def refuse(why):
        return MobileGap('mobile_device_agent_missing', '%s. Run `%s` yourself, then call again. Nothing was done' % (why, shown))
    if (platform or sys.platform) != 'darwin' or which('xcrun') is None:
        raise refuse('the iOS agent can only be installed on a Mac with Xcode (xcrun was not found; install Xcode from the App Store and run `xcode-select --install`)')
    if which('npx') is None:
        raise refuse('Node.js (npx) was not found on PATH; install Node.js 18 or newer (https://nodejs.org)')
    try:
        done = run(command, capture_output=True, text=True, timeout=AGENT_INSTALL_TIMEOUT_S, stdin=subprocess.DEVNULL, env={**os.environ, 'MOBILEMCP_DISABLE_TELEMETRY': '1'})
    except subprocess.TimeoutExpired:
        raise refuse('installing the iOS agent did not finish within %ds' % AGENT_INSTALL_TIMEOUT_S)
    except OSError:
        raise refuse('the install command could not be started')
    if done.returncode != 0:
        raise refuse('installing the iOS agent failed (exit %s)' % done.returncode)
    return None


def classify(text, action=False):
    """Map mobile-mcp's answer text to a typed reason WITHOUT echoing it (it carries local paths): (reason, message, delivery)."""
    low = (text or '').lower()
    if 'agent is not installed' in low:
        return ('mobile_device_agent_missing', 'the device agent (mobile-mcp\'s on-device helper) is not installed on this device; an iOS simulator or device needs it before its screen can be read. Install it with: %s. Nothing was done' % ' '.join(agent_install_command('<device id>')), 'none')
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
        self.started_at = None
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
        self.started_at = time.monotonic()
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
            raise MobileGap('mobile_observation_failed' if tool.startswith(('mobile_list', 'mobile_get', 'mobile_take_screenshot')) else 'mobile_action_failed',
                            'mobile-mcp answered an error to %s (%s)' % (tool, type(error).__name__), 'none' if tool.startswith(('mobile_list', 'mobile_get', 'mobile_take_screenshot')) else 'uncertain')
        if tool == 'mobile_take_screenshot':
            images = [c for c in (result.content or []) if getattr(c, 'type', '') == 'image']
            if getattr(result, 'isError', False) or len(images) != 1:
                raise MobileGap('screen_capture_unavailable', 'mobile-mcp did not return one screenshot')
            return {'data': images[0].data, 'mimeType': images[0].mimeType}, False
        text = '\n'.join(getattr(c, 'text', '') for c in (result.content or []) if getattr(c, 'type', '') == 'text')
        return text, bool(getattr(result, 'isError', False))

    def call(self, tool, args, mutating=False, timeout=CALL_TIMEOUT_S):
        """(text, is_error), or (image dict, is_error) for screenshots. A dead process is restarted ONCE for reads only."""
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
IOS_CONTROL = frozenset({'Button', 'Link', 'Switch', 'Toggle', 'Tab', 'Cell', 'MenuItem', 'Key', 'Icon'})  # Icon: a home-screen app icon (real tree, type "Icon")
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


def parse_apps(text):
    """mobile_list_apps' answer ("Found these apps on device: Name (package), Name (package)") as [{name, package}], in its order, one per package."""
    out, seen = [], set()
    for name, package in APP_ENTRY.findall((text or '')[len(APPS_PREFIX):]):
        if package not in seen:
            seen.add(package)
            out.append({'name': _text(name), 'package': package})
    return out


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
    """The displayed text of an element, else None (#69). Only displayed-text kinds (PLAIN_TEXT) are lines: a container, group, image or icon NAME is never a line
    (iOS names an empty 'Other' view 'label-view'); a control keeps its name as its control label."""
    return (e['names'][0] if e['names'] else None) if e['kind'] in PLAIN_TEXT else None


def dialog_roots(els):
    return [e for e in els if (e['id_tail'] in DIALOG_IDS and e['id'].startswith('android:id/')) or (not e['android'] and e['kind'] in DIALOG_KINDS)]


BAND_SLACK = 2          # pixels two vertical extents may overlap by and still be two rows (antialiasing, 1px borders)
TALL_LEAF = 0.5         # a named leaf taller than this share of the screen is a scroll area or backdrop, not a row member


def derive_records(els):
    """Records from element geometry, as the perception layout fallback groups text regions. The list is flat, so: (1) candidates are the elements that carry
    a name (a label, text or content description) and have a size; (2) LEAVES are the candidates that hold no other candidate; (3) leaves are banded
    top to bottom, one band being the leaves whose vertical extents overlap (a row of a list, a card, a toolbar); (4) a control that wraps several leaves
    (a list cell, a nav item) joins the ONE band its leaves are in; a cell that holds no other cell merges the bands it holds (stacked title and subtitle are one row), and a
    control that spans several rows (a list container) is ignored; (5) a band is a record only
    when it holds at least one control. Lines are the texts of the band in reading order; controls are what can be pressed in it. Returns records in page order,
    each {'root', 'lines', 'controls' (elements, left to right), 'top'} (`root` numbers the band; lk.select numbers the records r1.. itself)."""
    def carries(e):
        return bool(label_of(e)) if e['role'] in ('control', 'input') else bool(tagged_line(e))
    cands = [e for e in els if area(e) > 0 and carries(e)]
    def wraps(c):
        return any(d is not c and inside(d['bounds'], c['bounds']) and (area(d) < area(c) or (area(d) == area(c) and d['i'] > c['i'])) for d in cands)
    container_ids = {c['i'] for c in cands if wraps(c)}
    page = max((e['bounds'][1] + e['bounds'][3] for e in els), default=0)
    leaves = [e for e in cands if e['i'] not in container_ids]
    if len(leaves) > 1:
        leaves = [e for e in leaves if e['bounds'][3] <= page * TALL_LEAF]
    bands = []
    for e in sorted(leaves, key=lambda e: (e['bounds'][1], e['bounds'][0], e['i'])):
        top, bottom = e['bounds'][1], e['bounds'][1] + e['bounds'][3]
        if bands and top < bands[-1]['bottom'] - BAND_SLACK:
            bands[-1]['leaves'].append(e)
            bands[-1]['bottom'] = max(bands[-1]['bottom'], bottom)
        else:
            bands.append({'top': top, 'bottom': bottom, 'leaves': [e], 'wrappers': []})
    wrappers = [c for c in cands if c['i'] in container_ids and c['role'] == 'control' and live(c)]
    def holding(w):
        return [b for b in bands if any(inside(l['bounds'], w['bounds']) for l in b['leaves'])]
    for w in wrappers:
        # a cell that holds no other cell IS the row: the bands it holds (a title above a subtitle) are one record; a wrapper that holds other cells, or one as
        # tall as a scroll area, is a list container and merges nothing
        if w['bounds'][3] > page * TALL_LEAF or any(o is not w and inside(o['bounds'], w['bounds']) for o in wrappers):
            continue
        hit = holding(w)
        for other in hit[1:]:
            hit[0]['leaves'] += other['leaves']
            hit[0]['top'], hit[0]['bottom'] = min(hit[0]['top'], other['top']), max(hit[0]['bottom'], other['bottom'])
            bands.remove(other)
    for w in wrappers:
        hit = holding(w)
        if len(hit) == 1:
            hit[0]['wrappers'].append(w)
    records = []
    for n, band in enumerate(bands, 1):
        members = band['leaves'] + band['wrappers']
        controls = sorted((e for e in members if e['role'] in ('control', 'input') and label_of(e)), key=lambda e: (e['bounds'][0], e['bounds'][1], e['i']))
        if not controls:
            continue
        wrapped = {lk.norm(label_of(w)) for w in band['wrappers']}
        texts = sorted((e for e in band['leaves'] if e['role'] == 'text'), key=lambda e: (e['bounds'][1], e['bounds'][0], e['i']))
        plain = {lk.norm(e['names'][0]) for e in texts if e['kind'] in PLAIN_TEXT and e['names']}
        lines = []
        for e in texts:
            line = tagged_line(e)
            if not line or lk.norm(e['names'][0]) in wrapped or (e['kind'] not in PLAIN_TEXT and lk.norm(e['names'][0]) in plain) or line in lines:
                continue
            lines.append(line)
        records.append({'root': n, 'lines': lines, 'controls': controls, 'top': band['top']})
    return records


def analyze(els):
    """Structure of one element list, no model: dialogs, page text, controls, inputs, toggles and the records derived from geometry (derive_records)."""
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
            'records': derive_records(rest), 'headings': [],
            'counts': {'elements': len(els), 'controls': sum(1 for e in els if e['role'] == 'control')}}


def signature(els):
    """The screen as it reads: a change in any element's name, content, state or place changes it."""
    return json.dumps([[e['type'], e['names'], e['value'], e['id'], e['enabled'], e['checked'], e['selected'], e['focused'], e['bounds']] for e in els], ensure_ascii=False, sort_keys=True)


NOTE_RECORDS = ('records are derived from element geometry (mobile-mcp lists the screen flat): elements whose vertical extents overlap form one row, and a row '
                'with at least one control is a record. Press by the exact label of a control, or use where.lines with this look_id to pick the row')
NOTE_FLAT = ('this screen yields no records (no row holds a control): mobile-mcp lists it flat, without hierarchy or a clickable flag. Press by the exact label of a '
             'control (a button, switch or cell first, else any element that carries the label); where.lines is not available')


def look_id_for(a, rows, device):
    """What the look showed AND did not: the device, the FULL lines of each displayed record, the page text and every control's state."""
    return lk.look_id_of([r['rec']['lines'] for r in rows] + [a['text']], device, [], a['control_state'])


def record_row(r):
    item = {'r': r['r'], 'controls': list(dict.fromkeys(label_of(e)[:30] for e in r['rec']['controls'] if e['enabled'])), 'lines': r['lines']}
    disabled = list(dict.fromkeys(label_of(e)[:30] for e in r['rec']['controls'] if not e['enabled']))
    if disabled:
        item['disabled'] = disabled
    return item


def check_device(device):
    if not isinstance(device, str) or not DEVICE_ID.fullmatch(device):
        raise Gap('bad_request: device is the id `look`(device="list") shows (an emulator\'s AVD name, a phone\'s adb serial, or an iOS simulator UDID)')


# -- discovery ---------------------------------------------------------------------------------------------------------------------------

class Mobile:
    """The facade's view of mobile-mcp: typed reads and actions over any backend with call(tool, args, mutating) -> (text, is_error) and close()."""
    def __init__(self, backend=None, installer=install_agent, sleep=time.sleep):
        self.backend, self.installer, self.installed, self.sleep = backend, installer, [], sleep
        self.cold_empty = False   # the last devices() answered empty while the backend had only just started

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

    def _just_started(self):
        at = getattr(self.backend, 'started_at', None)
        return at is not None and time.monotonic() - at < COLD_START_S

    def _list_devices(self):
        text, error = self._backend().call('mobile_list_available_devices', {})
        try:
            rows = json.loads(text).get('devices') if not error else None
        except (ValueError, AttributeError):
            rows = None
        if not isinstance(rows, list):
            raise MobileGap('mobile_observation_failed', 'mobile-mcp could not list devices')
        return [{k: _text(d.get(k))[:60] for k in ('id', 'name', 'platform', 'type', 'version', 'state') if d.get(k) is not None} for d in rows if isinstance(d, dict)][:DEVICE_LIST_MAX]

    def devices(self):
        """The devices mobile-mcp lists. An EMPTY answer within COLD_START_S of the backend's start is not trusted (#69): wait COLD_RETRY_S and ask again, at most COLD_RETRIES times."""
        out = self._list_devices()
        self.cold_empty = False
        for _ in range(COLD_RETRIES):
            if out or not self._just_started():
                break
            self.sleep(COLD_RETRY_S)
            out = self._list_devices()
        self.cold_empty = not out and self._just_started()
        return out

    def _read(self, device):
        text, error = self._backend().call('mobile_list_elements_on_screen', {'device': device, 'format': 'json'})
        return parse_elements(text)

    def screenshot(self, device):
        """Capture only: no element enumeration or automatic device-agent install."""
        payload, error = self._backend().call('mobile_take_screenshot', {'device': device, 'maxSize': 2048})
        if error or not isinstance(payload, dict) or set(payload) != {'data', 'mimeType'}:
            raise MobileGap('screen_capture_unavailable', 'mobile-mcp did not return one screenshot')
        return payload

    def elements(self, device):
        """A fresh element list. A refusal mobile_device_agent_missing installs the on-device agent ONCE and retries the read ONCE (never a loop): a failed
        install, or an agent still missing after it, is the typed refusal naming the exact command."""
        try:
            return self._read(device)
        except MobileGap as gap:
            if gap.reason != 'mobile_device_agent_missing':
                raise
        self.installer(device)
        self.installed.append(device)
        try:
            return self._read(device)
        except MobileGap as gap:
            if gap.reason == 'mobile_device_agent_missing':
                raise MobileGap('mobile_device_agent_missing', 'the iOS agent was installed but the device still answers that it is missing. Run `%s` yourself (add --force to reinstall), then call again. Nothing was done' % ' '.join(agent_install_command(device)))
            raise

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

    def apps(self, device):
        """The installed apps mobile-mcp lists: [{name, package}] (an Android package or an iOS bundle id), in its order, one per package."""
        text, error = self._backend().call('mobile_list_apps', {'device': device})
        if error or not isinstance(text, str) or not text.startswith(APPS_PREFIX):
            reason, message, delivery = classify(text)
            raise MobileGap(reason, message, delivery)
        return parse_apps(text)

    def launch_app(self, device, package):
        self._act('mobile_launch_app', {'device': device, 'packageName': package}, 'Launched app')

    def swipe(self, device, direction, point=None, distance=None):
        """mobile-mcp swipes from the centre of the screen unless it is given a start point; with one it swipes `distance` pixels from there."""
        args = {'device': device, 'direction': direction}
        if point is not None:
            args.update({'x': point[0], 'y': point[1], 'distance': distance})
        self._act('mobile_swipe_on_screen', args, 'Swiped')

    def type_keys(self, device, text):
        self._act('mobile_type_keys', {'device': device, 'text': text, 'submit': False}, 'Typed text')

    def open_url(self, device, url):
        self._act('mobile_open_url', {'device': device, 'url': url}, 'Opened URL')


def bridge(f):
    if getattr(f, '_mobile', None) is None:
        f._mobile = Mobile()
    return f._mobile


DISCOVERY_HINTS = {  # #64: an empty or unavailable list says what would appear, why it matters and the one call to get it
    'listed': 'Pass device=<an id from devices> to `look` and `do` to work on a phone or emulator, or title=<a window title> for a Mac window.',
    'empty': 'No phone or emulator is attached; each would appear as {id, platform, name}. Start one (emulator -avd <name>, or xcrun simctl boot <udid>), then call `look` with device="list" again; or pass title=<a window title>.',
    'empty_cold': 'The device backend had only just started and was asked again after a short wait; a simulator that is still booting may appear on the next call.',
    'backend': 'The device backend did not start (devices_unavailable.message): only the user can install it, so tell the user and do not retry. Mac windows still work: pass title=<a window title>.',
}


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
    out['hint'] = DISCOVERY_HINTS['listed']
    if 'devices_unavailable' in out:
        out['hint'] = DISCOVERY_HINTS['backend']
    elif not out['devices']:
        out['hint'] = DISCOVERY_HINTS['empty']
        if getattr(bridge(f), 'cold_empty', False):
            out['hint'] = DISCOVERY_HINTS['empty_cold'] + ' ' + out['hint']
    return out


# -- look --------------------------------------------------------------------------------------------------------------------------------

def look(f, device, fields=None, max_records=40, max_bytes=6000, focus=None, max_lines=6, line_chars=60):
    """Read-only look at a device screen, or device="list" for discovery. Same response shape as a window look; records are derived from geometry."""
    t0 = f.clock()
    try:
        if device == LIST_TOKEN:
            return discovery(f)
        lk.check_look_args(None, max_records, max_bytes, focus, max_lines, line_chars)
        check_device(device)
        if fields is not None:
            raise Gap('not_supported_on_device: fields (the extraction model) read the values of records, and a device look shows the strings only')
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
        opts = (max_lines, line_chars)
        rows, _, matched = lk.select(a, terms, cap=max_records, opts=opts)
        response_rows = [record_row(r) for r in rows]
        lost += sum(r['lost'] for r in rows)
        notes = [NOTE_RECORDS if a['records'] else NOTE_FLAT]
        if matched > len(rows):
            notes.append('%d more records matched but only max_records=%d are shown; pass focus=<words from the record you want> or raise max_records' % (matched - len(rows), max_records))
        if not els:
            notes.append('the device listed no elements: it may be locked, asleep or showing a secure screen; nothing was read')
        lost += max(0, len(kept_text) - TEXT_MAX_LINES)
        response = {'status': 'ok', 'untrusted_page_text': True, 'notice': lk.NOTICE, 'window': {'title': device, 'device': device, 'platform': platform_of(els)},
                    'look_id': None, 'record_kind': 'rows' if a['records'] else 'none', 'records': response_rows, 'text': kept_text[:TEXT_MAX_LINES], 'dialogs': a['dialogs'][:DIALOG_MAX], 'controls': kept_controls[:CONTROL_MAX]}
        if a['disabled']:
            response['disabled_controls'] = a['disabled'][:CONTROL_MAX]
        if a['inputs']:
            response['inputs'] = a['inputs'][:INPUT_MAX]
        if a['toggles']:
            response['toggles'] = a['toggles'][:INPUT_MAX]
        if terms:
            response['focus'] = {'terms': terms[:8], 'matched': len(kept_text) + len(kept_controls) + matched, 'filtered_out': len(shown) - len(kept_text) + len(a['controls']) - len(kept_controls) + len(a['records']) - matched}
        response['counts'] = {'records': len(a['records']), 'controls': a['counts']['controls'], 'page_controls': len(a['controls']), 'non_page_controls': max(0, a['counts']['controls'] - len(a['controls'])), 'elements': a['counts']['elements']}
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
        while measured() > max_bytes and (response['records'] or response['text'] or response['controls'] or response.get('inputs') or response.get('toggles') or response['dialogs']):
            for key in ('records', 'text', 'controls', 'toggles', 'inputs', 'dialogs'):
                if response.get(key):
                    response[key] = response[key][:-1]
                    bytes_cut += 1
                    break
        notes = closing_notes(bytes_cut, lost)
        shown_rows = rows[:len(response['records'])]
        response['look_id'] = look_id_for(a, shown_rows, device)
        response['truncated'] = {'records': matched - len(rows), 'lines': lost, 'bytes': bytes_cut}
        response['notes'] = notes
        f.looks[(device, 'device', response['look_id'])] = {'device': device, 'created': f.clock(), 'n': len(shown_rows), 'terms': terms, 'opts': opts, 'records': len(a['records'])}
        while len(f.looks) > 8:
            f.looks.pop(next(iter(f.looks)))
        total = round((f.clock() - t0) * 1000)
        response['ms_by_stage'] = {'observe': total, 'total': total}
        f.event('look', route='device', records=len(response['records']), look_id=response['look_id'], ms=total)
        return response
    except MobileGap as gap:
        return {'status': 'refused' if gap.reason in REFUSED else 'failed', 'reason': gap.reason, 'message': str(gap), **({} if gap.reason in REFUSED else {'retryable': True}),
                'hint': 'Nothing was done to the device. Fix the cause in the message, then call `look` again.'}
    except Gap as gap:
        reason = f._do_reason(str(gap))
        return {'status': 'refused', 'reason': reason, 'message': lk.safe_message(reason, str(gap))}


# -- do ----------------------------------------------------------------------------------------------------------------------------------

DEVICE_STEP_KEYS = frozenset({'do', 'goal', 'where', 'control', 'control_match', 'text', 'expect', 'allow_destructive', 'accept_hidden_text', 'url', 'app', 'direction', 'within'})
DEVICE_KINDS = ('press', 'type', 'verify', 'goto', 'launch', 'swipe')
DEVICE_HINTS = {
    'mobile_backend_unavailable': 'The device backend (mobile-mcp) could not run; nothing was done. Tell the user what the setup block or the message says to install or fix; do not retry until they have.',
    'device_not_found': 'No such device; nothing was done. Call `look` with device="list", then `do` with an id from it.',
    'mobile_device_agent_missing': "The device needs mobile-mcp's on-device agent to be read; nothing was done. Tell the user (it is installed on the device, not by this server); do not retry until they have.",
    'mobile_observation_failed': 'The device screen could not be read, nothing was tapped by this step. Check the device is unlocked and reachable, then call `do` again.',
    'mobile_action_failed': 'The device action was not confirmed and may have reached the device (see delivery). Call `look` to read the screen before acting again.',
    'mobile_backend_timeout': 'The device backend did not answer in time (see delivery). Call `look` to read the screen before acting again.',
    'screen_unchanged_after_action': "Step %(n)d's action was sent but the screen did not change and expect was not seen (locked device, covered control, end of the list?). Do not repeat it blindly: call look, unlock if needed, then do.",
    'app_ambiguous': 'Several apps match step %(n)d (found.apps lists name and package); nothing was launched. Call do again with one exact package from found.apps as app, with the steps from step %(n)d on.',
    'app_not_found': 'No installed app matches step %(n)d (found.apps lists near matches, else installed apps); nothing was launched. Call do with an exact name or package from found.apps as app, from step %(n)d on.',
    'within_not_found': 'No element on the device screen is named by step %(n)d within (found.containers lists the large named areas); nothing was swiped. Call look, then do with an exact name, or no within, from step %(n)d on.',
    'within_ambiguous': 'Several elements carry step %(n)d within; nothing was swiped. Call look, then do with a more specific exact name, or no within to swipe the centre of the screen, from step %(n)d on.',
    'focus_not_on_field': 'After the tap the keyboard focus is on another field, so nothing was typed by step %(n)d. Call `look`, then `do` with the exact label of the field you mean.',
    'control_not_found': 'No control on the device screen matches step %(n)d (found.controls lists the buttons); nothing was tapped by this step. Call `look`, then `do` with the exact label from it.',
    'control_ambiguous': 'Several elements on the device screen carry step %(n)d\'s label; nothing was guessed or tapped. Use a longer exact label (see `look`), or control_match=prefix only if you mean it.',
    'control_not_pressable': 'The element of step %(n)d is present but disabled or has no size right now; nothing was tapped by this step. Call `look`, then `do` with the steps from step %(n)d on.',
    'toggle_state_unseen': 'Step %(n)d flips a switch or checkbox and the plan has no look_id that saw its state; nothing was tapped. Call look, then do with its look_id and an expect naming the new state.',
}


def unsupported(steps):
    """Steps the device path does not run, refused before anything is read or tapped."""
    if not isinstance(steps, list):
        return
    for n, raw in enumerate(steps, 1):
        if not isinstance(raw, dict):
            continue
        kind = raw.get('do')
        if isinstance(raw.get('where'), dict) and raw['where'].get('fields') is not None:
            raise Gap('where_not_supported_on_device: step %d where.fields reads record values with the extraction model, which a device screen does not have; use where.lines over the strings `look`(device=...) showed, or press by the exact label of the control' % n)
        if kind != 'press' and raw.get('where') is not None:
            raise Gap('bad_request: step %d (%s) does not take where on a device; where picks the record a press acts in' % (n, kind))
        if kind in ('confirm', 'open_tab', 'close_tab', 'read_pages', 'upload') or (kind == 'press' and raw.get('menu') is not None):
            raise Gap('not_supported_on_device: step %d (%s) is for a Mac window; on a device use press, type, verify, goto, launch and swipe' % (n, kind if raw.get('menu') is None else 'press menu'))
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


def record_stage(x, step, before):
    """`where.lines` on a device, the twin of plan.lines_stage over records derived from the FRESH list. Returns (element, None) for the one control to press,
    else (None, result) where result is the stopped step. 1. The screen must still read the way the look showed it (its look_id is recomputed from the fresh
    list with the look's own focus, cap and line cut). 2. Uniqueness is decided over ALL records of the fresh list. 3. Negative conditions are refused for
    records with cut lines; selecting one needs accept_hidden_text. 4. Within the record the control is named by step.control, else it must be the only one."""
    import plan as planmod
    look = next((v for k, v in x.f.looks.items() if k[0] == x.device and k[2] == step['_look_id']), None)
    a = analyze(before)
    stop = lambda reason, **more: (None, {'status': 'stopped', 'reason': reason, 'delivery': 'none', **more})
    if look is None:
        return stop('unknown_look_id')
    opts = look['opts']
    shown, _, _ = lk.select(a, look['terms'], cap=look['n'], opts=opts)
    if look_id_for(a, shown, x.device) != step['_look_id']:
        return stop('page_changed_since_look', found={'records': len(a['records']), 'record_kind': 'rows' if a['records'] else 'none'})
    every, _, _ = lk.select(a, [], cap=None, opts=opts)
    displayed = {r['rec']['root'] for r in shown}
    conds = step['where']['lines']
    lines_of = lambda r: [lk.norm(t) for t in r['lines']]
    positive = [c for c in conds if c['line'] in ('eq', 'contains')]
    negative = [c for c in conds if c['line'] not in ('eq', 'contains')]
    candidates = [r for r in every if all(planmod.cond_ok(lines_of(r), c) for c in positive)]
    cut = [r['r'] for r in candidates if r['lost']]
    if negative and cut:
        return stop('negative_condition_over_cut_lines', evidence={'records_with_cut_or_omitted_lines': cut[:8], 'count': len(cut)})
    matched = [r for r in candidates if all(planmod.cond_ok(lines_of(r), c) for c in negative)]
    shown_matches = [r for r in matched if r['rec']['root'] in displayed]
    if len(matched) != 1 or len(shown_matches) != 1:
        return stop('no_matching_record' if len(matched) < 2 else 'where_matches_several',
                    evidence={'matches': [{'lines': r['lines']} for r in shown_matches[:5]], 'match_count': len(shown_matches) if len(matched) < 2 else len(matched),
                              'displayed_matches': len(shown_matches), **({'outside_look': len(matched) - len(shown_matches)} if len(matched) != len(shown_matches) else {})})
    only = matched[0]
    if only['lost'] and step.get('accept_hidden_text') is not True:
        return stop('selected_record_has_hidden_text', evidence={'record': only['r'], 'hidden_lines': only['lost']})
    pool = only['rec']['controls']
    if step.get('control') is not None:
        prefix = step.get('control_match') == 'prefix'
        exact = [e for e in pool if names_match(e, step['control'], prefix)[0]]
        pool = exact or [e for e in pool if names_match(e, step['control'], prefix)[1]]
        pool = collapse(pool)
        if not pool:
            return stop('control_not_found', found={'controls': [label_of(e)[:30] for e in only['rec']['controls']][:FOUND_MAX]})
    pool = collapse(pool)
    ok = [e for e in pool if live(e)]
    if len(ok) != 1:
        if not ok and pool:
            return stop('control_not_pressable')
        return stop('control_ambiguous', control_count=len(ok) or len(pool), found={'controls': [label_of(e)[:30] for e in pool][:FOUND_MAX]})
    return ok[0], None


def step_press(x, step):
    before = x.elements()
    if step.get('where') is not None:
        target, stopped = record_stage(x, step, before)
        if stopped:
            return stopped
        problem = None
    else:
        target, problem = resolve(before, step['control'], step.get('control_match') == 'prefix', (lambda e: e['role'] == 'control', lambda e: e['role'] == 'text'))
    if problem:
        return {'status': 'refused' if problem['reason'] != 'control_not_pressable' else 'stopped', 'delivery': 'none', **not_found_payload(before, ('control',)),
                'reason': problem['reason'], **({'control_count': problem['count']} if problem['reason'] == 'control_ambiguous' else {}),
                'message': '%s: %s' % (problem['reason'], 'no element on the device screen carries that exact label' if problem['reason'] == 'control_not_found' else 'nothing was tapped')}
    refusal = destructive(step, target, step.get('control') or '')
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


def resolve_app(apps, wanted):
    """(app, None) for exactly one installed app, else (None, {reason, candidates}). Tiers, the first with any match decides: the exact package or bundle id, the
    exact name, a name that starts with the words given. Several in a tier is app_ambiguous: the first is never taken."""
    want = lk.norm(wanted)
    tiers = (lambda a: lk.norm(a['package']) == want, lambda a: lk.norm(a['name']) == want, lambda a: lk.norm(a['name']).startswith(want + ' '))
    shown = lambda found: ['%s (%s)' % (a['name'][:30], a['package'][:60]) for a in found][:FOUND_MAX]
    for tier in tiers:
        found = [a for a in apps if tier(a)]
        if len(found) == 1:
            return found[0], None
        if found:
            return None, {'reason': 'app_ambiguous', 'candidates': shown(found), 'count': len(found)}
    near = [a for a in apps if want in lk.norm(a['name']) or want in lk.norm(a['package'])]
    return None, {'reason': 'app_not_found', 'candidates': shown(near or apps), 'count': len(near)}


def step_launch(x, step):
    before = x.elements()
    apps = x.mob.apps(x.device)
    app, problem = resolve_app(apps, step['app'])
    if problem:
        return {'status': 'refused', 'delivery': 'none', 'reason': problem['reason'], 'found': {'apps': problem['candidates']},
                **({'control_count': problem['count']} if problem['reason'] == 'app_ambiguous' else {}),
                'message': '%s: %s' % (problem['reason'], 'several installed apps match; nothing was launched' if problem['reason'] == 'app_ambiguous' else 'no installed app matches; nothing was launched')}
    selected = {'description': ('app: %s (%s)' % (app['name'], app['package']))[:120]}
    try:
        x.mob.launch_app(x.device, app['package'])
    except MobileGap as gap:
        return {'status': 'failed', 'reason': gap.reason, 'delivery': gap.delivery, 'message': str(gap), 'selected': selected}
    return x.settle(step, before, LOAD_DELAYS, extra={'selected': selected})


def step_swipe(x, step):
    before = x.elements()
    point = distance = None
    selected = {'description': 'swipe %s%s' % (step['direction'], ' in ' + step['within'][:60] if step.get('within') else ' from the centre of the screen')}
    if step.get('within'):
        target, problem = resolve(before, step['within'], False, (lambda e: True,))
        if problem:
            named = sorted((e for e in before if e['role'] != 'control' and label_of(e) and live(e)), key=lambda e: -area(e))
            reason = 'within_ambiguous' if problem['reason'] == 'control_ambiguous' else 'within_not_found'
            return {'status': 'refused', 'delivery': 'none', 'reason': reason, 'found': {'containers': list(dict.fromkeys(label_of(e)[:30] for e in named))[:FOUND_MAX]},
                    'message': '%s: %s' % (reason, 'nothing was swiped')}
        bx, by, bw, bh = target['bounds']
        point = (bx + bw // 2, by + bh // 2)
        distance = max(1, (bw if step['direction'] in ('left', 'right') else bh) // SWIPE_FRACTION)
    try:
        x.mob.swipe(x.device, step['direction'], point, distance)
    except MobileGap as gap:
        return {'status': 'failed', 'reason': gap.reason, 'delivery': gap.delivery, 'message': str(gap), 'selected': selected}
    if step.get('expect'):
        result = x.settle(step, before, TAP_DELAYS, extra={'selected': selected})
        if result.get('reason') == 'delivery_unverified' and x.last is not None and signature(x.last) == signature(before):  # expect was already on screen, and nothing moved
            return {**result, 'reason': 'screen_unchanged_after_action', 'delivery': 'uncertain'}
        return result
    after = None
    for n, delay in enumerate((0.0,) + TAP_DELAYS):  # a scroll settles; observe fresh lists, bounded, until one differs from the list the swipe started on
        if n and x.over():
            break
        if delay:
            x.f.sleep(delay)
        after = x.elements()
        if signature(after) != signature(before):
            return {'status': 'done', 'delivery': 'delivered', 'selected': selected, 'verification': {'status': 'satisfied', 'route': 'device_list_changed'}}
    return {'status': 'stopped', 'reason': 'screen_unchanged_after_action', 'delivery': 'uncertain', 'selected': selected}


def step_verify(x, step):
    check, after = x.verify(step['expect'], None, ())
    result = {'delivery': 'none', 'verification': {k: check.get(k) for k in ('status', 'route', 'reason') if check.get(k)}}
    if check['status'] == 'satisfied':
        return {**result, 'status': 'observed'}
    return {**result, 'status': 'stopped', 'reason': 'not_verified'}


STEPS = {'press': step_press, 'type': step_type, 'goto': step_goto, 'verify': step_verify, 'launch': step_launch, 'swipe': step_swipe}


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
        if any(isinstance(s, dict) and s.get('where') is not None for s in steps):
            seen = next((v for k, v in f.looks.items() if k[0] == device and k[2] == look_id), None)
            if not seen or not seen.get('records'):
                raise Gap('where_not_supported_on_device: the look of this screen found no records (no row holds a control; mobile-mcp lists it flat), so there is nothing for where.lines to pick; press by the exact label of a control (see the controls in `look`(device=...))')
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
            for key in ('found', 'control_count', 'evidence'):
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
