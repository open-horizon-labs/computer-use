"""Stateful local CUA facade. Driver observations own records and executable arguments."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid

DISPATCH = Path(__file__).resolve().parents[1] / 'inference/cua-decider/capability-dispatch'
sys.path.insert(0, str(DISPATCH))
from dispatch import Engine, execute_bound, request_digest, predicate as dispatch_predicate, typed as dispatch_typed
from page_candidates import NuExtractPage, filter_records
from providers import generic_from_config, RemoteSpans
from rollout import Strangler
from terminal_observation import VisualTerminal
from ax_aliases import table_aliases


OBSERVE_RETRY_DELAYS = (0.5, 1.0)   # seconds before the 2nd and 3rd observation of a page that is not ready
MEMORY_READOUT = re.compile(r'(Memory usage - )[\d.,]+\s*[KMGT]?B',re.I)
THIN_PAGE_NODES = 10   # a web page with this few nodes or fewer is still loading or a holding page ("checking your browser"), whatever the site


class Gap(ValueError):
    """An observation/authority gap; must not authorize execution."""


class StaleUI(Gap):
    """act() refused: the bound observation changed before delivery. Nothing was clicked.
    Typed, so cua_do recovers from it without matching on message text."""


class DriverCallFailed(Gap):
    """A Cua Driver call failed at the process boundary (exit, timeout, unusable
    output). Typed, so callers never match on message text. Carries no stderr."""



def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


MIN_DRIVER_VERSION = (0, 29, 1)  # off_space_or_ax_unresolved fixed upstream; trycua/cua#4068
PERCEPTION_CAPTURE_TTL_S = 60  # cua-perception capture registry expiry (upstream perception-extension.md)
REGION_CANDIDATE_LIMIT = 18  # the generic chooser's capacity (sketch S4.5); never truncate


MUTATING_TOOLS = frozenset({'click', 'double_click', 'right_click', 'type_text', 'drag', 'scroll', 'hotkey', 'press_key',
                              'invoke_menu', 'set_window_frame'})


class Driver:
    def __init__(self, executable=None):
        self.executable = executable or os.environ.get('CUA_DRIVER', str(Path.home()/'.local/bin/cua-driver'))
        self._version = None
        self._perception = None

    def version(self):
        # Cache: one subprocess per process lifetime, not per tool call.
        if self._version is None:
            try:
                result = subprocess.run([self.executable, '--help'], capture_output=True, text=True, timeout=10)
            except subprocess.TimeoutExpired:
                raise DriverCallFailed('driver_call_failed: version probe timed out')
            except OSError:
                raise DriverCallFailed('driver_call_failed: cua-driver could not be started (check CUA_DRIVER)')
            match = re.search(r'cua-driver\s+(\d+)\.(\d+)\.(\d+)', result.stdout + result.stderr)
            self._version = tuple(int(part) for part in match.groups()) if match else False
        return self._version or None

    def perception_status(self):
        # Cache like version(): one probe per process lifetime. The facade
        # never installs/updates the extension itself; it only reads status.
        if self._perception is None:
            try:
                result = subprocess.run([self.executable, 'extension', 'status', 'cua-perception', '--self-test', '--json'],
                                         capture_output=True, text=True, timeout=15)
                self._perception = json.loads(result.stdout) if result.stdout.strip() else {}
            except (subprocess.TimeoutExpired, ValueError, OSError):
                self._perception = {}
        return self._perception

    def call(self, tool, args, timeout=20):
        # After a mutating call the action may already have been delivered.
        note = ('; the action may have been delivered, so verify before retrying' if tool in MUTATING_TOOLS else '')
        try:
            result = subprocess.run([self.executable, 'call', tool, '--json', json.dumps(args)],
                                    capture_output=True, text=True, timeout=timeout, check=True)
            value = json.loads(result.stdout)
        except subprocess.CalledProcessError as error:
            raise DriverCallFailed('driver_call_failed: %s exited %s%s' % (tool, error.returncode, note))
        except subprocess.TimeoutExpired:
            raise DriverCallFailed('driver_call_failed: %s timed out after %ss%s' % (tool, timeout, note))
        except (OSError, ValueError):
            raise DriverCallFailed('driver_call_failed: %s returned no usable result%s' % (tool, note))
        if not isinstance(value, dict):
            raise DriverCallFailed('driver_call_failed: %s returned a non-object result%s' % (tool, note))
        if value.get('refusal') or value.get('status') == 'refused':
            raise Gap('Driver refused: ' + str(value.get('refusal', {}).get('code', 'unknown')))
        return value

    def observe(self, pid, window_id, session, timeout=20):
        # resolve() avoids Driver rejecting /tmp's symlink as a nondirectory.
        try:
            directory_context = tempfile.TemporaryDirectory(prefix='cua-facade-')
        except OSError:
            raise DriverCallFailed('driver_call_failed: no temporary directory for the screenshot')
        with directory_context as directory:
            path = Path(directory).resolve()/'window.png'
            result = self.call('get_window_state', {'pid': pid, 'window_id': window_id,
                'session': session, 'max_elements': 15000, 'max_dimension': 1280,
                'screenshot_out_file': str(path)}, timeout=timeout)
            try:
                result['_image'] = path.read_bytes() if path.exists() else b''
            except OSError:
                raise DriverCallFailed('driver_call_failed: get_window_state screenshot was unreadable')
        return result


class Facade:
    def __init__(self, driver=None, generic_factory=generic_from_config, reader_factory=NuExtractPage,
                 spans_factory=RemoteSpans, visual_factory=VisualTerminal, clock=time.monotonic, sleep=time.sleep):
        self.driver = driver or Driver()
        self.sleep = sleep
        self.foreground_ok = False  # per call/step: allow_foreground; a background pixel click cannot reach a canvas (see act)
        self.factories = {'generic': generic_factory, 'reader': reader_factory,
                          'spans': spans_factory, 'visual': visual_factory}
        self.providers = {}
        self.clock = clock
        self.session = 'cua-facade-' + uuid.uuid4().hex[:10]
        self.started = False
        self.driver_version = None
        self.driver_version_state = 'unprobed'
        self.perception_version = None
        self.perception_state = 'unprobed'  # healthy | not_installed | unhealthy | unprobed
        self.snapshots, self.latest, self.selections, self.readings = {}, {}, {}, {}
        self.looks = {}  # (pid, window_id, look_id) -> the page a cua_look showed (plans may filter over displayed lines only against one of these)
        self.prefix_control = True  # plan steps set this False (exact label) unless control_match=prefix; the single-step form keeps the whole-word prefix
        self.events = []
        self.lock = threading.RLock()

    def event(self, operation, **data):
        # Content-free route audit: no screenshots, text, command payloads or secrets.
        row = {'operation': operation, **data}
        self.events.append(row)
        self.events = self.events[-200:]
        return row

    def provider(self, name):
        if name not in self.providers:
            start = self.clock()
            self.providers[name] = self.factories[name]()
            self.event('provider_start', provider=name, setup_ms=(self.clock()-start)*1000)
        return self.providers[name]

    def windows(self, title=None):
        if not self.started:
            version_probe = getattr(self.driver, 'version', None)
            if callable(version_probe):
                self.driver_version = version_probe()
                self.driver_version_state = 'unparsed' if self.driver_version is None else 'probed'
                # Unknown version (older driver with no --help version line) is not
                # blocked; a version we CAN parse and IS too old must refuse.
                if self.driver_version is not None and self.driver_version < MIN_DRIVER_VERSION:
                    raise Gap('cua-driver %s is unsupported (needs >= %s): off_space_or_ax_unresolved routes are refused on older builds; upgrade cua-driver (trycua/cua#4068)'
                              % ('.'.join(map(str, self.driver_version)), '.'.join(map(str, MIN_DRIVER_VERSION))))
            perception_probe = getattr(self.driver, 'perception_status', None)
            if callable(perception_probe):
                payload = perception_probe() or {}
                self.perception_version = payload.get('active_version')
                self.perception_state = 'healthy' if payload.get('installed') and payload.get('healthy') \
                    else ('not_installed' if not payload.get('installed') else 'unhealthy')
            else:
                self.perception_state = 'not_installed'
            self.driver.call('start_session', {'session': self.session})
            self.started = True
        result = self.driver.call('list_windows', {'session': self.session})
        return {'route': 'driver_inventory', 'windows': [
            {k:w[k] for k in ('app_name','pid','window_id','title','is_on_screen') if k in w}
            for w in result.get('windows', []) if w.get('title') and (title is None or w['title']==title)]}

    def observe(self, pid, window_id, timeout=None, wait_ready=False):
        """With wait_ready (a look at a page just opened, never the revalidation or recovery observations of an action): observe, waiting out a page that is not ready yet: a bounded, deterministic retry (OBSERVE_RETRY_DELAYS) when the Driver call
        gave no snapshot while the window is still listed, returned an empty/degraded tree, or the page is THIN (a web area with almost
        nothing in it: still loading, or a holding page such as "checking your browser", which clears itself). A structural rule, no site or
        phrase list. A failed Driver call is NOT retried here: _do's own bounded recovery owns it. Read-only, so a retry can never act twice. After the last try
        the result (or the original error) is returned unchanged; nothing here solves or bypasses a check."""
        delays = list(OBSERVE_RETRY_DELAYS) if wait_ready else []
        for attempt in range(len(delays) + 1):
            last = attempt == len(delays)
            try:
                result = self._observe_once(pid, window_id, timeout)
            except Gap as error:
                if last or not str(error).startswith('driver_snapshot_unavailable'):
                    raise
            else:
                reason = self._not_ready(result) or ('thin_page' if self._thin_page(result['snapshot']) else None)
                if last or reason is None:
                    if attempt:
                        self.event('observe_retry', attempts=attempt, ready=reason is None, reason=reason)
                    return result
            self.sleep(delays[attempt])

    @staticmethod
    def _not_ready(result):
        if not result.get('elements'):
            return 'empty_tree'
        if result['quality'].get('degraded_reason'):
            return 'degraded'
        return None

    def _thin_page(self, handle):
        state = self.snapshots[handle]
        web = self._top_web_areas(state)
        if not web:
            return False
        below, frontier = 0, {web[0]}
        while frontier:
            frontier = {i for i, n in state['nodes'].items() if n.get('parent_index') in frontier}
            below += len(frontier)
        return below <= THIN_PAGE_NODES

    def _observe_once(self, pid, window_id, timeout=None):
        if not self.started:
            self.windows()
        began = self.clock()
        raw = self.driver.observe(pid, window_id, self.session, *([timeout] if timeout is not None else []))
        if not raw.get('snapshot_id') or raw.get('pid', pid) != pid or raw.get('window_id', window_id) != window_id:
            # A vague message here just makes the agent guess three times. Say
            # whether the window is gone or the Driver degraded/refused instead.
            windows = self.driver.call('list_windows', {'session': self.session}).get('windows', [])
            if not any(w.get('pid') == pid and w.get('window_id') == window_id for w in windows):
                raise Gap('window_closed: the target window is no longer in the Driver window list; call cua_windows again')
            raise Gap('driver_snapshot_unavailable: ' + json.dumps(
                {'refusal': raw.get('refusal'), 'degraded_reason': raw.get('degraded_reason')}, sort_keys=True))
        nodes = {}
        for item in raw.get('elements', []):
            index = item.get('element_index')
            if not isinstance(index, int) or index in nodes:
                raise Gap('Invalid observed element indices')
            if item.get('element_token') != f"{raw['snapshot_id']}:{index}":
                raise Gap('Element token does not belong to snapshot')
            nodes[index] = copy.deepcopy(item)
        normalized = [{k:v for k,v in item.items() if k != 'element_token'} for item in nodes.values()]
        content = {'pid': pid, 'window_id': window_id, 'title': raw.get('window_title'),
                   'bounds': raw.get('window_bounds'), 'nodes': normalized,
                   'degraded': raw.get('degraded_reason')}
        handle = 'obs_' + uuid.uuid4().hex
        image = raw.pop('_image', b'')
        state = {'raw': raw, 'nodes': nodes, 'image': image, 'fingerprint': digest(content),
                 'image_digest': hashlib.sha256(image).hexdigest() if image else None,
                 'pid': pid, 'window_id': window_id, 'created': self.clock(), 'aliases':table_aliases(nodes)}
        self.snapshots[handle] = state
        self.latest[(pid, window_id)] = handle
        # Retain bounded memory. Old handles cannot become current again.
        while len(self.snapshots) > 8:
            self.snapshots.pop(next(iter(self.snapshots)))
        quality = {'ax_available': bool(nodes), 'coverage': 'observed_tree_only',
                   'terminal_text_coverage': 'unknown', 'screenshot_available': bool(image),
                   'degraded_reason': raw.get('degraded_reason'), 'progress': 'unknown',
                   'table_alias_count':len(state['aliases'])}
        self.event('observe', route='cua-driver', snapshot=handle, driver_ms=(self.clock()-began)*1000)
        return {'snapshot': handle, 'driver_snapshot_id': raw['snapshot_id'], 'title': raw.get('window_title'),
                'quality': quality, 'elements': [{'id': 'e'+str(i), 'parent_id': 'e'+str(a['parent_index']) if a.get('parent_index') in nodes else None,
                    'role': a.get('role'), 'name': a.get('label', ''), 'value': a.get('value'),
                    'enabled': a.get('enabled', True), 'actions': a.get('actions', []),
                    **({'alias_of':'e'+str(state['aliases'][i])} if i in state['aliases'] else {})} for i,a in nodes.items()]}

    @staticmethod
    def check_foreground(raw):
        """Refuse before delivery when the window is off-Space/AX-unresolved.

        The facade never activates, raises or moves windows to work around
        this; it only refuses so the caller (or the user) brings it forward,
        or upgrades cua-driver.
        """
        background = raw.get('background_input') or {}
        exact_window = background.get('exact_window') or {}
        status = exact_window.get('status')
        routes = background.get('routes') or []
        # cua-driver emits a list of {route,status,reason}; tolerate a keyed dict too.
        routes = list(routes.values()) if isinstance(routes, dict) else routes
        refused_reasons = {r.get('reason') for r in routes if isinstance(r, dict) and r.get('status') == 'refused'}
        if (status is not None and status != 'matched') or 'off_space_or_ax_unresolved' in refused_reasons:
            raise Gap('needs_foreground: window is on another Space or AX-unresolved (exact_window.status=%r); '
                      'the facade never moves, activates or raises windows; bring it forward yourself, or upgrade '
                      'cua-driver to >= %s' % (status, '.'.join(map(str, MIN_DRIVER_VERSION))))

    def state(self, handle):
        state = self.snapshots.get(handle)
        if not state or self.latest.get((state['pid'],state['window_id'])) != handle:
            raise Gap('Stale or unknown observation; observe again')
        if self.clock() - state['created'] > 120:
            raise Gap('Observation expired; observe again')
        return state

    @staticmethod
    def node(state, candidate):
        if not isinstance(candidate,str) or not candidate.startswith('e') or not candidate[1:].isdigit():
            raise Gap('Candidate must be an observed element ID')
        try:
            return state['nodes'][int(candidate[1:])]
        except KeyError:
            raise Gap('Candidate was not observed') from None

    def subtree(self, state, candidate):
        root = self.node(state, candidate)['element_index']
        # Same closure as repeatedly collecting children, from a per-observation child map (a 100-row page made this quadratic).
        kids = state.get('_kids')
        if kids is None:
            kids = {}
            for i,n in state['nodes'].items():kids.setdefault(n.get('parent_index'), []).append(i)
            state['_kids'] = kids
        descendants, stack = {root}, [root]
        while stack:
            for child in kids.get(stack.pop(), ()):
                if child not in descendants:descendants.add(child);stack.append(child)
        text = []
        for i,n in state['nodes'].items():
            if i in descendants:
                # A heading's `value` is its LEVEL ('1', '2'), never text: its label (and its text child) is.
                for key in (('label',) if n.get('role') == 'AXHeading' else ('label','value')):
                    value = n.get(key)
                    if isinstance(value,str) and value.strip() and value not in text:
                        text.append(value)
        # Preserve explicit table cell boundaries. Container aria labels (e.g.
        # 'Cedar record') are not cell values; don't mix them into the data.
        cells = [i for i,n in state['nodes'].items()
                 if n.get('parent_index') == root and n.get('role') == 'AXCell']
        if state['nodes'][root].get('role') == 'AXRow' and cells:
            text = [json.dumps({'cells': [self.subtree(state, 'e'+str(i))[0]
                                        for i in cells]}, ensure_ascii=False)]
        return '\n'.join(text), descendants

    def regions(self, snapshot, kinds=None, min_confidence=None, max_regions=None):
        """Parse this SAME capture's perception regions via the Driver's
        capture-bound contract (perception-extension.md 'Capture-bound parse
        and action'): pass the exact capture_id get_window_state returned for
        this observation. Never re-parses a different/expired capture for an
        old selection -- callers must reobserve instead.
        """
        state = self.state(snapshot)
        if self.perception_state != 'healthy':
            raise Gap('perception_not_available: cua-perception is %s; install it with '
                      '`python3 scripts/install_perception.py` (never auto-installed by the facade)' % self.perception_state)
        capture_id = state['raw'].get('capture_id')
        if not capture_id:
            raise Gap('capture_unavailable: this observation carries no Driver capture_id to parse')
        if self.clock() - state['created'] > PERCEPTION_CAPTURE_TTL_S:
            raise Gap('capture_expired: perception captures expire after %ds upstream; reobserve for a fresh capture'
                      % PERCEPTION_CAPTURE_TTL_S)
        if state.get('regions_capture_id') == capture_id and state.get('regions') is not None:
            return state['regions']
        if state.get('regions_failure', (None, None))[0] == capture_id:
            # A failed parse of this capture is not retried per candidate.
            raise Gap(state['regions_failure'][1])
        options = {}
        if kinds: options['kinds'] = list(kinds)
        if min_confidence is not None: options['min_confidence'] = min_confidence
        if max_regions is not None: options['max_regions'] = max_regions
        # Driver captures are scoped to the session that made them: without the
        # same session the Driver answers capture_not_found (verified live, 0.30.3).
        args = {'capture_id': capture_id, 'session': self.session, **({'options': options} if options else {})}
        try:
            result = self.driver.call('parse_visual_regions', args)
        except DriverCallFailed as gap:
            message = 'perception_parse_failed: %s (cached for this capture; reobserve to retry, and if it persists the Driver session may have been lost)' % gap
            state['regions_failure'] = (capture_id, message)
            raise Gap(message)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError) as error:
            # A Driver/extension failure is an unavailable capability, never a
            # crash of the caller. Fixed text only: stderr can carry paths and ids.
            message = 'perception_parse_failed: parse_visual_regions failed (%s; cached for this capture; reobserve to retry, and if it persists the Driver session may have been lost)' % type(error).__name__
            state['regions_failure'] = (capture_id, message)
            raise Gap(message)
        state['regions'] = result
        state['regions_capture_id'] = capture_id
        self.event('perception_parse', route='cua-perception', snapshot=snapshot,
                   region_count=len(result.get('regions', [])))
        return result

    @staticmethod
    def _png_size(data):
        if not data or len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n':
            return None
        width = int.from_bytes(data[16:20], 'big')
        height = int.from_bytes(data[20:24], 'big')
        return (width, height) if width and height else None

    def _pixel_scale(self, state):
        """(sx, sy) mapping AX frame points onto perception's screenshot-pixel
        space, or None when that is not provably a uniform ratio. AX frames are
        the Driver's window-local points; parsed regions are in screenshot
        pixels (cua.visual_regions_v1 action_coordinate_space.kind ==
        'screenshot_pixels'). A Retina/downscale factor can make these
        numerically different -- only compute the ratio from the ACTUAL
        screenshot's pixel size against the Driver's reported window bounds;
        never assume 1:1. Mismatched/missing data means DON'T mix: return None.
        """
        bounds = state['raw'].get('window_bounds') or {}
        width, height = bounds.get('w') or bounds.get('width'), bounds.get('h') or bounds.get('height')
        size = self._png_size(state['image'])
        if not width or not height or not size:
            return None
        sx, sy = size[0]/width, size[1]/height
        if sx <= 0 or sy <= 0 or abs(sx-sy) > 0.02*max(sx, sy):
            return None
        return (sx, sy)

    def record_context_perception(self, state, index):
        """Fallback record grouping from perception layout, used only when
        AX record_context/sibling_record found nothing (flat/ambiguous AX).
        Maps this control's AX frame into perception's pixel space (refusing if
        the coordinate spaces aren't provably comparable), then bands text
        regions vertically between this control and its nearest same-role/label
        neighbours. Description/corroboration context ONLY: OCR values must
        never feed cua_read/NuExtract (see docs/FACADE.md OCR evidence table --
        "60 min"->"600 min" etc.). Returns (text, 'perception_layout') or
        ('', None) when unavailable.
        """
        node = state['nodes'][index]
        frame = node.get('frame')
        if not frame or self.perception_state != 'healthy':
            return '', None
        # Only a control that repeats has an ambiguity layout can resolve. A
        # unique control ("Yes, cancel order") needs no record context and must
        # never cost a live parse (about 1.5 s) or a chance to fail.
        kind = (node.get('role'), node.get('label'))
        if sum(1 for n in state['nodes'].values() if (n.get('role'), n.get('label')) == kind) < 2:
            return '', None
        scale = self._pixel_scale(state)
        if not scale:
            return '', None
        snapshot = next((h for h, s in self.snapshots.items() if s is state), None)
        try:
            parsed = self.regions(snapshot) if snapshot else None
        except Gap:
            return '', None
        if not parsed:
            return '', None
        sx, sy = scale
        kind = (node.get('role'), node.get('label'))
        siblings = sorted((n for n in state['nodes'].values()
                            if (n.get('role'), n.get('label')) == kind and n.get('frame')),
                          key=lambda n: n['frame'].get('y', 0))
        if len(siblings) < 2:
            return '', None
        ys = [s['frame'].get('y', 0)*sy for s in siblings]
        my_y = frame.get('y', 0)*sy
        try:
            position = ys.index(my_y)
        except ValueError:
            return '', None
        # Assumes the common card layout observed in the booking evidence
        # (provider/duration/start text ABOVE its own "Book" button): band each
        # control's record from the end of the PREVIOUS same-kind control down
        # to this control's own top edge, never past it into the next record.
        band_top = ys[position-1] + siblings[position-1]['frame'].get('h', 0)*sy if position else 0
        band_bottom = my_y
        texts = []
        for region in parsed.get('regions', []):
            if region.get('kind') != 'text':
                continue
            by = region.get('bounds', {}).get('y', 0)
            if band_top <= by < band_bottom:
                text = region.get('text')
                if text and text not in texts:
                    texts.append(text)
        return ('\n'.join(texts), 'perception_layout') if texts else ('', None)

    def record_context(self, state, index):
        """Text of this control's record: the outermost ancestor still holding
        exactly one control of the same role/label, i.e. the child of the first
        ancestor that repeats it. The nearest unique ancestor can be a table cell
        holding only sibling controls; the first repeating ancestor spans every
        record. A control that never repeats needs no record context.
        """
        node = state['nodes'][index]
        ancestor = node.get('parent_index')
        chain = []
        while ancestor in state['nodes'] and ancestor not in chain:
            chain.append(ancestor)
            ancestor = state['nodes'][ancestor].get('parent_index')
        # Same role+label first (repeated "Book"); then role alone, for distinctly
        # labelled controls whose records still repeat ("Inspect first/second").
        for kind in (lambda n: (n.get('role'), n.get('label')), lambda n: n.get('role')):
            record = ''
            for anc in chain:
                text, members = self.subtree(state, 'e'+str(anc))
                if sum(1 for i in members if kind(state['nodes'][i]) == kind(node)) > 1:
                    if record:return record
                    break
                record = text
        inferred = self.sibling_record(state, index)
        return '\n'.join(inferred[0]) if inferred else ''

    def sibling_record(self, state, index, by_role=False):
        """Flat trees (Chrome often prunes each <li> wrapper): split the parent's
        children at each repeat of this control. Records must consistently sit
        on one side of their control -- text before the first repeat and none
        after the last, or the reverse -- otherwise the grouping is ambiguous
        and returns None rather than guessing. Returns (texts, member indices).
        """
        node = state['nodes'][index]
        parent = node.get('parent_index')
        kind = (node.get('role'), node.get('label'))
        children = sorted(i for i,n in state['nodes'].items() if n.get('parent_index') == parent)
        repeats = [i for i in children if (state['nodes'][i].get('role'), state['nodes'][i].get('label')) == kind]
        if by_role and len(repeats) < 2:
            # Per-record labels ("Book Dr A", "Book Dr B"): the peers are the same-role controls of the same parent.
            repeats = [i for i in children if state['nodes'][i].get('role') == node.get('role') and self._is_control(state['nodes'][i])]
        if len(repeats) < 2 or index not in repeats:
            return None
        before = [i for i in children if i < repeats[0]]
        after = [i for i in children if i > repeats[-1]]
        position = repeats.index(index)
        if before and not after:
            low = repeats[position-1] if position else -1
            members = [i for i in children if low < i < index]
        elif after and not before:
            high = repeats[position+1] if position+1 < len(repeats) else float('inf')
            members = [i for i in children if index < i < high]
        else:
            return None
        members = [i for i in members if not self._title_member(state, i)]  # the page's own title heading is page text, not the first record's
        texts = []
        for i in members:
            text, _ = self.subtree(state, 'e'+str(i))
            texts += [line for line in text.split('\n') if line and line not in texts]
        return (texts, set(members) | {index}) if texts else None

    @staticmethod
    def _title_member(state, i):
        """True for the page's title as text: a heading whose text equals or contains the window title, or a text node that equals it. (Only these, so a record line
        that merely mentions a word of the title is never dropped.)"""
        title = re.sub(r'\s+', ' ', str(state['raw'].get('window_title') or '')).strip().casefold()
        n = state['nodes'].get(i)
        if not title or not n:return False
        label = re.sub(r'\s+', ' ', str(n.get('label') or n.get('value') or '')).strip().casefold()
        if n.get('role') == 'AXHeading':return bool(label) and title in label
        return label == title

    READ_BUDGET = 2  # readings per (snapshot, record scope); S4.2 §7 bounds steps, S4.8 forbids re-read loops

    def read(self, snapshot, task, fields, record_ids, predicates=None, coverage_complete=False, flat_by_role=False, shape_guard=False):
        state = self.state(snapshot)
        fields = copy.deepcopy(fields)
        # S4.8: readings are the displayed strings. Supplied types are ignored
        # (recorded, never applied): the controlling LLM interprets "half-hour".
        types_ignored = {name: spec['type'] for name, spec in fields.items() if spec.get('type', 'text') not in ('text', 'string')}
        for spec in fields.values():
            spec['type'] = 'text'; spec.pop('currency', None)
        if not record_ids or len(set(record_ids)) != len(record_ids):
            raise Gap('Supply distinct observed record roots')
        scope = (snapshot, frozenset(record_ids))
        prior = [h for h, r in self.readings.items() if (r['snapshot'], frozenset(r['record_ids'])) == scope]
        if len(prior) >= self.READ_BUDGET:
            last = self.readings[prior[-1]]
            raise Gap('read_budget: these records were already read %d times for this observation; re-reading is a '
                      'defect, not recovery. Judge the extracted strings yourself and pass the eligible records as '
                      'candidate_ids/record_actions with reading %s: %s' % (len(prior), prior[-1],
                      json.dumps({r['record_id']: r['fields'] for r in last['extraction']['records']}, ensure_ascii=False)))
        records, memberships, record_basis = [], [], {}
        for candidate in record_ids:
            text, members = self.subtree(state,candidate)
            root = self.node(state,candidate)['element_index']
            if len(members) == 1:
                # A lone control in a flat tree: use its sibling-order record,
                # labelled so the weaker grouping stays visible downstream.
                inferred = self.sibling_record(state, root, flat_by_role)
                if inferred:
                    text, members = '\n'.join(inferred[0] + ([text] if text else [])), inferred[1]
                    record_basis[candidate] = 'sibling_order'
            if any(members & previous for previous in memberships):
                raise Gap('Overlapping record roots could mix fields across records')
            if not text:
                raise Gap('Record has no observed text')
            memberships.append(members)
            records.append({'id':candidate, 'text':text})
        start = self.clock()
        extraction = self.provider('reader').extract({'snapshot_id':state['raw']['snapshot_id'],
            'task':task, 'fields':{k:v['description'] for k,v in fields.items()}, 'records':records},state['raw']['snapshot_id'])
        filtered = filter_records(extraction,fields=fields,predicates=predicates or [],
            coverage_complete=coverage_complete,current_snapshot=state['raw']['snapshot_id'])
        if shape_guard:filtered = self._reclassify_shapes(fields, predicates or [], extraction, filtered)
        handle = 'read_' + uuid.uuid4().hex
        result = {'reading':handle, 'snapshot':snapshot, 'route':'nuextract3', 'extraction':extraction, 'filter':filtered,
                  **({'record_basis':record_basis} if record_basis else {}), **({'types_ignored':types_ignored} if types_ignored else {})}
        self.readings[handle] = copy.deepcopy({**result,'fields':fields,'predicates':predicates or [],'record_ids':list(record_ids)})
        while len(self.readings)>32:self.readings.pop(next(iter(self.readings)))
        self.event('read',route='nuextract3',snapshot=snapshot,records=len(records),endpoint_ms=(self.clock()-start)*1000)
        return result

    @staticmethod
    def _operation_compatible(node, operation):
        if operation == 'click':
            return 'AXPress' in node.get('actions', [])
        if operation == 'type_text':
            return node.get('role') in ('AXTextField', 'AXTextArea', 'AXComboBox', 'AXSearchField')
        return False

    OBSERVED_ID = re.compile(r'\be(\d+)\b')
    LEAK_PHRASE = re.compile(r'\bthe correct (?:one|answer) is\b|\bcorrect answer\s*[:=]|\bthe answer is\b', re.I)

    def reject_answer_leak(self, state, goal):
        """Refuse a goal that hands the chooser the answer instead of criteria."""
        mentioned = {int(m) for m in self.OBSERVED_ID.findall(goal or '')}
        if mentioned & set(state['nodes']):
            raise Gap('Goal names an observed element ID; describe distinguishing criteria instead, '
                      'not the answer — the chooser evaluates evidence, not a preselected candidate.')
        if self.LEAK_PHRASE.search(goal or ''):
            raise Gap('Goal states the answer (e.g. "the correct one is ..."); describe the '
                      'distinguishing criteria instead so the chooser evaluates evidence, not a preselected candidate.')

    TEXT_ONLY_FILLER = frozenset('the a an page window screen status message banner text shows show reads read says '
                                 'displays display contains contain is are now visible visibly appears with and'.split())

    @staticmethod
    def quoted_tokens(text):
        return [re.sub(r'\s+', ' ', token).strip() for token in re.findall(r'"([^"]+)"', text or '')]

    def visual_corroborated(self, goal, picked_id, actions):
        """Deterministic check: goal's quoted tokens appear only in the pick's
        own record context (see record_context/actions), never another
        candidate's. Model score/evidence text alone never authorizes a click.
        """
        tokens = self.quoted_tokens(goal)
        if not tokens:
            return False
        contexts = {a['id']: a.get('description', '').casefold() for a in actions}
        picked = contexts.get(picked_id, '')
        if not all(token.casefold() in picked for token in tokens):
            return False
        return not any(aid != picked_id and any(token.casefold() in ctx for token in tokens)
                        for aid, ctx in contexts.items())

    @staticmethod
    def _within_one_edit(a, b):
        if abs(len(a) - len(b)) > 1:return False
        if a == b:return True
        i = 0
        while i < min(len(a), len(b)) and a[i] == b[i]:i += 1
        if len(a) == len(b):return a[i+1:] == b[i+1:]
        short, long_ = (a, b) if len(a) < len(b) else (b, a)
        return short[i:] == long_[i+1:]

    def region_corroborated(self, goal, picked_id, actions, all_texts=None):
        """Regions are labels, so corroboration is an EXACT label match: every quoted
        token equals the picked region's text and no other text region ANYWHERE in the
        window is within one edit of it. Measuring only the narrowed candidates would let
        a decoy that reads exactly the quote win when the real control's OCR is garbled
        ("Sove"); substring uniqueness would never let "Export" beat "Export All".
        Several quoted tokens must all equal the one picked text (fails closed).
        """
        tokens = [self._ocr_normalize(t) for t in self.quoted_tokens(goal)]
        if not tokens:return False
        texts = {a['id']: self._ocr_normalize(a.get('evidence_text') or a.get('description')) for a in actions}
        if picked_id not in texts:return False
        pool = list(all_texts) if all_texts is not None else list(texts.values())
        for token in tokens:
            if texts[picked_id] != token:return False
            near = [t for t in pool if (self._within_one_edit(t, token) if len(token) >= 3 else t == token)]
            if len(near) != 1:return False
        return True

    def incomplete_scope_defer(self, filt, read=None):
        extracted = {r['record_id']: r['fields'] for r in (read or {}).get('extraction', {}).get('records', [])
                     if r['record_id'] in filt['unknown_ids']}
        return {'status': 'defer', 'route': 'nuextract3', 'reason': 'unknown_or_incomplete_scope',
                'unknown_ids': filt['unknown_ids'], 'excluded_count': len(filt['excluded_ids']),
                'eligible_ids': filt['eligible_ids'],
                'missing_fields': {aid: filt['checks'][aid]['gaps'] for aid in filt['unknown_ids']},
                'extracted': extracted,
                'hint': 'Do not re-read. A record whose strings are shown above is yours to judge: pass the records '
                        'you find eligible as candidate_ids or record_actions with this reading. Only a record with '
                        'no extracted value for a listed field justifies one re-read; otherwise the scope stays incomplete.'}

    def actions(self, state, ids, operation, text):
        if operation not in ('click','type_text'):
            raise Gap('Supported bound operations: click, type_text; use explicit raw fallback for others')
        if len(set(ids)) != len(ids):raise Gap('Duplicate candidates')
        result = []
        seen = set()
        for candidate in ids:
            node = self.node(state,candidate)
            canonical=state['aliases'].get(node['element_index'],node['element_index'])
            if canonical in seen:continue
            seen.add(canonical)
            if node.get('enabled') is False:continue
            if operation=='click' and 'AXPress' not in node.get('actions',[]):continue
            if operation=='type_text' and node.get('role') not in ('AXTextField','AXTextArea','AXComboBox','AXSearchField'):continue
            evidence,_ = self.subtree(state,candidate)
            args={'pid':state['pid'],'window_id':state['window_id'],'session':self.session,
                  'element_token':node['element_token']}
            if operation=='type_text':
                if text is None:raise Gap('type_text requires caller text')
                args['text']=text
            base_description=node.get('label') or node.get('value') or node.get('role','')
            own={node.get('label') or '',node.get('value') or ''}
            context=self.record_context(state,node['element_index'])
            record_basis=None
            if not context:
                # AX-only grouping found nothing (flat/ambiguous tree); fall
                # back to perception layout for description/corroboration only.
                context,record_basis=self.record_context_perception(state,node['element_index'])
            context_lines=[line for line in context.split('\n') if line and line not in own]
            record_text=' · '.join(context_lines)[:240]
            description=base_description+' — record: '+record_text if record_text else base_description
            result.append({'id':candidate,'name':node.get('label',''),'role':node.get('role'),
                           'operation':operation,'enabled':True,'evidence_text':evidence,
                           'description':description,
                           **({'record_basis':record_basis} if record_basis else {}),
                           'arguments':args})
        return result

    def choose_regions(self, snapshot, goal, candidate_ids=None, operation='click'):
        """Offer perception regions (from THIS snapshot's capture) as candidates
        for a canvas/pixel-only pick, per the Driver's documented capture-bound
        contract (perception-extension.md 'Capture-bound parse and action';
        click's capture_id+x,y admits and consumes that exact capture). Requires
        the same answer-leak rejection and quoted-text corroboration as visual
        mode -- OCR text never authorizes alone; it only corroborates.
        """
        state=self.state(snapshot)
        if operation!='click':raise Gap('regions mode supports click only (capture-bound pixel dispatch)')
        self.reject_answer_leak(state,goal)
        capture_id=state['raw'].get('capture_id')
        if not capture_id:raise Gap('capture_unavailable: no live Driver capture_id on this observation; reobserve to get one')
        parsed=self.regions(snapshot)
        regions=parsed.get('regions',[])
        if candidate_ids is not None:regions=[r for r in regions if r.get('id') in candidate_ids]
        # Candidates are text regions, narrowed by the label the caller quoted in the
        # goal. Icons and browser chrome are never bulk-offered (live: 41 regions went
        # to a chooser capped at 18); an oversized scope defers rather than truncating.
        regions=[r for r in regions if r.get('kind')=='text' and (r.get('text') or '').strip()]
        tokens=self.quoted_tokens(goal)
        if not regions:raise Gap('No perception text regions in the requested scope')
        all_texts=[self._ocr_normalize(r['text']) for r in regions]  # the whole window, before any narrowing
        if tokens and len(regions)>REGION_CANDIDATE_LIMIT:
            # Only an oversized scope is narrowed, and only by the caller's own quoted label.
            regions=[r for r in regions if all(self._ocr_normalize(t) in self._ocr_normalize(r['text']) for t in tokens)]
            if not regions:raise Gap('No perception text regions match the quoted label')
        if len(regions)>REGION_CANDIDATE_LIMIT:
            self.event('choose',snapshot=snapshot,route='scope_guard',mode='regions',authorized=False,
                       reason='too_many_regions',region_count=len(regions))
            return {'status':'defer','route':'scope_guard','reason':'too_many_regions','region_count':len(regions),
                    'hint':'Quote the button label in the goal (e.g. "Export") to narrow the text regions; '
                           'regions mode never truncates or ranks an oversized scope.'}
        actions=[]
        for r in regions:
            bounds=r.get('bounds') or {}
            description=r.get('text') or r.get('label') or r.get('kind','region')
            actions.append({'id':r['id'],'name':description,'role':'perception_region:'+r.get('kind',''),
                            'operation':operation,'enabled':True,'evidence_text':r.get('text') or '',
                            'description':description,'record_basis':'perception_layout',
                            'arguments':{'pid':state['pid'],'window_id':state['window_id'],'session':self.session,
                                        'capture_id':capture_id,'delivery_mode':'background',
                                        'target':{'kind':'window','pid':state['pid'],'window_id':state['window_id']},
                                        'x':bounds.get('x',0)+bounds.get('width',0)/2,
                                        'y':bounds.get('y',0)+bounds.get('height',0)/2}})
        if len(actions)==1:
            self.event('choose',snapshot=snapshot,route='scope_guard',mode='regions',authorized=False,
                       reason='singleton_requires_grounded_reading')
            return {'status':'defer','route':'scope_guard','reason':'singleton_requires_grounded_reading',
                    'hint':'Offer multiple region alternatives, or use AX exact/spans mode for a genuinely unique control.'}
        request={'snapshot_id':state['raw']['snapshot_id'],'kind':'semantic','operation':operation,
                 'goal':goal,'actions':actions,'observation':'\n'.join(a['description'] for a in actions)}
        policy=Strangler.from_config({'incumbent_jev':lambda step,req:self.provider('generic')(step,req)})
        start=self.clock();event_start=len(self.events)
        decision=policy.decide(request,request['snapshot_id'])
        if decision.get('action_authorized'):
            picked=decision['action_id']
            # As in visual mode (review P1): a caller-narrowed region list cannot
            # self-corroborate; quote uniqueness only counts across all regions.
            if candidate_ids is not None or not self.region_corroborated(goal,picked,actions,all_texts):
                self.event('choose',snapshot=snapshot,route='visual_uncorroborated_guard',mode='regions',
                           authorized=False,reason='visual_uncorroborated')
                return {'status':'defer','route':'visual_uncorroborated_guard','reason':'visual_uncorroborated',
                        'suggested_id':picked,'snapshot':snapshot}
        elapsed=(self.clock()-start)*1000
        setup=sum(e.get('setup_ms',0) for e in self.events[event_start:])
        output=decision.get('provider_outputs',[])
        route=[r.get('route',r.get('model','unknown')) for r in output]
        self.event('choose',snapshot=snapshot,route=route,mode='regions',decision_ms=max(0,elapsed-setup),
                   provider_setup_ms=setup,wall_ms=elapsed,authorized=decision.get('action_authorized',False),
                   reason=decision.get('reason'),caller_preselected=candidate_ids is not None)
        result={'status':decision['status'],'route':route,'decision':decision,'snapshot':snapshot,
                'offered_count':len(actions),'caller_preselected':candidate_ids is not None,
                'candidate_scope':'caller_subset' if candidate_ids is not None else 'observed_or_filtered_scope'}
        if decision.get('action_authorized'):
            handle='sel_'+uuid.uuid4().hex
            self.selections[handle]={'snapshot':snapshot,'request':copy.deepcopy(request),'decision':copy.deepcopy(decision),
                                     'mode':'regions','operation':operation,'text':None,'used':False,'allow_foreground':self.foreground_ok,'capture_id':capture_id}
            while len(self.selections)>32:self.selections.pop(next(iter(self.selections)))
            result.update(selection=handle,selected_id=decision['action_id'])
        return result

    def choose(self, snapshot, goal, candidate_ids=None, mode='semantic', exact_name=None, exact_role=None,
               operation='click', text=None, reading=None, fields=None, predicates=None, order_by=None,
               coverage_complete=False,record_actions=None,accept_unknown=None):
        if mode=='regions':
            return self.choose_regions(snapshot,goal,candidate_ids,operation)
        state=self.state(snapshot)
        modes={'exact','semantic','visual','spans'}
        if mode not in modes:raise Gap('Unsupported selection mode')
        if mode in ('semantic','visual'):self.reject_answer_leak(state,goal)
        ids=candidate_ids if candidate_ids is not None else ['e'+str(i) for i in state['nodes']]
        # Exact uniqueness must be checked against the entire observed scope,
        # never against a caller-supplied singleton hiding duplicate controls.
        if mode=='exact':
            if not exact_name:raise Gap('Exact mode requires an observed name, not a synthetic ID')
            ids=['e'+str(i) for i in state['nodes'] if i not in state['aliases']]
        if mode=='spans' and fields and not all(isinstance(v,dict) and v.get('description') for v in fields.values()):
            raise Gap('spans fields map each name to {description, type}, e.g. {"provider": {"description": "clinician name", "type": "text"}}')
        if (fields or predicates or order_by) and mode not in ('spans',) and not reading:
            raise Gap('Typed criteria require a reading handle or spans mode; they cannot be ignored')
        # A caller-narrowed candidate_ids scope (no reading grounding it) means
        # the caller preselected a winner; the chooser mustn't be counted as
        # having found it independently. Not chooser-accuracy evidence.
        full_ids={'e'+str(i) for i,n in state['nodes'].items()
                  if i not in state['aliases'] and self._operation_compatible(n,operation)}
        caller_preselected=(candidate_ids is not None and not reading and mode not in ('exact','spans')
                             and set(candidate_ids)<full_ids)
        if reading:
            if mode not in ('semantic','visual'):raise Gap('A reading uses semantic or visual mode; spans/exact use their own evidence')
            read=copy.deepcopy(self.readings.get(reading))
            if not read or read['snapshot']!=snapshot:raise Gap('Reading is not bound to this observation')
            if fields or order_by:raise Gap('Reading schemas come from cua_read; ordering is supported only in spans mode')
            grounded=[r['record_id'] for r in read['extraction']['records']]
            # S4.8: the controller may judge the strings itself. Record IDs in
            # candidate_ids/record_actions are its verdict on eligibility; they
            # must be this reading's records and not excluded by stated text
            # predicates. Without a verdict the filter decides and unknowns defer.
            judged=list(record_actions) if record_actions is not None else (
                list(candidate_ids) if candidate_ids is not None and set(candidate_ids)<=set(grounded) else None)
            if judged is None and not read['filter']['complete']:return self.incomplete_scope_defer(read['filter'],read)
            base_retained=read['filter']['eligible_ids']
            if predicates:
                # Filter cached evidence, never repeat extraction or silently send
                # unexecuted typed criteria only as free-text model context.
                read['filter']=filter_records(read['extraction'],fields=read['fields'],
                    predicates=read['predicates']+predicates,
                    coverage_complete=read['filter']['coverage_complete'],
                    current_snapshot=state['raw']['snapshot_id'])
                read['predicates']+=predicates
                self.event('filter',route='typed_same_record',snapshot=snapshot,
                           eligible=len(read['filter']['eligible_ids']),unknown=len(read['filter']['unknown_ids']),
                           excluded=len(read['filter']['excluded_ids']))
                if judged is None and not read['filter']['complete']:return self.incomplete_scope_defer(read['filter'],read)
            filt=read['filter']
            if record_actions is not None:
                # A cross-record target is a defect regardless of eligibility.
                for root,target in record_actions.items():
                    _,members=self.subtree(state,root)
                    if self.node(state,target)['element_index'] not in members:
                        raise Gap('Record action is outside its source record')
            if judged is not None:
                stray=[r for r in judged if r not in grounded]
                if stray:raise Gap('Judged records must be records of this reading: %s' % stray)
                # Stated text predicates can only narrow a verdict, never be overridden by it.
                retained=[r for r in judged if r not in filt['excluded_ids']]
                if not retained:raise Gap('Every judged record %s was excluded by the stated predicates' % judged)
                judgment='controller' if set(retained)!=set(filt['eligible_ids']) else 'filter'
            else:
                retained=filt['eligible_ids'];judgment='filter'
            unknown_competitors=[r for r in filt['unknown_ids'] if r not in retained]
            acknowledged=list(accept_unknown or [])
            stray=[r for r in acknowledged if r not in filt['unknown_ids']]
            if stray:raise Gap('accept_unknown names records that are not unknown in this reading: %s' % stray)
            unacknowledged=[r for r in unknown_competitors if r not in acknowledged]
            if unacknowledged:
                # S4.2 section 4: an unknown possible competitor prevents automatic
                # selection. The controller may release it, but only by naming it.
                extracted={r['record_id']:r['fields'] for r in read['extraction']['records'] if r['record_id'] in unacknowledged}
                self.event('choose',snapshot=snapshot,route='scope_guard',mode=mode,authorized=False,
                           reason='unknown_competitors_unacknowledged',unknown_competitors=len(unacknowledged))
                return {'status':'defer','route':'scope_guard','reason':'unknown_competitors_unacknowledged',
                        'unknown_ids':unacknowledged,'extracted':extracted,'judged_ids':retained,
                        'hint':'Your verdict skips records the reading left unknown. If their strings above show they are '
                               'ineligible, repeat this call with accept_unknown listing exactly those IDs; otherwise include '
                               'them in your verdict or narrow the scope. Do not re-read just to fill a format.'}
            mapped=[]
            for root in retained:
                _,members=self.subtree(state,root)
                if record_actions is not None:
                    target=record_actions[root]
                else:
                    choices=self.actions(state,['e'+str(i) for i in state['nodes'] if i in members],operation,text)
                    if len(choices)!=1:raise Gap('Record has ambiguous controls; supply record_actions')
                    target=choices[0]['id']
                mapped.append(target)
            allowed_scopes=[set(retained),set(base_retained),set(mapped)]
            if record_actions is not None:allowed_scopes.append(set(record_actions.values()))
            if candidate_ids is not None and set(candidate_ids) not in allowed_scopes:
                raise Gap('candidate_ids must be this reading\'s judged/eligible record IDs or their mapped control IDs')
            ids=mapped
        actions=self.actions(state,ids,operation,text)
        if reading and {a['id'] for a in actions} != set(ids):
            raise Gap('An eligible record lacks an enabled compatible control; cannot silently exclude it')
        if reading and len(actions)==1:
            # S4.2 §5: a unique best yields the bound action. A reading-grounded
            # singleton (filter-unique or controller-judged) binds without any
            # chooser round trip; the trace names whose judgment it was.
            request={'snapshot_id':state['raw']['snapshot_id'],'kind':'semantic','operation':operation,
                     'goal':goal,'actions':actions,'observation':actions[0]['description'],'specialist_context':read}
            decision={'status':'selected','action_id':actions[0]['id'],'action_authorized':True,
                      'reason':'grounded_singleton','judgment':judgment,'snapshot_id':request['snapshot_id'],
                      'binding_digest':request_digest(request),'provider_outputs':[]}
            self.event('choose',snapshot=snapshot,route='grounded_singleton',models=[],mode=mode,decision_ms=0,
                       provider_setup_ms=0,wall_ms=0,authorized=True,reason='grounded_singleton',judgment=judgment,
                       unknown_competitors=len(unknown_competitors),accepted_unknown=len(acknowledged),caller_preselected=judgment=='controller')
            return self.issue(snapshot,request,decision,mode,operation,text,
                              {'status':'selected','route':'grounded_singleton','decision':decision,'snapshot':snapshot,
                               'offered_count':1,'judgment':judgment,'unknown_competitors':unknown_competitors,'accepted_unknown':acknowledged,
                               'caller_preselected':judgment=='controller','candidate_scope':'observed_or_filtered_scope'})
        if mode=='semantic' and len(actions)==1 and not reading:
            self.event('choose',snapshot=snapshot,route='scope_guard',mode=mode,
                       authorized=False,reason='singleton_requires_grounded_reading')
            return {'status':'defer','route':'scope_guard',
                    'reason':'singleton_requires_grounded_reading',
                    'hint':'Offer the relevant alternatives, or use a complete filtered reading; exact mode remains available for unique controls.'}
        request={'snapshot_id':state['raw']['snapshot_id'],'kind':'semantic','operation':operation,
                 'goal':goal,'actions':actions,'observation':'\n'.join(a['description'] for a in actions)}
        if reading:request['specialist_context']=read
        if mode=='exact':
            request.update(kind='exact',target={'name':exact_name,**({'role':exact_role} if exact_role else {})})
            policy=Engine({})
        elif mode=='visual':
            if not state['image']:raise Gap('Visual choice needs a Driver screenshot')
            import base64
            request['screenshot_data_url']='data:image/png;base64,'+base64.b64encode(state['image']).decode()
            policy=Engine({'jev':self.provider('visual')})
        elif mode=='spans':
            request.update(kind='match',shape='spans',language='en',candidate_ids=[a['id'] for a in actions],
                fields=fields or {},predicates=predicates or [],order_by=order_by or [],coverage_complete=coverage_complete)
            # Lazy recovery: don't start Julia unless the dispatcher actually asks.
            policy=Strangler.from_config({'gliner2':self.provider('spans'),
                'incumbent_jev':lambda step,req:self.provider('generic')(step,req)})
        else:
            policy=Strangler.from_config({'incumbent_jev':lambda step,req:self.provider('generic')(step,req)})
        start=self.clock(); event_start=len(self.events)
        decision=policy.decide(request,request['snapshot_id'])
        if mode=='visual' and decision.get('action_authorized'):
            # A model pick (even scored) never authorizes alone: either a complete
            # filtered reading grounds it (the offered actions are already the
            # reading's mapped controls), or the goal's quoted text deterministically
            # names this candidate's own record and no other's.
            picked=decision['action_id']
            # Quoted-text corroboration only counts across the full observed scope:
            # against a caller-narrowed subset it just ratifies the caller's winner.
            if not (bool(reading) or (not caller_preselected and self.visual_corroborated(goal,picked,actions))):
                self.event('choose',snapshot=snapshot,route='visual_uncorroborated_guard',mode=mode,
                           authorized=False,reason='visual_uncorroborated',caller_preselected=caller_preselected)
                return {'status':'defer','route':'visual_uncorroborated_guard','reason':'visual_uncorroborated',
                        'suggested_id':picked,'snapshot':snapshot}
        elapsed=(self.clock()-start)*1000
        setup=sum(e.get('setup_ms',0) for e in self.events[event_start:])
        output=decision.get('provider_outputs',[])
        route='exact_observed_control' if mode=='exact' else [r.get('route',r.get('model','unknown')) for r in output]
        provider_models=[entry.get('model') for out in output for entry in out.get('trace',[out]) if entry.get('model')]
        self.event('choose',snapshot=snapshot,route=route,models=provider_models,mode=mode,decision_ms=max(0,elapsed-setup),provider_setup_ms=setup,wall_ms=elapsed,
                   authorized=decision.get('action_authorized',False),reason=decision.get('reason'),caller_preselected=caller_preselected)
        result={'status':decision['status'],'route':route,'decision':decision,'snapshot':snapshot,
                'offered_count':len(actions),'caller_preselected':caller_preselected,
                'candidate_scope':'caller_subset' if candidate_ids is not None and not reading and mode!='exact' else 'observed_or_filtered_scope',
                **({'judgment':judgment,'unknown_competitors':unknown_competitors,'accepted_unknown':acknowledged} if reading else {})}
        if mode=='exact' and not decision.get('action_authorized'):
            # Additive diagnosis of exact_target_not_unique: the offered actions only include press-capable nodes, so a control that
            # Chrome did not advertise AXPress on is invisible here and the target looks absent, not duplicated (live orders dialog).
            observed=[n for i,n in state['nodes'].items() if i not in state['aliases'] and n.get('label')==exact_name and (exact_role is None or n.get('role')==exact_role)]
            offered_named=[a for a in actions if a['name']==exact_name and (exact_role is None or a['role']==exact_role)]
            result['diagnostic']={'observed_named':len(observed),'offered_named':len(offered_named),
                'not_press_capable':len(observed)-len(offered_named) if len(observed)>len(offered_named) else 0}
        return self.issue(snapshot,request,decision,mode,operation,text,result)

    def issue(self,snapshot,request,decision,mode,operation,text,result):
        """Store an authorized selection with the content scope it was bound in."""
        if decision.get('action_authorized'):
            state=self.state(snapshot)
            root=self.content_root(state,[a['id'] for a in request['actions']])
            if state['nodes'][root].get('role')=='AXWebArea' and not self.address_fields(state,self.subtree(state,'e'+str(root))[1]):
                root=None  # navigation unobservable without an address field: keep whole-window revalidation
            handle='sel_'+uuid.uuid4().hex
            self.selections[handle]={'snapshot':snapshot,'request':copy.deepcopy(request),'decision':copy.deepcopy(decision),
                                     'mode':mode,'operation':operation,'text':text,'used':False,
                                     'scope_root':root,'scope_digest':None if root is None else self.scope_digest(state,root)}
            while len(self.selections)>32:self.selections.pop(next(iter(self.selections)))
            result.update(selection=handle,selected_id=decision['action_id'])
        return result

    def bind_press(self,snapshot,node_id,goal):
        """Bind ONE press on an observed element the caller already identified by structure (not by a chooser): the same issue/act path
        as a grounded singleton, so act() revalidates the observation before the Driver is called. Returns the selection handle."""
        state=self.state(snapshot)
        actions=self.actions(state,[node_id],'click',None)
        if len(actions)!=1:raise Gap('control_not_pressable: the observed element is disabled or has no AXPress action')
        request={'snapshot_id':state['raw']['snapshot_id'],'kind':'semantic','operation':'click','goal':goal,'actions':actions,'observation':actions[0]['description']}
        decision={'status':'selected','action_id':node_id,'action_authorized':True,'reason':'observed_structure','judgment':'structure',
                  'snapshot_id':request['snapshot_id'],'binding_digest':request_digest(request),'provider_outputs':[]}
        self.event('choose',snapshot=snapshot,route='observed_structure',models=[],mode='semantic',decision_ms=0,provider_setup_ms=0,wall_ms=0,
                   authorized=True,reason='observed_structure')
        return self.issue(snapshot,request,decision,'semantic','click',None,{'status':'selected','route':'observed_structure','decision':decision,'snapshot':snapshot})['selection']

    def content_root(self,state,ids):
        """The observed content scope a selection binds to: the offered actions'
        common ancestor, widened to the enclosing AXWebArea when there is one
        (a browser's page), else the window root. Browser chrome such as a tab
        strip's live memory readout is outside a page action's scope.
        """
        chains=[]
        for cid in ids:
            index=self.node(state,cid)['element_index'];chain=[]
            while index in state['nodes'] and index not in chain:
                chain.append(index);index=state['nodes'][index].get('parent_index')
            chains.append(chain)
        common=[i for i in chains[0] if all(i in c for c in chains[1:])]
        lca=common[0] if common else chains[0][-1]
        for i in chains[0][chains[0].index(lca):]:
            if state['nodes'][i].get('role')=='AXWebArea':return i
        return chains[0][-1]

    @staticmethod
    def address_fields(state,members):
        return [{'role':n.get('role'),'value':n.get('value')} for i,n in sorted(state['nodes'].items())
                if i not in members and n.get('role') in ('AXTextField','AXComboBox') and n.get('value')]

    def scope_changes(self,before,after,root):
        # Diagnostic only, called after the selection is spent: it must never
        # replace the refusal with its own crash on an unusual tree.
        try:return self._scope_changes(before,after,root)
        except Exception:return 'digest differs'

    def _scope_changes(self,before,after,root):
        """Where a bound scope differs, by element id, role and changed field names
        only (never page values), so a refusal is diagnosable without leaking text."""
        if root not in after['nodes']:return 'scope root %s is gone' % ('e'+str(root))
        _,old=self.subtree(before,'e'+str(root));_,new=self.subtree(after,'e'+str(root))
        skip={'element_token'};out=[]
        for i in sorted(old|new):
            a,b=before['nodes'].get(i) if i in old else None,after['nodes'].get(i) if i in new else None
            if a is None or b is None:
                out.append('e%d %s' % (i,'added' if a is None else 'removed'));continue
            keys=sorted(k for k in set(a)|set(b) if k not in skip and a.get(k)!=b.get(k))
            if keys:out.append('e%d %s: %s' % (i,b.get('role'),','.join(keys)))
        a_addr=self.address_fields(before,old) if before['nodes'][root].get('role')=='AXWebArea' else []
        b_addr=self.address_fields(after,new) if after['nodes'][root].get('role')=='AXWebArea' else []
        if a_addr!=b_addr:out.append('address field changed')
        if before['raw'].get('window_title')!=after['raw'].get('window_title'):out.append('window title changed')
        return ('; '.join(out[:6])+(' ...' if len(out)>6 else '')) or 'digest differs'

    def scope_digest(self,state,root):
        _,members=self.subtree(state,'e'+str(root))
        # A page scope also binds the address field (role and value only): a
        # navigation is a different page even when its tree happens to match.
        address=[] if state['nodes'][root].get('role')!='AXWebArea' else self.address_fields(state,members)
        # A tab strip's live memory readout ('<title> - Memory usage - 32.4 MB') changes between observations and is not page state
        # (S4.8): the number is masked, the title is not.
        def mask(node):
            tab=node.get('role')=='AXRadioButton'  # only a tab-strip tab carries the readout; page text is never masked
            return {k:(MEMORY_READOUT.sub(r'\1#',v) if tab and isinstance(v,str) else v) for k,v in node.items() if k!='element_token'}
        return digest({'title':state['raw'].get('window_title'),'address':address,
                       'nodes':[mask(state['nodes'][i]) for i in sorted(members)]})

    def act(self, selection):
        item=self.selections.get(selection)
        if not item or item['used']:raise Gap('Unknown or already consumed selection')
        state=self.state(item['snapshot'])
        item['used']=True  # Never replay an uncertain side effect.
        try:
            fresh=self.observe(state['pid'],state['window_id'])
        except DriverCallFailed:
            item['used']=False  # nothing was clicked: transient Driver failure, not an uncertain side effect
            raise
        current=self.state(fresh['snapshot'])
        self.check_foreground(current['raw'])
        # Revalidate the content scope the selection was bound in (S4.8): any
        # change inside it refuses; a change outside it (browser chrome) does not.
        root=item.get('scope_root')
        if root is None:
            if state['fingerprint']!=current['fingerprint']:
                raise StaleUI('UI changed since selection; reobserve and choose again')
        elif root not in current['nodes'] or self.scope_digest(current,root)!=item['scope_digest']:
            raise StaleUI('UI changed within the bound content scope since selection (%s); reobserve and choose again'
                      % self.scope_changes(state,current,root))
        if item['mode']=='visual' and state['image_digest']!=current['image_digest']:
            raise Gap('Visual evidence changed; choose again from current screenshot')
        request=copy.deepcopy(item['request'])
        if item['mode']=='regions':
            # A capture-bound pixel click is admitted/consumed against its
            # ORIGINAL capture_id, never rebound to a fresh one (the Driver's
            # capture registry -- not this facade -- is the source of truth for
            # capture_not_found/capture_expired). We only add the AX-unchanged
            # safety check above; the capture identity itself must not move.
            if self.clock()-state['created']>PERCEPTION_CAPTURE_TTL_S:
                raise Gap('capture_expired: perception captures expire after %ds upstream; reobserve and choose again'
                          % PERCEPTION_CAPTURE_TTL_S)
            # A background pixel click never reaches a drawn surface: cua-driver 0.30.x turns it into an AXPress on the element
            # under the point, which Chrome delivers at that element's CENTRE (probe 2026-09-29 on our own fixture: aimed at a
            # corner button, the centre button was pressed, reported as success). So it is a wrong click, not a no-op, and it is
            # never sent. A real pointer event needs the Driver's foreground delivery, which fronts the window briefly: only the
            # caller's explicit allow_foreground (this call or this step) permits that.
            if not item.get('allow_foreground'):
                item['used']=False  # nothing was clicked
                raise Gap("pointer_not_deliverable_in_background: a background pixel click on a drawn surface lands at the element's centre, not at %r; nothing was clicked. Pass allow_foreground=true (this call or step) to let the Driver briefly front the window for a real pointer event, only if the user allows that" % (item['request']['actions'][0].get('name') or '')[:40])
            for action in request['actions']:action['arguments']['delivery_mode']='foreground'
            request['snapshot_id']=current['raw']['snapshot_id']
            decision={**item['decision'],'snapshot_id':request['snapshot_id'],'binding_digest':request_digest(request)}
        else:
            # Rebind only after proving the entire observed AX content/frames unchanged.
            # IDs are server-owned element indices; only Driver-issued tokens change.
            request['snapshot_id']=current['raw']['snapshot_id']
            for action in request['actions']:
                action['arguments']['element_token']=self.node(current,action['id'])['element_token']
            decision={**item['decision'],'snapshot_id':request['snapshot_id'],'binding_digest':request_digest(request)}
        result=execute_bound(request,decision,request['snapshot_id'],lambda tool,args:self.driver.call(tool,args))
        self.latest.pop((state['pid'],state['window_id']),None)
        self.event('act',route='cua-driver',selection=selection,revalidation='unchanged_observation',
                   original_binding=item['decision']['binding_digest'],fresh_binding=decision['binding_digest'],
                   verification='pending')
        return {'status':'delivered','driver_result':result,'requires_verification':True,
                'pid':state['pid'],'window_id':state['window_id']}

    @staticmethod
    def _ocr_normalize(text):
        return re.sub(r'\s+', ' ', (text or '').strip()).casefold()

    def _perception_fuzzy_check(self, quoted, parsed):
        """Fuzzy OCR presence check used only after the AX quoted-text check
        fails and before calling the hosted vision model (facade/core.py
        Facade.verify). Perception's own OCR corrupts values with digits
        ("60 min"->"600 min", "1:30 PM"->"130 PM"; docs/FACADE.md evidence
        table), so this NEVER returns satisfied for a quote containing a digit,
        and NEVER on a merely fuzzy/partial match -- those return unknown with
        evidence: ocr_candidate so the caller still corroborates independently.
        Only a short, digit-free quote that matches exactly-once after
        normalization may return satisfied.
        """
        texts = [r.get('text') or '' for r in parsed.get('regions', []) if r.get('kind') == 'text']
        normalized = [self._ocr_normalize(t) for t in texts]
        for token in quoted:
            needle = self._ocr_normalize(token)
            if not needle:
                continue
            hits = [i for i, t in enumerate(normalized) if t == needle]
            if hits:
                if any(ch.isdigit() for ch in needle) or len(hits) != 1:
                    return {'status': 'unknown', 'route': 'perception_ocr_fuzzy', 'evidence': 'ocr_candidate',
                            'matched_region': texts[hits[0]] if len(hits) == 1 else None}
                return {'status': 'satisfied', 'route': 'perception_ocr_fuzzy',
                        'reason': 'quoted_text_observed_in_ocr_region_exact_single_match',
                        'matched_region': texts[hits[0]]}
        for token in quoted:
            needle = self._ocr_normalize(token)
            candidate = next((t for t in texts if needle and (needle in self._ocr_normalize(t) or self._ocr_normalize(t) in needle)), None)
            if candidate:
                return {'status': 'unknown', 'route': 'perception_ocr_fuzzy', 'evidence': 'ocr_candidate',
                        'matched_region': candidate}
        return None

    def verify(self,pid,window_id,postcondition,mode='visual',name=None,role=None,value=None,match='equals'):
        began=self.clock()
        fresh=self.observe(pid,window_id);state=self.state(fresh['snapshot'])
        assessment_start=self.clock();event_start=len(self.events)
        if match not in ('equals','contains'):raise Gap('match must be equals or contains')
        def text_match(actual,needle):
            if needle is None:return True
            if actual is None:return False
            if match=='equals':return actual==needle
            return needle.casefold() in str(actual).casefold()
        if mode=='exact':
            if not name:raise Gap('Exact verification requires an observed label')
            matches=[n for n in state['nodes'].values() if text_match(n.get('label'),name) and (role is None or n.get('role')==role)]
            ok=any(text_match(n.get('value'),value) for n in matches)
            result={'status':'satisfied' if ok else 'unknown','route':'exact_postcondition',
                    'reason':'observed_matching_element' if ok else 'absence_not_proven'}
        elif mode=='visual':
            # A quoted postcondition string is checked deterministically against
            # the fresh AX tree first; only fall back to the vision model when
            # that text isn't observed there (e.g. it's a purely visual state).
            # Only a purely textual postcondition short-circuits: any other
            # constraint (which row, which view) still needs vision, never
            # text that merely appears somewhere in the window.
            quoted=self.quoted_tokens(postcondition)
            rest=set(re.findall(r'[a-z0-9#]+',re.sub(r'"[^"]*"',' ',postcondition or '').casefold()))-self.TEXT_ONLY_FILLER
            # Each quote must be observed in exactly one element: text repeated
            # across records ("Cancelled") cannot establish which one changed.
            texts=[f"{n.get('label') or ''} {n.get('value') or ''}".casefold() for n in state['nodes'].values()]
            if quoted and not rest and all(sum(token.casefold() in t for t in texts)==1 for token in quoted):
                result={'status':'satisfied','route':'exact_text_postcondition',
                        'reason':'quoted_text_observed_in_ax_tree','matched_quotes':quoted}
            else:
                perception_hint=None
                if quoted and self.perception_state=='healthy':
                    try:perception_hint=self._perception_fuzzy_check(quoted,self.regions(fresh['snapshot']))
                    except Gap:perception_hint=None
                if perception_hint and perception_hint['status']=='satisfied':
                    result=perception_hint
                else:
                    import base64
                    try:
                        result=self.provider('visual').inspect({**state['raw'],
                        'screenshot_data_url':'data:image/png;base64,'+base64.b64encode(state['image']).decode() if state['image'] else None},postcondition,max(0.01,20-(self.clock()-began)))
                    except (ValueError, RuntimeError, TimeoutError, OSError) as error:
                        result={'state':'unknown','reason':'visual_provider_failure','error_type':type(error).__name__}
                    result={'status':'satisfied' if result.get('state')=='ready' else 'unknown','route':'systemone_vision','assessment':result}
                    if perception_hint:result['perception_hint']=perception_hint
        else:raise Gap('Verification mode must be exact or visual')
        setup=sum(e.get('setup_ms',0) for e in self.events[event_start:])
        self.event('verify',route=result['route'],snapshot=fresh['snapshot'],status=result['status'],
                   assessment_ms=max(0,(self.clock()-assessment_start)*1000-setup),
                   provider_setup_ms=setup,wall_ms=(self.clock()-began)*1000)
        return {**result,'snapshot':fresh['snapshot'],'independent_observation':True,'observation':fresh}

    # --- cua_do: the dispatcher runs the evidence chain and its bounded recovery (S4.1-S4.2, S4.6-S4.8) ---
    DO_OPS = ('eq', 'neq', 'contains', 'not_contains')
    DO_LIST_CAP = 20
    RETRY_BACKOFF_S = 0.3
    MODAL_ROLES = ('AXSheet', 'AXDialog')
    # A record is defined by its repeated ACTIONABLE control. Real Chrome trees advertise AXPress on every static text, cell and row,
    # so press-capability alone says nothing: the role must be a control role.
    CONTROL_ROLES = ('AXButton', 'AXLink', 'AXMenuItem', 'AXMenuButton', 'AXPopUpButton', 'AXRadioButton', 'AXCheckBox')

    @staticmethod
    def _top_web_areas(state):
        """AXWebArea nodes that are not inside another web area (an iframe's web area is part of its page, not a second page)."""
        nodes, out = state['nodes'], []
        for i, n in sorted(nodes.items()):
            if n.get('role') != 'AXWebArea':continue
            a, nested, seen = n.get('parent_index'), False, {i}
            while a in nodes and a not in seen:
                seen.add(a);nested = nested or nodes[a].get('role') == 'AXWebArea';a = nodes[a].get('parent_index')
            if not nested:out.append(i)
        return out

    def _content_ids(self, state):
        """Node indices of the page content (the first top-level AXWebArea subtree), else every node. The browser's own menu bar
        (hundreds of AXMenuItems) and toolbar are chrome, never the records or candidates of a page goal."""
        web = self._top_web_areas(state)
        return set(state['nodes']) if not web else self.subtree(state, 'e'+str(web[0]))[1]

    def _escalate(self, state, expect, remaining_s):
        """Perception exact-presence (never satisfies on a digit-bearing quote), then the screenshot model. Deliberately NOT cua_verify's
        AX quote check, which counts control labels and the tab strip."""
        handle = next(h for h, x in self.snapshots.items() if x is state);hint = None
        if self.perception_state == 'healthy':
            try:hint = self._perception_fuzzy_check([expect], self.regions(handle))
            except Gap:hint = None
        if hint and hint['status'] == 'satisfied':return {'status': 'satisfied', 'route': hint['route']}
        import base64
        try:
            seen = self.provider('visual').inspect({**state['raw'], 'screenshot_data_url': 'data:image/png;base64,' + base64.b64encode(state['image']).decode() if state['image'] else None},
                                                   'The window shows "%s"' % expect, max(0.01, min(20.0, remaining_s)))
        except (ValueError, RuntimeError, TimeoutError, OSError) as error:
            seen = {'state': 'unknown', 'reason': 'visual_provider_failure', 'error_type': type(error).__name__}
        return {'status': 'satisfied' if seen.get('state') == 'ready' else 'unknown', 'route': 'systemone_vision', **({'perception_hint': hint} if hint else {})}

    @staticmethod
    def _column_copies(state):
        """Nodes inside AXColumn projections of a table that also has AXRow children. Chrome exposes every cell twice (by row and by
        column); the alias detector abstains without positive frames, so these copies would otherwise double every record."""
        nodes, kids, skip = state['nodes'], {}, set()
        for i, n in nodes.items():kids.setdefault(n.get('parent_index'), []).append(i)
        for table, node in nodes.items():
            if node.get('role') != 'AXTable' or not any(nodes[c].get('role') == 'AXRow' for c in kids.get(table, [])):continue
            stack = [c for c in kids.get(table, []) if nodes[c].get('role') == 'AXColumn']
            while stack:
                x = stack.pop();skip.add(x);stack += kids.get(x, [])
        return skip

    @classmethod
    def _is_control(cls, node):
        return node.get('role') in cls.CONTROL_ROLES and node.get('enabled') is not False
    STALE = object()

    class _Ambiguous(Exception):pass

    @staticmethod
    def _do_reason(message):
        match = re.match(r'([a-z_]+):', message or '')
        return match.group(1) if match else 'refused'

    def _do_records(self, records):
        """Validate the caller's records spec (displayed strings, S4.8) before any Driver call."""
        if not isinstance(records, dict):raise Gap('bad_request: records must be {fields, predicates, record_ids}')
        fields = records.get('fields')
        if not isinstance(fields, dict) or not fields or not all(isinstance(v, dict) and v.get('description') for v in fields.values()):
            raise Gap('bad_request: records.fields maps each name to {description}')
        predicates = list(records.get('predicates') or [])
        for rule in predicates:
            if rule.get('field') not in fields:raise Gap('bad_request: predicate field %r is not in records.fields' % rule.get('field'))
            if rule.get('op', 'eq') not in self.DO_OPS:raise Gap('bad_request: predicate op must be one of %s' % ', '.join(self.DO_OPS))
        supplied = records.get('record_ids')
        if supplied is not None and (not supplied or len(set(supplied)) != len(supplied)):raise Gap('bad_request: record_ids must be distinct observed roots')
        identity = records.get('identity')
        if identity is not None and (not identity or any(k not in fields for k in identity)):raise Gap('bad_request: records.identity must name fields from records.fields')
        return fields, predicates, supplied, records.get('coverage_complete') is True, list(identity) if identity else (list(dict.fromkeys(r['field'] for r in predicates if r.get('op', 'eq') == 'eq')) or list(fields))

    def _record_root(self, state, index):
        """Outermost ancestor still holding exactly one control of this kind (as record_context)."""
        kind = lambda n: (n.get('role'), n.get('label'))
        want, root, ancestor, seen = kind(state['nodes'][index]), index, state['nodes'][index].get('parent_index'), {index}
        while ancestor in state['nodes'] and ancestor not in seen:
            seen.add(ancestor)
            if sum(1 for i in self.subtree(state, 'e'+str(ancestor))[1] if kind(state['nodes'][i]) == want) > 1:return root
            root, ancestor = ancestor, state['nodes'][ancestor].get('parent_index')
        return None

    def _label_matches(self, control, label):
        """Exact label (case and whitespace insensitive), else a whole-word prefix: control "Book" matches "Book Dr. B". Plan steps are exact only
        (self.prefix_control False) unless the step says control_match=prefix: "Finish" must never press "Finish later"."""
        norm = lambda v: re.sub(r'\s+', ' ', str(v or '').strip()).casefold()
        return norm(label) == norm(control) or (self.prefix_control and norm(label).startswith(norm(control) + ' '))

    def _shape(self, state, kids, index, depth=5):
        node = state['nodes'][index]
        return (node.get('role'), tuple(self._shape(state, kids, c, depth-1) for c in kids.get(index, [])) if depth > 0 else ())

    def _kids(self, state):
        kids = {}
        for i, n in sorted(state['nodes'].items()):kids.setdefault(n.get('parent_index'), []).append(i)
        return kids

    def _structural_units(self, state, controls):
        """Records from structure, not labels: {unit root: [controls]}. A unit is the lowest ancestor of a control that has a same-role,
        same-shape sibling (li cards, table rows, grid groups); a flat list (field texts and controls are siblings) makes each control its
        own unit when it has same-role peers with a consistent sibling-order record."""
        nodes, kids, content = state['nodes'], self._kids(state), self._content_ids(state)
        units, loose = {}, []
        for c in controls:
            a, found = nodes[c].get('parent_index'), None
            while a in nodes and a in content and nodes[a].get('role') != 'AXWebArea':
                p = nodes[a].get('parent_index');mine = self._shape(state, kids, a)
                if any(x != a and nodes[x].get('role') == nodes[a].get('role') and self._shape(state, kids, x) == mine for x in kids.get(p, [])):found = a;break
                a = p
            if found is None:loose.append(c)
            else:units.setdefault(found, []).append(c)
        flat = {}
        for c in loose:flat.setdefault((nodes[c].get('parent_index'), nodes[c].get('role')), []).append(c)
        for peers in flat.values():
            if len(peers) >= 2 and all(self.sibling_record(state, c, True) for c in peers):
                for c in peers:units[c] = [c]
        return units

    def discover_records(self, state, operation, control=None):
        """Records are defined by ACTIONABLE controls (role in CONTROL_ROLES, press-capable, inside the page content), never by repeated
        static text, cells or rows. (1) the same role+label repeated >= 2 times; else (2) structure: same-shaped units (cards, rows, groups,
        flat sibling runs) whose controls carry per-record labels; else (3) ONE actionable candidate is the record. `control` matches a
        label exactly, else as a whole-word prefix. Returns (roots, {root: control}, found, reason, disabled_roots); roots is None with a
        reason (control_needed, control_not_found, control_ambiguous, records_ambiguous) when the records cannot be told without guessing."""
        norm = lambda v: re.sub(r'\s+', ' ', str(v or '').strip()).casefold()
        content, nodes = self._content_ids(state) - self._column_copies(state), state['nodes']
        enabled, disabled = [], []
        for i, n in sorted(nodes.items()):
            if i not in content or i in state['aliases'] or n.get('role') not in self.CONTROL_ROLES:continue
            if n.get('enabled') is False:disabled.append(i)
            elif self._operation_compatible(n, operation):enabled.append(i)
        allc = sorted(enabled + disabled)
        labels = sorted({nodes[i].get('label') or '' for i in allc})
        found = {'controls': self._bounded([l for l in labels if l])}
        groups = {}
        for i in allc:groups.setdefault((nodes[i].get('role'), nodes[i].get('label') or ''), []).append(i)
        repeated = {k: v for k, v in groups.items() if len(v) >= 2}
        found['repeated_controls'] = [{'role': k[0], 'label': k[1], 'count': len(v)} for k, v in list(repeated.items())[:8]]
        if not allc:return None, {}, found, 'no_controls', set()
        units = {}
        if repeated:
            wanted = repeated
            if control is not None:
                wanted = {k: v for k, v in repeated.items() if norm(k[1]) == norm(control)}
                if not wanted:wanted = {k: v for k, v in repeated.items() if self._label_matches(control, k[1])}
                if not wanted:return None, {}, found, 'control_not_found', set()
                if len(wanted) > 1:return None, {}, found, 'control_ambiguous', set()
            elif len(wanted) > 1:return None, {}, found, 'control_needed', set()
            for i in next(iter(wanted.values())):
                root = self._record_root(state, i)
                if root is None or root in units or (root == i and not self.sibling_record(state, i)):return None, {}, found, 'records_ambiguous', set()
                units[root] = [i]
        else:
            structural = self._structural_units(state, allc)
            if len(structural) >= 2:
                units = structural
                if control is None and any(len([c for c in cs if c in enabled]) > 1 for cs in units.values()):
                    return None, {}, {**found, 'repeated_controls': [{'role': 'AXButton', 'label': l, 'count': 1} for l in found['controls'][:8]]}, 'control_needed', set()
            else:
                pool = [i for i in allc if control is None or self._label_matches(control, nodes[i].get('label') or '')]
                if control is not None and not pool:return None, {}, found, 'control_not_found', set()
                if len(pool) != 1:return None, {}, found, 'records_ambiguous', set()
                # One record: the nearest ancestor (below the page) that carries text besides the control itself.
                a, root = nodes[pool[0]].get('parent_index'), None
                while a in nodes and a in content and nodes[a].get('role') != 'AXWebArea':
                    if any(nodes[i].get('role') not in self.CONTROL_ROLES and (nodes[i].get('value') or nodes[i].get('label')) for i in self.subtree(state, 'e'+str(a))[1] if i != a):root = a;break
                    a = nodes[a].get('parent_index')
                if root is None:return None, {}, found, 'records_ambiguous', set()
                units = {root: [pool[0]]}
        targets, disabled_roots = {}, set()
        for root, cs in units.items():
            mine = [c for c in cs if control is None or nodes[c].get('label') == control or norm(nodes[c].get('label')) == norm(control)] or \
                   [c for c in cs if control is not None and self._label_matches(control, nodes[c].get('label') or '')]
            live = [c for c in mine if c in enabled]
            if len(live) > 1:return None, {}, found, 'control_ambiguous', set()
            if live:targets['e'+str(root)] = 'e'+str(live[0])
            elif any(c in disabled for c in mine):disabled_roots.add('e'+str(root))
        return ['e'+str(r) for r in units], targets, found, None, disabled_roots

    def _bounded(self, values):
        if isinstance(values, dict):
            items = list(values.items());kept = dict(items[:self.DO_LIST_CAP])
            return kept if len(items) <= self.DO_LIST_CAP else {**kept, '_truncated': len(items)-self.DO_LIST_CAP}
        return list(values)[:self.DO_LIST_CAP]

    def _visual_available(self):
        try:self.provider('visual');return True
        except Exception:return False

    def _expect_check(self, state, before, expect, target=None, typed=None):
        """Case-insensitive exact, else contains, each required in exactly ONE text-bearing NON-control node of the page content
        (static text, status text, field values other than the typed target): a button label, the address bar and the tab strip prove
        nothing. Absence is unknown, never failed. Presence that proves nothing is `unproven` (no presence-based step can prove it):
        the text was already there before the click, it is the text just typed, or it is the label of a control. before=None (a
        verify-only look) has no before-state, so presence is all it can report."""
        norm = lambda v: re.sub(r'\s+', ' ', str(v or '').strip()).casefold()
        needle = norm(expect)
        skip = (target.get('role'), target.get('label')) if target else None
        def bearing(tree):
            content = self._content_ids(tree)
            return [n for i, n in tree['nodes'].items() if i in content and n.get('role') not in self.CONTROL_ROLES and (n.get('role'), n.get('label')) != skip]
        def hits(tree, exact):
            return sum(1 for n in bearing(tree) if any((norm(n.get(k)) == needle) if exact else (needle in norm(n.get(k))) for k in ('label', 'value')))
        if typed is not None and (needle in norm(typed) or norm(typed) in needle):
            return {'status': 'unknown', 'route': 'ax_expect', 'reason': 'expect_echoes_typed_text', 'unproven': True}
        content = self._content_ids(state)
        if any(n.get('role') in self.CONTROL_ROLES and norm(n.get('label')) == needle for i, n in state['nodes'].items() if i in content):
            return {'status': 'unknown', 'route': 'ax_expect', 'reason': 'expect_is_a_control_label', 'unproven': True}
        if before is not None and hits(before, False) > 0:
            return {'status': 'unknown', 'route': 'ax_expect', 'reason': 'expect_present_before_action', 'present_before': True, 'unproven': True}
        exact, loose = hits(state, True), hits(state, False)
        present_before = False if before is not None else 'unknown'
        if exact == 1 or (exact == 0 and loose == 1):
            return {'status': 'satisfied', 'route': 'ax_expect_' + ('exact' if exact else 'contains'), 'present_before': present_before}
        return {'status': 'unknown', 'route': 'ax_expect', 'present_before': present_before,
                'reason': 'expect_ambiguous' if max(exact, loose) > 1 else 'absence_not_proven'}

    def _modal_signature(self, state, root):
        members = self.subtree(state, 'e'+str(root))[1];node = state['nodes'][root]
        return (node.get('role'), node.get('label'), tuple(sorted((n.get('role'), n.get('label') or '', str(n.get('value') or ''), tuple(n.get('actions', [])))
                                                            for n in (state['nodes'][i] for i in members))))

    def _new_modals(self, state, before):
        """(new dialog roots, replaced). A dialog is new only when no identical one (by content, not index or count)
        was open before the click; if any dialog was open before, a different one now is `replaced` (ambiguous)."""
        roots = lambda st: sorted(i for i, n in st['nodes'].items() if n.get('role') in self.MODAL_ROLES)
        was = [self._modal_signature(before, i) for i in roots(before)];had = bool(was);new = []
        for i in roots(state):
            signature = self._modal_signature(state, i)
            if signature in was:was.remove(signature)
            else:new.append(i)
        return new, bool(new and had)

    def _new_dialog(self, state, before):
        """(dialog control ids, dialog text, ambiguous). Real pages show a confirm dialog as page content, so roles cannot detect it.
        New content is a content diff (by role, label, value) inside the page. A REGION is a run of sibling subtrees whose nodes are ALL new.
        It is a dialog only if it is role-tagged (AXDialog/AXSheet) with a control, or holds >= 2 controls, and is not list growth (a new
        subtree that mirrors an existing sibling's shape, or only re-creates controls the parent already has). A toast with one Undo is not
        a dialog; a 5- or 8-button dialog is. Text is only the region's own static text, so the page's rows never vouch for it."""
        nodes, aliases = state['nodes'], state['aliases']
        sig = lambda n: (n.get('role'), n.get('label') or '', str(n.get('value') or ''))
        was = {}
        for i in self._content_ids(before):was[sig(before['nodes'][i])] = was.get(sig(before['nodes'][i]), 0) + 1
        new = []
        for i in sorted(self._content_ids(state)):
            key = sig(nodes[i])
            if was.get(key, 0) > 0:was[key] -= 1
            else:new.append(i)
        newset, kids = set(new), self._kids(state)
        def below(i):
            out, stack = set(), [i]
            while stack:
                x = stack.pop();out.add(x);stack += kids.get(x, [])
            return out
        clusters = {}
        for i in new:
            if nodes[i].get('parent_index') not in newset and below(i) <= newset:clusters.setdefault(nodes[i].get('parent_index'), []).append(i)
        regions = []
        for parent, roots in clusters.items():
            members = set().union(*(below(i) for i in roots))
            controls = [i for i in sorted(members) if i not in aliases and self._is_control(nodes[i])]
            tagged = any(nodes[i].get('role') in self.MODAL_ROLES for i in members)
            old = [x for x in kids.get(parent, []) if x not in newset]
            shapes = {self._shape(state, kids, x) for x in old}
            growth = all(self._shape(state, kids, i) in shapes for i in roots) or (
                bool(controls) and all(any((nodes[x].get('role'), nodes[x].get('label')) == (nodes[c].get('role'), nodes[c].get('label')) for x in old) for c in controls))
            if (tagged and controls) or (len(controls) >= 2 and not growth):
                texts = [str(nodes[i].get('value') or nodes[i].get('label')) for i in sorted(members)
                         if nodes[i].get('role') in ('AXStaticText', 'AXHeading') and (nodes[i].get('value') or nodes[i].get('label'))]
                regions.append((controls, '\n'.join(dict.fromkeys(texts)), members, parent))
        modals, replaced = self._new_modals(state, before)
        ambiguous = replaced or len(modals) > 1 or len(regions) > 1
        self._dialog_cluster = (regions[0][2], regions[0][3]) if regions else None  # read by _dialog_region (same observation, same call)
        return (regions[0][0], regions[0][1], ambiguous) if regions else ([], '', ambiguous)

    def _dialog_region(self, state, before):
        """EVERY node that belongs to a dialog, for a confirm step's whitelist: (a) all new nodes anywhere in the window (a warning parented outside the cluster, beside the
        web area, counts; browser chrome such as the tab strip, toolbar and address field is skipped) with their subtrees; (b) the whole subtree of the container that holds the
        dialog cluster when it is not the page or window root, so text that was ALREADY inside it (identical to text on the page before) is still compared, not dropped;
        (c) the whole subtree of the nearest dialog-tagged ancestor. A dialog whose container IS the web area is compared by its new nodes only (documented)."""
        self._new_dialog(state, before)
        nodes, content, kids = state['nodes'], self._content_ids(state), self._kids(state)
        sig = lambda n: (n.get('role'), n.get('label') or '', str(n.get('value') or ''))
        was = {}
        for n in before['nodes'].values():was[sig(n)] = was.get(sig(n), 0) + 1
        def chrome(i):
            a, guard = i, set()
            while a in nodes and a not in guard:
                guard.add(a)
                if nodes[a].get('role') in ('AXTabGroup', 'AXToolbar', 'AXMenuBar', 'AXMenu'):return True
                a = nodes[a].get('parent_index')
            return False
        new = []
        for i in sorted(nodes):
            key = sig(nodes[i])
            if was.get(key, 0) > 0:was[key] -= 1;continue
            if nodes[i].get('role') in ('AXWindow', 'AXWebArea'):continue
            if i in content or (not chrome(i) and nodes[i].get('role') not in ('AXTextField', 'AXComboBox', 'AXSearchField')):new.append(i)
        def below(i):
            out, stack = set(), [i]
            while stack:
                x = stack.pop()
                if x not in out:out.add(x);stack += kids.get(x, [])
            return out
        region = set()
        for i in new:region |= below(i)
        cluster = getattr(self, '_dialog_cluster', None)
        if cluster:
            parent = cluster[1]
            if parent in nodes and nodes[parent].get('role') not in ('AXWebArea', 'AXWindow'):region |= below(parent)
            a, guard = parent, set()
            while a in nodes and a not in guard:
                guard.add(a)
                if nodes[a].get('role') in self.MODAL_ROLES:region |= below(a);break
                a = nodes[a].get('parent_index')
        return region

    @staticmethod
    def _value_shape(value):
        """(has a digit, clock time, currency): a small deterministic shape signature of a displayed string."""
        text = str(value)
        return (bool(re.search(r'\d', text)), bool(re.search(r'\d{1,2}:\d{2}', text)), bool(re.search(r'[$\u20ac\u00a3]\s?\d|\d\s?[$\u20ac\u00a3]', text)))

    def _incomparable(self, predicate_value, value, majority):
        """S4.2 s4: a value that differs in SHAPE from what the predicate talks about (a digit-bearing predicate against 'half-hour'; NOT the reverse: a text predicate such as 'Walnut' or 'PM' against a string with incidental digits is ordinary),
        or that is an outlier of the field's majority shape in this reading, cannot be judged: it is unknown, never excluded."""
        a, b = self._value_shape(predicate_value), self._value_shape(value)
        return (a[0] and not b[0]) or (a[1] and not b[1]) or (a[2] and not b[2]) or (majority is not None and b != majority)

    def _reclassify_shapes(self, fields, predicates, extraction, filtered):
        """A record excluded ONLY by predicates that cannot be compared with its value becomes unknown. A comparable failure on any
        field (S4.2) still excludes. Recomputes eligible/unknown/excluded and completeness."""
        rows = {r['record_id']: r['fields'] for r in extraction['records']}
        majority = {}
        for name in fields:
            counts = {}
            for row in rows.values():
                if row.get(name) not in (None, ''):counts[self._value_shape(row[name])] = counts.get(self._value_shape(row[name]), 0) + 1
            top = max(counts.items(), key=lambda kv: kv[1]) if counts else None
            majority[name] = top[0] if top and top[1] * 2 > sum(counts.values()) else None
        checks = filtered['checks'];moved = False
        for aid in list(filtered['excluded_ids']):
            gaps, real = list(checks[aid]['gaps']), []
            for name in checks[aid]['failed']:
                value = rows[aid].get(name);rules = [r for r in predicates if r['field'] == name]
                failing = []
                for rule in rules:
                    try:
                        if not dispatch_predicate(dispatch_typed(value, fields[name]), rule, fields[name]) and not self._incomparable(rule['value'], value, majority[name]):failing.append(rule)
                    except (ValueError, TypeError, ArithmeticError):pass
                (real if failing else gaps).append(name)
            if not real and set(gaps) - set(checks[aid]['gaps']):
                checks[aid] = {'state': 'unknown', 'failed': [], 'gaps': gaps};moved = True
        if not moved:return filtered
        order = [r['record_id'] for r in extraction['records']]
        states = {aid: checks[aid]['state'] for aid in order}
        for key, state in (('eligible_ids', 'eligible'), ('unknown_ids', 'unknown'), ('excluded_ids', 'excluded')):filtered[key] = [a for a in order if states[a] == state]
        filtered['complete'] = filtered['coverage_complete'] and not filtered['unknown_ids']
        return filtered

    def _promote_unknown(self, reading, ids):
        """Controller verdict (treat_as_match): these UNKNOWN records satisfy the predicates. Updates the stored reading the chooser will see."""
        for holder in (reading, self.readings.get(reading['reading'])):
            filt = holder['filter'];order = [r['record_id'] for r in holder['extraction']['records']]
            for aid in ids:filt['checks'][aid] = {'state': 'eligible', 'failed': [], 'gaps': [], 'controller_verdict': True}
            filt['unknown_ids'] = [a for a in filt['unknown_ids'] if a not in ids]
            filt['eligible_ids'] = [a for a in order if a in set(filt['eligible_ids']) | set(ids)]
            filt['complete'] = filt['coverage_complete'] and not filt['unknown_ids']

    def _excluded_values(self, reading, predicates):
        """Audit: per predicate field, the distinct strings of the EXCLUDED records (at most 8, each cut to 40 characters)."""
        rows = {r['record_id']: r['fields'] for r in reading['extraction']['records']}
        out = {}
        for name in dict.fromkeys(r['field'] for r in predicates):
            values = list(dict.fromkeys(str(rows[a][name])[:40] for a in reading['filter']['excluded_ids'] if rows[a].get(name) not in (None, '')))
            out[name] = values[:8]
        return out

    REGION_NEAR_PX = 300

    def _text_regions(self, snapshot):
        return [r for r in self.regions(snapshot).get('regions', []) if r.get('kind') == 'text' and (r.get('text') or '').strip() and r.get('bounds')]

    def _region_texts(self, regions):
        """Distinct on-screen texts with how often each is drawn (bounded): what a caller may pass as control."""
        counts = {}
        for r in regions:counts[r['text'].strip()[:40]] = counts.get(r['text'].strip()[:40], 0) + 1
        return [{'text': t, 'count': c} for t, c in sorted(counts.items())][:self.DO_LIST_CAP]

    def _region_neighbor(self, region, regions):
        """Text of the nearest text region ABOVE or LEFT of this one within REGION_NEAR_PX; None when there is none or two tie."""
        b, best = region['bounds'], []
        for other in regions:
            if other is region:continue
            o = other['bounds'];tol = 4
            x_overlap = o['x'] < b['x'] + b['width'] and b['x'] < o['x'] + o['width'];y_overlap = o['y'] < b['y'] + b['height'] and b['y'] < o['y'] + o['height']
            if o['y'] + o['height'] <= b['y'] + tol and x_overlap:best.append((b['y'] - (o['y'] + o['height']), other))
            elif o['x'] + o['width'] <= b['x'] + tol and y_overlap:best.append((b['x'] - (o['x'] + o['width']), other))
        best = sorted([(max(0, d), o['id'], o) for d, o in best if d <= self.REGION_NEAR_PX], key=lambda t: (t[0], t[1]))
        if not best or (len(best) > 1 and best[0][0] == best[1][0]):return None
        return best[0][2]['text']

    def region_exact(self, snapshot, label, goal, near=None):
        """Pixel-only pages: resolve `label` against TEXT regions exactly (normalized) and UNIQUELY, with the near-edit veto of region_corroborated
        (an OCR twin such as 'Sove' for 'Save' vetoes). Several exact matches defer unless `near` (the text of the nearest region above or left)
        picks exactly one. Capture-bound click at the region centre, as choose_regions. Returns {'status': selected|defer|none, ...}."""
        state = self.state(snapshot);capture_id = state['raw'].get('capture_id')
        regions = self._text_regions(snapshot);norm = self._ocr_normalize;want = norm(label)
        texts = self._region_texts(regions)
        exact = [r for r in regions if norm(r['text']) == want]
        if not exact:return {'status': 'none', 'region_texts': texts}
        twins = [r for r in regions if norm(r['text']) != want and len(want) >= 3 and self._within_one_edit(norm(r['text']), want)]
        if twins:
            return {'status': 'defer', 'reason': 'region_uncorroborated', 'region_texts': texts, 'twin_count': len(twins),
                    'hint': 'Another text on the screen reads almost the same as %r (an OCR-style twin), so the label cannot be trusted; nothing was clicked. Call cua_do again with near=<the text just above or left of the control> and the exact label, or stop and report it.' % label}
        neighbors = {r['id']: self._region_neighbor(r, regions) for r in exact}
        if near is not None:exact = [r for r in exact if neighbors[r['id']] is not None and norm(neighbors[r['id']]) == norm(near)]
        if len(exact) != 1:
            everyone = [r for r in regions if norm(r['text']) == want]
            matches = [{'x': int(round(r['bounds']['x'] / 50.0) * 50), 'y': int(round(r['bounds']['y'] / 50.0) * 50), 'near': (neighbors[r['id']] or '')[:40]} for r in everyone][:8]
            return {'status': 'defer', 'reason': 'region_ambiguous', 'matches': matches, 'region_texts': texts,
                    'hint': '%d text regions read %r%s; nothing was clicked. Call cua_do again with the same control and near=<the text just above or left of the one you mean> (see matches[].near).'
                            % (len(everyone), label, '' if near is None else ' and none is right beside %r' % near)}
        target = exact[0];bounds = target['bounds']
        action = {'id': target['id'], 'name': target['text'], 'role': 'perception_region:text', 'operation': 'click', 'enabled': True, 'evidence_text': target['text'],
                  'description': target['text'], 'record_basis': 'perception_layout',
                  'arguments': {'pid': state['pid'], 'window_id': state['window_id'], 'session': self.session, 'capture_id': capture_id, 'delivery_mode': 'background',
                                'target': {'kind': 'window', 'pid': state['pid'], 'window_id': state['window_id']},
                                'x': bounds.get('x', 0) + bounds.get('width', 0) / 2, 'y': bounds.get('y', 0) + bounds.get('height', 0) / 2}}
        request = {'snapshot_id': state['raw']['snapshot_id'], 'kind': 'semantic', 'operation': 'click', 'goal': goal, 'actions': [action], 'observation': target['text']}
        decision = {'status': 'selected', 'action_id': target['id'], 'action_authorized': True, 'reason': 'exact_region_label', 'snapshot_id': request['snapshot_id'],
                    'binding_digest': request_digest(request), 'provider_outputs': []}
        handle = 'sel_' + uuid.uuid4().hex
        self.selections[handle] = {'snapshot': snapshot, 'request': copy.deepcopy(request), 'decision': copy.deepcopy(decision), 'mode': 'regions', 'operation': 'click',
                                   'text': None, 'used': False, 'allow_foreground': self.foreground_ok, 'capture_id': capture_id}
        while len(self.selections) > 32:self.selections.pop(next(iter(self.selections)))
        self.event('choose', snapshot=snapshot, route='exact_region_label', mode='regions', authorized=True, reason='exact_region_label', near_used=near is not None)
        return {'status': 'selected', 'route': 'exact_region_label', 'selection': handle, 'selected_id': target['id'], 'decision': decision}

    def _do_observation(self, pid, window_id):
        handle = self.latest.get((pid, window_id));state = self.snapshots.get(handle)
        if not state:return None
        roles = {}
        for n in state['nodes'].values():roles[n.get('role')] = roles.get(n.get('role'), 0) + 1
        return {'snapshot': handle, 'title': state['raw'].get('window_title'), 'element_count': len(state['nodes']),
                'top_roles': dict(sorted(roles.items(), key=lambda kv: (-kv[1], str(kv[0])))[:6]),
                'controls': [{'id': 'e'+str(i), 'name': (n.get('label') or '')[:40]} for i, n in state['nodes'].items()
                             if i not in state['aliases'] and self._is_control(n)][:12]}

    def look(self, title=None, pid=None, window_id=None, fields=None, max_records=40, max_bytes=6000, focus=None, max_lines=6, line_chars=60):
        """Read-only, deterministic look at the strings the page displays (no click, no window move, no model unless `fields`)."""
        import look as lookmod
        with self.lock:return self.mark(lookmod.run_look(self, title, pid, window_id, fields, max_records, max_bytes, focus, max_lines, line_chars))

    def do(self, goal, title=None, pid=None, window_id=None, records=None, operation='click', text=None,
           expect=None, accept_unknown=None, budget_s=20, confirm=None, control=None, treat_as_match=None, near=None,
           steps=None, look_id=None, abort_if=None, allow_foreground=None):
        """One call runs observe -> read -> same-record filter -> (chooser only if several) -> bind -> act -> verify,
        recovering deterministically (bounded) and deferring to the caller only where guessing would be worse.
        Composes observe/read/choose/act/verify; owns no selection policy. Never retries a click.
        With `steps` it runs a validated PLAN instead (plan.py): each step is this same pipeline on a fresh observation."""
        return self.mark(self._do_entry(goal, title, pid, window_id, records, operation, text, expect, accept_unknown, budget_s, confirm, control, treat_as_match, near, steps, look_id, abort_if, allow_foreground))

    def mark(self, result):
        """Every cua_do response can carry page-derived strings (summary.text, dialog.lines, evidence, found, descriptions): say so, with the fixed sentence."""
        import look as lookmod
        if isinstance(result, dict):
            result.setdefault('untrusted_page_text', True);result.setdefault('notice', lookmod.NOTICE)
        return result

    def _do_entry(self, goal, title, pid, window_id, records, operation, text, expect, accept_unknown, budget_s, confirm, control, treat_as_match, near, steps, look_id, abort_if, allow_foreground=None):
        if steps is not None or look_id is not None or abort_if is not None:
            import plan as planmod
            with self.lock:
                if steps is None:
                    return planmod.run_plan(self, goal, title, pid, window_id, [], look_id, abort_if, budget_s, expect, {})
                return planmod.run_plan(self, goal, title, pid, window_id, steps, look_id, abort_if, budget_s, expect,
                                        {'records': records, 'operation': operation, 'text': text, 'accept_unknown': accept_unknown, 'confirm': confirm,
                                         'control': control, 'treat_as_match': treat_as_match, 'near': near})
        self.foreground_ok = allow_foreground is True
        try:
            with self.lock:return self._do(goal, title, pid, window_id, records, operation, text, expect, accept_unknown, budget_s, confirm, control, treat_as_match, near)
        finally:self.foreground_ok = False

    def _do(self, goal, title, pid, window_id, records, operation, text, expect, accept_unknown, budget_s, confirm=None, control=None, treat_as_match=None, near=None, plan=None):
        confirm_label = confirm
        lines_where = plan.get('lines_where') if plan else None  # option B: a deterministic filter over displayed lines (plan.py), never a reader call
        if plan is not None:import plan as planmod
        t0 = self.clock();ms, calls, attempts, tries, keep = {}, {}, [], {}, {}
        ctx = {'stage': 'goal', 'pid': pid, 'window_id': window_id, 'delivery': 'none', 'selection': None, 'pass': 0}
        def finish(status, **extra):
            result = {'status': status, 'stage': ctx['stage'], **extra, 'delivery': ctx['delivery'],
                      'trace_summary': {'calls_by_route': dict(calls), 'ms_by_stage': dict(ms), 'passes': ctx['pass'],
                                        'attempts': attempts[:10], 'follow_up_needed': status not in ('done', 'observed')}}
            if ctx['pid'] is not None:
                observation = self._do_observation(ctx['pid'], ctx['window_id'])
                if observation:result['observation'] = observation
            if keep.get('audit') is not None and status != 'refused':result['evidence'] = {**result.get('evidence', {}), 'excluded_values': keep['audit']}
            self.event('do', stage=ctx['stage'], status=status, delivery=ctx['delivery'], passes=ctx['pass'],
                       attempts=len(attempts), calls_by_route=dict(calls), reason=extra.get('reason'))
            return result
        DEAD_END = 'this page needs the operator to enable the advanced tools (CUA_TASK_ADVANCED=1); do not loop'
        def count(name, route):
            calls[route] = calls.get(route, 0) + 1
            self.event('do_stage', stage=name, route=route, ms=ms.get(name, 0), pass_no=ctx['pass'])
        def over():return self.clock()-t0-ms.get('act', 0)/1000-ms.get('confirm', 0)/1000 > budget_s
        def hard():return self.clock()-t0 > 3*budget_s  # click and confirm time count here: slow stages cannot run on indefinitely
        def over_all():return over() or hard()
        def remaining():return max(1.0, min(20.0, budget_s - (self.clock()-t0-ms.get('act', 0)/1000-ms.get('confirm', 0)/1000)))
        def budget(**more):
            return finish('deferred', reason='budget_exceeded', budget_exceeded=True, budget_s=budget_s, **more,
                          hint='The wall budget ran out before the next step (a hard cap of 3x budget_s counts click time too); no further step ran and nothing was clicked after it. If a click had landed, call cua_do with operation="verify" and an expect to check it; otherwise call cua_do again.')
        def transient(error):
            return isinstance(error, DriverCallFailed) or (isinstance(error, (ValueError, RuntimeError, TimeoutError, OSError)) and not isinstance(error, Gap))
        def guarded(stage, fn):
            """Retry a pre-click stage ONCE after a short bounded backoff on a transient Driver/provider failure."""
            ctx['stage'] = stage
            for n in (1, 2):
                tries[stage] = n;began = self.clock()
                try:return fn()
                except Exception as error:
                    if not transient(error) or n == 2 or over_all():raise
                    attempts.append({'pass': ctx['pass'], 'stage': stage, 'kind': 'retry_after_transient_failure', 'error_type': type(error).__name__})
                    self.sleep(self.RETRY_BACKOFF_S)
                    if over_all():raise
                finally:ms[stage] = ms.get(stage, 0) + round((self.clock()-began)*1000)
        def deliver(selection):
            """act() once. A failure BEFORE the click (selection given back) may be retried once; a click never is."""
            stage = ctx['stage']
            for n in (1, 2):
                tries[stage] = n;began = self.clock()
                try:return self.act(selection)
                except DriverCallFailed as error:
                    if self.selections[selection]['used'] or n == 2 or over_all():raise
                    attempts.append({'pass': ctx['pass'], 'stage': stage, 'kind': 'retry_before_click', 'error_type': type(error).__name__})
                    self.sleep(self.RETRY_BACKOFF_S)
                finally:ms[stage] = ms.get(stage, 0) + round((self.clock()-began)*1000)
        def deferred(payload, **more):
            keep_keys = {k: payload[k] for k in ('reason', 'hint', 'suggested_id', 'offered_count', 'excluded_count', 'missing_fields',
                                                 'eligible_ids', 'unknown_ids', 'judged_ids', 'found') if k in payload}
            for key in ('eligible_ids', 'unknown_ids', 'judged_ids'):
                if key in keep_keys:keep_keys[key + '_count'] = len(keep_keys[key]);keep_keys[key] = self._bounded(keep_keys[key])
            if 'missing_fields' in keep_keys:keep_keys['missing_fields'] = self._bounded(keep_keys['missing_fields'])
            keep_keys.setdefault('reason', (payload.get('decision') or {}).get('reason') or 'no_selection')
            if payload.get('extracted'):more['evidence'] = {**more.get('evidence', {}), 'extracted': self._bounded(payload['extracted'])}
            if keep_keys['reason'] in ('unknown_competitors_unacknowledged', 'unknown_or_incomplete_scope') and payload.get('unknown_ids'):
                more['retry_with'] = 'cua_do again with the same arguments plus accept_unknown=[ids] (they do NOT match) or treat_as_match=[ids] (they DO match)'
                keep_keys['hint'] = ('Some records could not be compared with your predicates (unknown_ids; their strings are in evidence.extracted, and evidence.excluded_values shows what the predicates threw away). '
                                     'Call cua_do again with the same arguments plus ONE of: accept_unknown=<ids> if the strings show those records do NOT match; '
                                     'treat_as_match=<ids> if you judge they DO match (for example "half-hour" means 30 minutes). Nothing was clicked.')
            return finish('deferred', **keep_keys, **more)
        def identity_of(reading, state, roots, selected):
            """What the selected record IS: its extracted strings (records mode) or its description."""
            if not reading:return None
            index = self.node(state, selected)['element_index']
            root = next(r for r in roots if index in self.subtree(state, r)[1])
            fields = next(r['fields'] for r in reading['extraction']['records'] if r['record_id'] == root)
            return {k: re.sub(r'\s+', ' ', str(v)).strip() for k, v in sorted(fields.items()) if v is not None}
        def discovery_defer(why, found):
            """Records could not be told apart without guessing: defer with what the caller needs (shared by the reader and the lines-where paths)."""
            # Page text (control labels) lives ONLY in `found`; a hint is fixed text plus the caller's own words, never page text.
            hints = {'control_needed': 'Each record has several controls (found.repeated_controls lists their labels). Call cua_do again with control=<the exact label of the one to press>.',
                     'control_not_found': 'No control matches control=%r (found.controls lists what is pressable). Call cua_do again with control set to one of them, or without records and a goal that quotes the exact label.' % (control,),
                     'control_ambiguous': 'Several controls match control=%r in a record; nothing was guessed. Call cua_do again with control set to the exact full label, or without records and a goal that quotes the exact label of the control (see found.controls).' % (control,),
                     'records_ambiguous': 'Could not tell which controls are records (found.controls lists them). Call cua_do again WITHOUT records and with a goal that quotes the exact label of the control to press, or pass control=<exact label>. Nothing was guessed or clicked.',
                     'no_controls': 'No enabled control was found in the page content, so there is nothing cua_do can press here; nothing was clicked.'}
            dead = {'dead_end': True, 'report_to_user': DEAD_END} if why == 'no_controls' else {}
            return finish('deferred', reason='records_ambiguous' if why == 'no_controls' else why, found=found, hint=hints[why], **dead,
                          **({'retry_with': 'cua_do again with control=<one of found.repeated_controls labels>'} if why == 'control_needed' else {}))
        def confirm_step_check(state):
            """An explicit confirm step (plan.py): the dialog the PREVIOUS press opened, checked before anything is clicked. Deferred unless it is
            the only new dialog, displays EVERY string of the selected record's identity, and holds exactly one control labelled exactly as asked."""
            cs = plan['confirm_step'];nodes = state['nodes'];ctx['stage'] = 'confirm'
            norm = lambda v: re.sub(r'\s+', ' ', str(v or '').strip()).casefold()
            if cs['before'] is None:return finish('deferred', reason='confirm_dialog_not_found', verified=False)
            new_controls, dialog_text, ambiguous = self._new_dialog(state, cs['before'])
            if ambiguous:return finish('deferred', reason='confirm_dialog_ambiguous', verified=False)
            if not new_controls:return finish('deferred', reason='confirm_dialog_not_found', verified=False)
            labels = self._bounded([(nodes[i].get('label') or '')[:40] for i in new_controls])
            # POSITIVE AUTHORIZATION: the caller declared the dialog's COMPLETE text; every actual line must be declared and every declared line present.
            # No word list (negations, verbs, languages) decides intent: whether the caller declared exactly this text does.
            import look as lookmod
            region_lines, region_controls = lookmod.region_items(self, state, self._dialog_region(state, cs['before']))
            actual_lines, actual_controls = region_lines, region_controls
            dialog_text = '\n'.join(actual_lines)  # the identity sanity check reads the whole region, not only static texts
            shown_lines = [l[:80] for l in actual_lines[:12]]
            if {norm(x) for x in cs['dialog_text']} != {norm(x) for x in actual_lines} or {norm(x) for x in cs['dialog_controls']} != {norm(x) for x in actual_controls}:
                return finish('deferred', reason='confirm_dialog_unexpected_text', dialog={'controls': [c[:60] for c in actual_controls[:12]], 'identity': 'not_checked', 'lines': shown_lines,
                              'declared_lines': len(cs['dialog_text']), 'actual_lines': len(actual_lines), 'declared_controls': len(cs['dialog_controls']), 'actual_controls': len(actual_controls)}, verified=False)
            if not cs['identity']:return finish('deferred', reason='confirm_needs_identity', dialog={'controls': labels, 'identity': 'not_checked', 'lines': shown_lines}, verified=False)
            verdict, shown, missing = planmod.identity_state(dialog_text, cs['identity'])
            held = {'dialog': {'controls': labels, 'identity': verdict, 'lines': shown_lines}, 'verified': False}
            if verdict == 'partial':return finish('deferred', reason='confirm_identity_partial', **held, identity_shown=len(shown), identity_not_shown=len(missing))
            if verdict != 'matched':return finish('deferred', reason='confirm_identity_unknown', **held)
            hits = [i for i in new_controls if norm(nodes[i].get('label')) == norm(cs['label'])]
            if len(hits) != 1:return finish('deferred', reason='confirm_control_not_found' if not hits else 'confirm_dialog_ambiguous', **held)
            plan['confirm_new'] = set(new_controls)
            return None
        def attempt():
            ctx['pass'] += 1
            pid_, window_ = ctx['pid'], ctx['window_id']
            snapshot = guarded('observe', lambda: self.observe(pid_, window_, timeout=remaining()))['snapshot'];state = self.state(snapshot)
            count('observe', 'cua-driver')
            self.reject_answer_leak(state, goal)
            if over_all():return budget()
            webs = self._top_web_areas(state)
            if len(webs) > 1:
                return finish('deferred', reason='web_area_ambiguous', found={'web_areas': len(webs)},
                              hint='The window holds %d separate page areas (for example a browser extension popup beside the page); nothing was clicked. Close the extra one, or give the exact title of the window that holds only the page, and call cua_do again.' % len(webs))
            if operation == 'verify':return verify_only(state)
            reading, pick, roots = None, {}, []
            if plan and plan.get('confirm_step'):
                early = confirm_step_check(state)
                if early:return early
            if lines_where:
                ctx['stage'] = 'read'
                roots, targets, found, why, disabled_roots = self.discover_records(state, operation, control)
                if roots is None:return discovery_defer(why, found)
                outcome = planmod.lines_stage(self, state, snapshot, lines_where, roots, targets, disabled_roots)
                count('read', 'deterministic_lines')
                if 'defer' in outcome:return finish('deferred', **outcome['defer'])
                reading, pick = outcome['reading'], outcome['pick']
            elif spec:
                fields, predicates, supplied, coverage, _ = spec
                ctx['stage'] = 'read'
                norm = lambda v: re.sub(r'\s+', ' ', str(v or '').strip()).casefold()
                if supplied:
                    roots, targets, found = list(supplied), {}, {}
                    if control is not None:
                        for root in roots:
                            members = self.subtree(state, root)[1]
                            named = [i for i in sorted(members) if i not in state['aliases'] and self._is_control(state['nodes'][i]) and self._operation_compatible(state['nodes'][i], operation)
                                     and norm(state['nodes'][i].get('label')) == norm(control)]
                            if len(named) != 1:
                                return finish('deferred', reason='control_not_found' if not named else 'control_ambiguous', record=root,
                                              hint='control=%r must match exactly one enabled control inside each record; nothing was clicked.' % control)
                            targets[root] = 'e'+str(named[0])
                else:
                    roots, targets, found, why, disabled_roots = self.discover_records(state, operation, control);coverage = True
                    if roots is None:return discovery_defer(why, found)
                def read_once():
                    try:return self.read(snapshot, goal, fields, roots, predicates, coverage, flat_by_role=True, shape_guard=True)
                    except Gap as gap:
                        if str(gap).startswith(('Overlapping', 'Record has no observed text')):raise self._Ambiguous(str(gap))
                        raise
                reading = guarded('read', read_once);count('read', 'nuextract3')
                if reading['filter']['unknown_ids'] and not accept_unknown and not treat_as_match and not over_all():
                    # An unknown/garbled field: ONE re-read (READ_BUDGET caps it at 2), then stop and defer with the strings.
                    attempts.append({'pass': ctx['pass'], 'stage': 'read', 'kind': 'reread_unknown_field'})
                    reading = guarded('read', read_once);count('read', 'nuextract3')
                if over_all():return budget()
                ctx['stage'] = 'filter';filt = reading['filter']
                if treat_as_match:
                    stray = [r for r in treat_as_match if r not in filt['unknown_ids']]
                    if stray:
                        keep['audit'] = self._excluded_values(reading, predicates)
                        return finish('refused', reason='treat_as_match_invalid', stray_ids=self._bounded(stray), unknown_ids=self._bounded(filt['unknown_ids']),
                                      message='treat_as_match may name only records this reading left UNKNOWN (never excluded or unknown-to-this-page ids).',
                                      hint='Call cua_do again with treat_as_match limited to unknown_ids from this response.')
                    self._promote_unknown(reading, list(treat_as_match));keep['treated'] = list(treat_as_match)
                keep['audit'] = self._excluded_values(reading, predicates)
                if not filt['eligible_ids']:
                    if filt['unknown_ids']:return deferred(self.incomplete_scope_defer(filt, reading))
                    return finish('deferred', reason='no_eligible_record', excluded_count=len(filt['excluded_ids']),
                                  evidence={'extracted': self._bounded({r['record_id']: r['fields'] for r in reading['extraction']['records']})},
                                  hint='No record satisfies the predicates (the strings read from the records are in evidence); nothing was clicked. Call cua_do again with corrected fields/predicates.')
                # The judged path (record_actions/candidate_ids) skips the coverage gate, so it is used only when
                # coverage is guaranteed (discovered) or the caller names the unknowns it excludes (accept_unknown).
                if supplied and targets and not accept_unknown and not filt['complete']:return deferred(self.incomplete_scope_defer(filt, reading))
                if not supplied:
                    blocked = [r for r in filt['eligible_ids'] if r in disabled_roots]
                    if blocked:
                        return finish('deferred', reason='record_disabled', disabled_count=len(blocked),
                                      hint='%d record(s) that match are disabled, so their control cannot be pressed; nothing was clicked. Report that the item is unavailable, or call cua_do again with different predicates.' % len(blocked))
                    missing = [r for r in filt['eligible_ids'] if r not in targets]
                    if missing:
                        return finish('deferred', reason='control_not_found', missing_count=len(missing), found=found,
                                      hint='A matching record has no control labelled %r (found.controls lists what is pressable); nothing was clicked. Call cua_do again with control set to an exact label.' % (control,))
                if targets:pick = {'record_actions': {r: targets[r] for r in filt['eligible_ids']}}
                elif accept_unknown:pick = {'candidate_ids': list(filt['eligible_ids'])}
            mode = 'semantic';region_choice = None
            choose_args = dict(operation=operation, text=text)
            if reading:choose_args.update(reading=reading['reading'], accept_unknown=list(accept_unknown or []) or None, **pick)
            else:
                norm = lambda v: re.sub(r'\s+', ' ', str(v or '').strip()).casefold()
                tokens = self.quoted_tokens(goal)
                label = control if control is not None else (tokens[0] if len(tokens) == 1 else None)
                def pool(st):
                    # click: real page controls only (Chrome advertises AXPress on static text; its menu bar is chrome); type_text: any compatible field
                    content = self._content_ids(st) - self._column_copies(st)
                    return [i for i, n in st['nodes'].items() if i in content and i not in st['aliases'] and n.get('enabled') is not False
                            and (self._is_control(n) if operation == 'click' else True)]
                def named(st):
                    ids = [i for i in pool(st) if label is not None and norm(st['nodes'][i].get('label')) == norm(label)]
                    if not ids and control is not None:ids = [i for i in pool(st) if self._label_matches(control, st['nodes'][i].get('label') or '')]
                    return ids, [i for i in ids if self._operation_compatible(st['nodes'][i], operation)]
                offered = [i for i in pool(state) if self._operation_compatible(state['nodes'][i], operation)]
                if label is not None:
                    any_named, same = named(state)
                    if any_named and not same:
                        # Chrome can omit the press action on a fresh read: reobserve ONCE before concluding anything.
                        attempts.append({'pass': ctx['pass'], 'stage': 'choose', 'kind': 'reobserve_unpressable_control'})
                        self.sleep(self.RETRY_BACKOFF_S)
                        snapshot = guarded('observe', lambda: self.observe(pid_, window_, timeout=remaining()))['snapshot'];state = self.state(snapshot);count('observe', 'cua-driver')
                        any_named, same = named(state);offered = [i for i in pool(state) if self._operation_compatible(state['nodes'][i], operation)]
                    listing = self._bounded(sorted({state['nodes'][i].get('label') or '' for i in offered}))
                    fallback = None
                    if not any_named and operation == 'click' and self.perception_state == 'healthy' and state['raw'].get('capture_id'):
                        try:fallback = self.region_exact(snapshot, label, goal, near)
                        except Gap:fallback = None
                        if fallback and fallback['status'] == 'selected':region_choice = fallback;mode = 'region_exact'
                        elif fallback and fallback['status'] == 'defer':
                            self.event('choose', snapshot=snapshot, route='exact_region_label', mode='regions', authorized=False, reason=fallback['reason'])
                            return finish('deferred', **{k: v for k, v in fallback.items() if k != 'status'})
                    if mode != 'region_exact' and (any_named and not same or (control is not None and len(same) != 1)):
                        # Never claim a control is unique (or absent) when it is merely not press-capable in this snapshot.
                        why = 'control_not_found' if not any_named else ('control_not_pressable' if not same else 'control_ambiguous')
                        no_help = not listing and not (fallback and fallback.get('region_texts'))
                        return finish('deferred', reason=why, found={'controls': listing, **({'region_texts': fallback['region_texts']} if fallback and fallback.get('region_texts') else {})}, control_count=len(same),
                                      **({'dead_end': True, 'report_to_user': DEAD_END} if no_help else {}),
                                      hint='%r matched %d pressable controls (labels seen in found.controls; %d present but not press-capable); nothing was clicked. Call cua_do again with an exact control label.' % (label, len(same), len(any_named) - len(same)))
                    if plan and plan.get('confirm_new') is not None and mode != 'region_exact' and len(same) == 1 and same[0] not in plan['confirm_new']:
                        return finish('deferred', reason='confirm_control_not_found', verified=False)  # the label exists, but not inside the dialog the previous step opened
                    if len(same) == 1:
                        node = state['nodes'][same[0]];mode = 'exact';choose_args.update(exact_name=node.get('label'), exact_role=node.get('role'))
                if mode == 'semantic':
                    if offered:choose_args.update(candidate_ids=['e'+str(i) for i in offered])
                    else:
                        seen_texts = []
                        if operation == 'click' and self.perception_state == 'healthy' and state['raw'].get('capture_id'):
                            try:seen_texts = self._region_texts(self._text_regions(snapshot))
                            except Gap:seen_texts = []
                        if seen_texts:
                            return finish('deferred', reason='region_label_needed', found={'region_texts': seen_texts},
                                          hint='This page has no pressable controls, but text is drawn on it (found.region_texts). Call cua_do again with control=<the exact text of the button as drawn>; if that text appears more than once (count above 1), also pass near=<the text just above or left of the one you mean>.')
                        return finish('deferred', reason='no_actionable_controls', dead_end=True, report_to_user=DEAD_END,
                                       hint='No enabled, press-capable control was found in the page content, so no cua_do parameter can move forward; nothing was clicked. Stop and report this to the user; do not retry.')
            def choose_once():
                made = self.choose(snapshot, goal, mode=mode, **choose_args)
                # The dispatcher turns a chooser transport failure into a defer; that is a failed call, not a judgment.
                if 'selection' not in made and (made.get('decision') or {}).get('reason') == 'provider_failed':raise RuntimeError('chooser provider_failed')
                return made
            choice = region_choice or guarded('choose', choose_once)
            count('choose', 'exact_observed_control' if mode == 'exact' else (choice['route'] if isinstance(choice.get('route'), str) else 'chooser'))
            if 'selection' not in choice:return deferred({**choice, 'reason': choice.get('reason') or (choice.get('decision') or {}).get('reason')})
            if over_all():
                self.selections.pop(choice.get('selection'), None)  # bound but never delivered: leave no usable authority behind
                return budget()
            selection = choice['selection'];ctx['selection'] = selection
            item = self.selections[selection]
            action = next(a for a in item['request']['actions'] if a['id'] == choice['selected_id'])
            judgment = choice.get('judgment') if choice.get('route') == 'grounded_singleton' else ('exact' if mode in ('exact', 'region_exact') else 'chooser')
            if keep.get('treated') and reading:
                index = self.node(state, choice['selected_id'])['element_index']
                if any(index in self.subtree(state, r)[1] for r in keep['treated']):judgment = 'controller'  # the controller's verdict put this record in play
            picked = {'id': choice['selected_id'], 'description': action['description'][:120]}
            if plan is not None and operation != 'verify':
                sid_ = choice['selected_id']
                node = state['nodes'].get(int(sid_[1:]), {}) if isinstance(sid_, str) and sid_[:1] == 'e' and sid_[1:].isdigit() else {}  # a pixel region is no AX control
                if node.get('role') in planmod.lk.TOGGLE_ROLES or 'checked' in node or 'selected' in node:
                    # A toggle presses to the OPPOSITE of its current state: only against a look that saw that state, and unchanged since.
                    seen = self.looks.get((ctx['pid'], ctx['window_id'], plan.get('look_id'))) if plan.get('look_id') else None
                    why = 'toggle_state_unseen' if seen is None else (None if planmod.look_matches(self, state, seen, plan['look_id'])[0] else 'page_changed_since_look')
                    if why:
                        self.selections.pop(selection, None)
                        return finish('deferred', reason=why, verified=False)
                # The destructive-verb guard on the RESOLVED control (a whole-word prefix such as "Cancel" can resolve to "Cancel and delete account").
                bad = planmod.destructive_verbs(action.get('name') or '')
                if bad and not planmod.allowed(plan.get('allow'), action.get('name') or ''):
                    self.selections.pop(selection, None)
                    return finish('deferred', reason='destructive_control', selected=picked, verified=False)
            identity = identity_of(reading, state, roots, choice['selected_id']) if reading else {'description': action['description']}
            keep['picked_identity'] = identity if reading else None
            fold = lambda d: {k: v.casefold() for k, v in d.items()}
            def recoverable(picked_identity):
                # A record can be found again by its fields only if ALL requested fields were read and no other record shows the same ones.
                if not reading:return True
                complete = len(picked_identity) == len(spec[0]) and all(picked_identity.values())
                twins = sum(1 for r in reading['extraction']['records'] if fold({k: re.sub(r'\s+', ' ', str(v)).strip() for k, v in r['fields'].items() if v is not None}) == fold(picked_identity))
                return complete and twins == 1
            if 'identity' in keep and not recoverable(identity):
                self.selections.pop(selection, None)
                return finish('deferred', reason='record_changed_unverifiable', selected=picked, hint='The record cannot be identified by its fields (a field is missing or two records read the same); nothing was clicked again.')
            if 'identity' in keep and fold(keep['identity']) != fold(identity):
                # Recovery re-ran the whole pipeline and it picked a different record: a real change (case C).
                self.selections.pop(selection, None)
                return finish('deferred', reason='record_changed', selected=picked, hint='After a stale-UI refusal the fresh pipeline selects a different record than before; nothing was clicked. Re-state the goal against the new content.')
            ctx['stage'] = 'act'
            if plan is not None:
                plan['out']['before'] = state  # the observation this click was chosen on: a following confirm step diffs the dialog against it
                if lines_where:plan['out']['identity_strings'] = list(lines_where['identity'])
                elif reading:
                    values = [identity.get(k) for k in spec[4]];plan['out']['identity_strings'] = values if all(values) else None
            try:deliver(selection)
            except StaleUI as gap:
                if not recoverable(identity):
                    return finish('deferred', reason='record_changed_unverifiable', selected=picked,
                                  hint='The UI changed before the click and the selected record cannot be re-identified by its fields (a field is missing or two records read the same); nothing was clicked. Re-state the goal.')
                keep['identity'] = identity
                attempts.append({'pass': ctx['pass'], 'stage': 'act', 'kind': 'stale_ui', 'recovery': 'reobserve_and_rerun_pipeline' if ctx['pass'] < 2 else 'exhausted'})
                return self.STALE
            finally:count('act', 'cua-driver')
            ctx['delivery'] = 'delivered'
            return after_click(state, reading, roots, picked, judgment, goal_fields=spec)
        def observe_state():
            began = self.clock()
            handle = self.observe(ctx['pid'], ctx['window_id'], timeout=remaining())['snapshot']
            ms['verify'] = ms.get('verify', 0) + round((self.clock()-began)*1000)
            return self.state(handle)
        def check_outcome(current, before, target, typed, base):
            """(verification, early). AX text in exactly one non-control node; unproven presence never escalates; then Perception, then the screenshot model."""
            check = self._expect_check(current, before, expect, target, typed) if expect else None
            if check and check['status'] == 'satisfied':return check, None
            if check and check.get('unproven'):
                # Presence that was already there, the typed text echoed back, or a control's own label proves nothing, and no presence-based step can prove it either.
                return {k: v for k, v in check.items() if k != 'unproven'}, None
            if not expect:return {'status': 'unverified', 'route': 'none', 'reason': 'expect_not_given'}, None
            if over_all():return None, budget(**base)
            # Deterministic escalation, all server-side and never through a check that counts control labels: Perception exact-presence (never on digits), then the screenshot model.
            seen = self._escalate(current, expect, remaining())
            why = (check or {}).get('reason')
            return {**seen, **({'reason': why} if why else {}), **({'present_before': check['present_before']} if check else {})}, None
        def verify_only(state):
            ctx['stage'] = 'verify'
            try:verification, early = check_outcome(state, None, None, None, {'verified': False})
            except (Gap, ValueError, RuntimeError, TimeoutError, OSError) as error:
                verification, early = {'status': 'unknown', 'route': 'verify_error', 'error_type': type(error).__name__}, None
            if early:return early
            count('verify', verification['route'])
            if verification['status'] == 'satisfied':
                # No before-state exists, so this can only be a presence check: never `done`.
                return finish('observed', reason='presence_only', verification={**verification, 'present_before': 'unknown'}, verified=False,
                              hint='The text is visible now, but a verify-only look has no before-state: it cannot tell whether it was already there. It proves presence, not that an action worked.')
            return finish('deferred', reason='not_verified', verification=verification, verified=False,
                          hint='The text was not established in the current window (control labels never count). Nothing was clicked. Call cua_do with operation="verify" and a different expect, or report what you can see in observation.controls.')
        def after_click(before, reading, roots, picked, judgment, goal_fields):
            ctx['stage'] = 'verify';began = self.clock()
            base = {'selected': picked, 'judgment': judgment, 'verified': False}
            if over_all():return budget(**base)
            confirmation = None
            try:
                current = observe_state()
                target = self.node(before, picked['id']) if operation == 'type_text' and picked['id'] in {'e'+str(i) for i in before['nodes']} else None
                typed = text if operation == 'type_text' else None
                # expect FIRST: new text that satisfies it (a success toast, even with an Undo button) is the outcome; dialog detection is skipped.
                proven = expect and self._expect_check(current, before, expect, target, typed)['status'] == 'satisfied'
                new_controls, dialog_text, ambiguous = ([], '', False) if proven else self._new_dialog(current, before)
                if new_controls or ambiguous:
                    early, confirmation = confirm(current, before, new_controls, dialog_text, ambiguous, reading, goal_fields, picked)
                    if early:return early
                    if over_all():return budget(**base)
                    ctx['stage'] = 'verify'  # the confirm click landed: a failure from here on is a verification failure, not a dialog failure
                    current = observe_state()
                verification, early = check_outcome(current, before, target, typed, base)
                if early:return early
            except (Gap, ValueError, RuntimeError, TimeoutError, OSError) as error:
                if ctx['stage'] == 'confirm':
                    if isinstance(error, DriverCallFailed):raise
                    return finish('deferred', reason='confirm_error', error_type=type(error).__name__, **base,
                                  hint='The dialog could not be handled; the first click was delivered and nothing further was clicked. Call cua_do with operation="verify" and an expect to check the outcome.')
                verification = {'status': 'unknown', 'route': 'verify_error', 'error_type': type(error).__name__}
            ms['verify'] = ms.get('verify', 0) + round((self.clock()-began)*1000);count('verify', verification['route'])
            extra = {'selected': picked, 'judgment': judgment, 'verification': verification,
                     **({'confirmation': confirmation} if confirmation else {}),
                     **({'evidence': {'eligible': len(reading['filter']['eligible_ids']), 'excluded': len(reading['filter']['excluded_ids']),
                                      'unknown': len(reading['filter']['unknown_ids'])}} if reading else {})}
            if verification['status'] == 'satisfied':return finish('done', **extra, verified=True)
            if not expect:
                return finish('delivered_unverified', reason='expect_not_given', verified=False, **extra,
                              hint='The click was delivered but no expect was given, so nothing was checked. Do not click again. To check, call cua_do with operation="verify" and expect=<text that should now be visible>.')
            # (A) a click that may have been delivered and could not be verified: the caller decides; never a re-click.
            return finish('deferred', reason='delivery_unverified', verified=False, **extra,
                          hint='The click was delivered but the outcome could not be verified. Do not click again blindly. To re-check without clicking, call cua_do with operation="verify" and an expect that is visible page text (never a button label; see observation.controls for the buttons).')
        def confirm(current, before, new_controls, dialog_text, ambiguous, reading, fields_spec, picked):
            """A dialog after the first click. The goal never authorized pressing anything in it, so confirming is OPT-IN:
            only with `confirm` (an exact control label), a COMPLETE displayed-identity match with the selected record (S4.2 s7),
            and exactly ONE enabled control in the new dialog region with that label. Never the chooser, never a lone control by default."""
            ctx['stage'] = 'confirm';snapshot = next(h for h, s in self.snapshots.items() if s is current)
            if ambiguous:
                return finish('deferred', reason='confirm_dialog_ambiguous', selected=picked, verified=False,
                              hint='A dialog was already open, was replaced, or several appeared; the first click is done and nothing further was clicked. Call cua_do with operation="verify" and an expect, or act deliberately with a fresh goal.'), None
            nodes = current['nodes']
            labels = self._bounded([(nodes[i].get('label') or '')[:40] for i in new_controls])
            fields = fields_spec[0] if fields_spec else {}
            ident_fields = fields_spec[4] if fields_spec else []
            identity = keep.get('picked_identity') or {}
            comparable = {k: identity.get(k) for k in ident_fields}
            norm = lambda v: re.sub(r'\s+', ' ', str(v or '').strip()).casefold()
            state, extracted, shown, not_shown = 'not_checked' if not reading else 'unknown', None, [], list(ident_fields)
            if lines_where:
                # Deterministic: every identity string of the plan must be displayed by the dialog (no reader call).
                if dialog_text:state, shown, not_shown = planmod.identity_state(dialog_text, lines_where['identity'])
            elif reading and comparable and all(comparable.values()) and dialog_text:
                # The dialog's displayed text is only the NEW region text: the page's own rows can never vouch for the dialog.
                sid = current['raw']['snapshot_id'];specs = {k: {**fields[k], 'type': 'text'} for k in ident_fields}
                extraction = self.provider('reader').extract({'snapshot_id': sid, 'task': goal, 'fields': {k: v['description'] for k, v in specs.items()},
                                                              'records': [{'id': 'dialog', 'text': dialog_text}]}, sid)
                calls['nuextract3'] = calls.get('nuextract3', 0) + 1
                filt = filter_records(extraction, fields=specs, predicates=[{'field': k, 'op': 'eq', 'value': v} for k, v in comparable.items()],
                                      coverage_complete=True, current_snapshot=sid)
                got = extraction['records'][0]['fields'];extracted = self._bounded({'dialog': got})
                shown = [k for k in ident_fields if got.get(k) not in (None, '')];not_shown = [k for k in ident_fields if k not in shown]
                differs = [k for k in shown if norm(got[k]) != norm(comparable[k])]
                state = 'matched' if filt['eligible_ids'] else ('mismatch' if differs else ('partial' if shown else 'unknown'))
            held = {'selected': picked, 'verified': False, 'dialog': {'controls': labels, 'identity': state}, **({'evidence': {'extracted': extracted}} if extracted else {})}
            # The wall budget binds the confirm step too: a slow dialog read must not be followed by a second click.
            if over_all():return budget(selected=picked, verified=False), None
            if not confirm_label:
                return finish('deferred', reason='confirm_dialog_present', **held,
                              next_call={'goal': 'Click "<one of dialog.controls, exact label>"', 'expect': '<text that will appear once it is done>'},
                              hint='The first click is done: do not repeat this goal. A dialog is showing and nothing in it was pressed. To press one of dialog.controls, call cua_do again '
                                   'with a goal that quotes its exact label (that call does not re-click the first control) and an expect. To have this goal press it on its own, '
                                   'pass confirm=<exact control label>.'), None
            if not reading:return finish('deferred', reason='confirm_dialog_needs_identity', **held), None
            if state == 'partial':
                return finish('deferred', reason='confirm_identity_partial', **held, identity_shown=shown, identity_not_shown=not_shown,
                              hint='The dialog shows only part of the record identity (shown: %s; not shown: %s); nothing further was clicked. The first click is done: do not repeat this goal. If you judge it is the right dialog, '
                                   'call cua_do again with a goal that quotes one of dialog.controls and an expect. Next time pass records.identity=%s so that confirm=<label> can press it on its own.'
                                   % (', '.join(shown), ', '.join(not_shown), json.dumps(shown))), None
            if state != 'matched':
                return finish('deferred', reason='confirm_identity_mismatch' if state == 'mismatch' else 'confirm_identity_unknown', **held,
                              hint='The dialog does not display the identity of the selected record (fields %s); nothing further was clicked. Press it deliberately with a fresh cua_do that quotes its label.' % ', '.join(ident_fields)), None
            hits = [i for i in new_controls if norm(nodes[i].get('label')) == norm(confirm_label)]
            if len(hits) != 1:
                return finish('deferred', reason='confirm_control_not_found' if not hits else 'confirm_dialog_ambiguous', **held), None
            if 'AXPress' not in nodes[hits[0]].get('actions', []):
                # Chrome can omit the press action on the first read of fresh content: reobserve ONCE, never click blind.
                attempts.append({'pass': ctx['pass'], 'stage': 'confirm', 'kind': 'reobserve_unpressable_control'})
                self.sleep(self.RETRY_BACKOFF_S)
                current = observe_state();snapshot = next(h for h, s in self.snapshots.items() if s is current);nodes = current['nodes']
                new_controls, _, ambiguous = self._new_dialog(current, before)
                hits = [i for i in new_controls if norm(nodes[i].get('label')) == norm(confirm_label)]
                if ambiguous or len(hits) != 1:return finish('deferred', reason='confirm_dialog_ambiguous', **held), None
                if 'AXPress' not in nodes[hits[0]].get('actions', []):
                    return finish('deferred', reason='control_not_pressable', **held,
                                  hint='The dialog control is present but the Driver does not advertise a press action for it; nothing was clicked. Call cua_do again with a goal quoting its label.'), None
            choice = self.choose(snapshot, goal, mode='exact', exact_name=nodes[hits[0]].get('label'), exact_role=nodes[hits[0]].get('role'), operation='click')
            count('confirm', 'exact_observed_control')
            if 'selection' not in choice:return deferred({**choice, 'reason': choice.get('reason') or 'confirm_unselected'}, **held), None
            ctx['selection'] = choice['selection']
            if over_all():
                self.selections.pop(choice['selection'], None);ctx['selection'] = None
                return budget(selected=picked, verified=False), None
            try:deliver(choice['selection'])
            except StaleUI:return finish('deferred', reason='confirm_ui_changed', **held, hint='The dialog changed before it was confirmed; the first click was delivered. Call cua_do with operation="verify" and an expect to check the outcome.'), None
            finally:count('confirm_click', 'cua-driver')
            return None, {'status': 'confirmed', 'identity': 'matched', 'selected_id': choice['selected_id']}
        try:
            if not isinstance(goal, str) or not goal.strip():raise Gap('bad_request: goal is required')
            # Before any Driver/provider call: observed IDs are unknowable yet, so ANY element-ID token is a leak.
            self.reject_answer_leak({'nodes': {int(m): 0 for m in self.OBSERVED_ID.findall(goal)}}, goal)
            if operation not in ('click', 'type_text', 'verify'):raise Gap('bad_request: operation must be click, type_text or verify')
            if operation == 'verify' and (expect is None or records is not None or control is not None):raise Gap('bad_request: operation verify needs expect (and takes no records or control); it never clicks')
            if control is not None and (not isinstance(control, str) or not control.strip()):raise Gap('bad_request: control must be the exact label of the control to press')
            if operation == 'type_text' and text is None:raise Gap('bad_request: type_text requires text')
            if confirm_label is not None and (not isinstance(confirm_label, str) or not confirm_label.strip()):raise Gap('bad_request: confirm must be the exact label of a dialog control')
            if expect is not None and (not isinstance(expect, str) or not expect.strip()):raise Gap('bad_request: expect must be nonempty text')
            if not isinstance(budget_s, (int, float)) or isinstance(budget_s, bool) or budget_s <= 0:raise Gap('bad_request: budget_s must be positive seconds')
            spec = self._do_records(records) if records is not None else None
            if lines_where:
                if records is not None:raise Gap('bad_request: a step filters by where.lines or where.fields, not both')
                spec = ({'lines': {'description': 'the displayed lines of the record'}}, [], None, True, ['lines'])
            ctx['stage'] = 'window';began = self.clock()
            if title is not None:
                if pid is not None or window_id is not None:raise Gap('bad_request: give title or pid+window_id, not both')
                found = guarded('window', lambda: self.windows(title))['windows']
                if len(found) != 1:
                    raise Gap('window_%s: %d windows match the exact title; check the exact window title' % ('not_found' if not found else 'ambiguous', len(found)))
                ctx.update(pid=found[0]['pid'], window_id=found[0]['window_id'])
            elif pid is None or window_id is None:raise Gap('bad_request: supply title, or pid and window_id')
            count('window', 'driver_inventory')
            if plan is not None:plan['pid'], plan['window_id'] = ctx['pid'], ctx['window_id']
            if lines_where:
                lines_where['look'] = self.looks.get((ctx['pid'], ctx['window_id'], lines_where['look_id']))
                if lines_where['look'] is None:
                    raise Gap('look_window_mismatch: no cua_look of THIS window returned that look_id; call cua_look on this window and use its look_id')
            for _ in (1, 2):
                result = attempt()
                if result is not self.STALE:return result
                # Stale UI refused BEFORE any click: never reuse that selection or its tokens (S4.3); reobserve and re-run everything.
                if ctx['pass'] == 2:
                    return finish('deferred', reason='ui_changed_repeatedly', hint='The content changed again during the second pass; nothing was clicked. Re-state the goal against the current observation.')
                if over():return budget()
            return budget()
        except DriverCallFailed as gap:
            item = self.selections.get(ctx['selection']) if ctx['selection'] else None
            # Once ANY click was delivered nothing may be handed back: a returned selection could click a dialog the goal never authorized.
            given_back = bool(item) and not item['used'] and ctx['delivery'] == 'none'
            if ctx['delivery'] != 'none' and ctx['selection']:self.selections.pop(ctx['selection'], None)
            if ctx['stage'] in ('act', 'confirm') and not given_back and ctx['delivery'] == 'none':ctx['delivery'] = 'uncertain'
            return finish('failed', reason='driver_call_failed', message='driver_call_failed: a Driver call failed; delivery and retryable say whether anything may have been clicked', attempts=tries.get(ctx['stage'], 1),
                          retryable=ctx['delivery'] == 'none', **({'selection': ctx['selection']} if given_back else {}))
        except self._Ambiguous as gap:
            return finish('deferred', reason='records_ambiguous', message=str(gap))
        except Gap as gap:
            import look as lookmod
            return finish('refused', reason=self._do_reason(str(gap)), message=lookmod.safe_message(self._do_reason(str(gap)), str(gap)))
        except (ValueError, RuntimeError, TimeoutError, OSError) as error:
            return finish('failed', reason='provider_failure', error_type=type(error).__name__, attempts=tries.get(ctx['stage'], 1),
                          retryable=ctx['delivery'] == 'none')

    def close(self):
        for provider in self.providers.values():
            try:provider.close()
            except Exception:self.event('cleanup',status='worker_close_failed')
        self.providers.clear()
        self.snapshots.clear();self.selections.clear();self.readings.clear();self.latest.clear();self.looks.clear()
        return {'status':'closed','trace':self.events,'driver_version':self.driver_version,'driver_version_state':self.driver_version_state,
                'perception_version':self.perception_version,'perception_state':self.perception_state}
