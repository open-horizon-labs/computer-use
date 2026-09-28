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
from dispatch import Engine, execute_bound, request_digest
from page_candidates import NuExtractPage, filter_records
from providers import generic_from_config, RemoteSpans
from rollout import Strangler
from terminal_observation import VisualTerminal
from ax_aliases import table_aliases


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

    def observe(self, pid, window_id, timeout=None):
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
        descendants = {root}
        for _ in range(len(state['nodes'])):
            more = {i for i,n in state['nodes'].items() if n.get('parent_index') in descendants}
            if more <= descendants:
                break
            descendants |= more
        text = []
        for i,n in state['nodes'].items():
            if i in descendants:
                for key in ('label','value'):
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

    def sibling_record(self, state, index):
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
        texts = []
        for i in members:
            text, _ = self.subtree(state, 'e'+str(i))
            texts += [line for line in text.split('\n') if line and line not in texts]
        return (texts, set(members) | {index}) if texts else None

    READ_BUDGET = 2  # readings per (snapshot, record scope); S4.2 §7 bounds steps, S4.8 forbids re-read loops

    def read(self, snapshot, task, fields, record_ids, predicates=None, coverage_complete=False):
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
                inferred = self.sibling_record(state, root)
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
                                     'mode':'regions','operation':operation,'text':None,'used':False,'capture_id':capture_id}
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
        return digest({'title':state['raw'].get('window_title'),'address':address,
                       'nodes':[{k:v for k,v in state['nodes'][i].items() if k!='element_token'} for i in sorted(members)]})

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
        return fields, predicates, supplied, records.get('coverage_complete') is True

    def _record_root(self, state, index):
        """Outermost ancestor still holding exactly one control of this kind (as record_context)."""
        kind = lambda n: (n.get('role'), n.get('label'))
        want, root, ancestor, seen = kind(state['nodes'][index]), index, state['nodes'][index].get('parent_index'), {index}
        while ancestor in state['nodes'] and ancestor not in seen:
            seen.add(ancestor)
            if sum(1 for i in self.subtree(state, 'e'+str(ancestor))[1] if kind(state['nodes'][i]) == want) > 1:return root
            root, ancestor = ancestor, state['nodes'][ancestor].get('parent_index')
        return None

    def discover_records(self, state, operation):
        """Repeated-control records: one record per control of the single repeated (role,label) kind.
        Returns (roots, {root: control}, found); roots is None when discovery is ambiguous (never guess)."""
        groups = {}
        for i, n in sorted(state['nodes'].items()):
            if i in state['aliases'] or n.get('enabled') is False or not self._operation_compatible(n, operation):continue
            groups.setdefault((n.get('role'), n.get('label')), []).append(i)
        repeated = {k: v for k, v in groups.items() if len(v) >= 2}
        found = {'repeated_controls': [{'role': k[0], 'label': k[1], 'count': len(v)} for k, v in list(repeated.items())[:6]],
                 'compatible_controls': sum(len(v) for v in groups.values())}
        if len(repeated) != 1:return None, {}, found
        targets = {}
        for i in next(iter(repeated.values())):
            root = self._record_root(state, i)
            if root is None or ('e'+str(root)) in targets or (root == i and not self.sibling_record(state, i)):return None, {}, found
            targets['e'+str(root)] = 'e'+str(i)
        return list(targets), targets, found

    def _bounded(self, values):
        if isinstance(values, dict):
            items = list(values.items());kept = dict(items[:self.DO_LIST_CAP])
            return kept if len(items) <= self.DO_LIST_CAP else {**kept, '_truncated': len(items)-self.DO_LIST_CAP}
        return list(values)[:self.DO_LIST_CAP]

    def _visual_available(self):
        try:self.provider('visual');return True
        except Exception:return False

    def _expect_check(self, state, before, expect, target=None, typed=None):
        """Case-insensitive exact, else contains, each required in exactly ONE element of the fresh AX tree.
        Absence is unknown, never failed. Presence that proves nothing is `unproven` (no presence-based step can prove it):
        the text was already there before the click, or it is the text just typed (the target field's own echo)."""
        norm = lambda v: re.sub(r'\s+', ' ', str(v or '').strip()).casefold()
        needle = norm(expect)
        skip = (target.get('role'), target.get('label')) if target else None
        def hits(tree, exact):
            return sum(1 for n in tree['nodes'].values() if (n.get('role'), n.get('label')) != skip
                       and any((norm(n.get(k)) == needle) if exact else (needle in norm(n.get(k))) for k in ('label', 'value')))
        if typed is not None and (needle in norm(typed) or norm(typed) in needle):
            return {'status': 'unknown', 'route': 'ax_expect', 'reason': 'expect_echoes_typed_text', 'unproven': True}
        if hits(before, False) > 0:
            return {'status': 'unknown', 'route': 'ax_expect', 'reason': 'expect_present_before_action', 'present_before': True, 'unproven': True}
        exact, loose = hits(state, True), hits(state, False)
        if exact == 1 or (exact == 0 and loose == 1):
            return {'status': 'satisfied', 'route': 'ax_expect_' + ('exact' if exact else 'contains'), 'present_before': False}
        return {'status': 'unknown', 'route': 'ax_expect', 'present_before': False,
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

    def _do_observation(self, pid, window_id):
        handle = self.latest.get((pid, window_id));state = self.snapshots.get(handle)
        if not state:return None
        roles = {}
        for n in state['nodes'].values():roles[n.get('role')] = roles.get(n.get('role'), 0) + 1
        return {'snapshot': handle, 'title': state['raw'].get('window_title'), 'element_count': len(state['nodes']),
                'top_roles': dict(sorted(roles.items(), key=lambda kv: (-kv[1], str(kv[0])))[:6]),
                'controls': [{'id': 'e'+str(i), 'name': (n.get('label') or '')[:40]} for i, n in state['nodes'].items()
                             if i not in state['aliases'] and 'AXPress' in n.get('actions', [])][:12]}

    def do(self, goal, title=None, pid=None, window_id=None, records=None, operation='click', text=None,
           expect=None, accept_unknown=None, budget_s=20, confirm=None):
        """One call runs observe -> read -> same-record filter -> (chooser only if several) -> bind -> act -> verify,
        recovering deterministically (bounded) and deferring to the caller only where guessing would be worse.
        Composes observe/read/choose/act/verify; owns no selection policy. Never retries a click."""
        with self.lock:return self._do(goal, title, pid, window_id, records, operation, text, expect, accept_unknown, budget_s, confirm)

    def _do(self, goal, title, pid, window_id, records, operation, text, expect, accept_unknown, budget_s, confirm=None):
        confirm_label = confirm
        t0 = self.clock();ms, calls, attempts, tries, keep = {}, {}, [], {}, {}
        ctx = {'stage': 'goal', 'pid': pid, 'window_id': window_id, 'delivery': 'none', 'selection': None, 'pass': 0}
        def finish(status, **extra):
            result = {'status': status, 'stage': ctx['stage'], **extra, 'delivery': ctx['delivery'],
                      'trace_summary': {'calls_by_route': dict(calls), 'ms_by_stage': dict(ms), 'passes': ctx['pass'],
                                        'attempts': attempts[:10], 'follow_up_needed': status != 'done'}}
            if ctx['pid'] is not None:
                observation = self._do_observation(ctx['pid'], ctx['window_id'])
                if observation:result['observation'] = observation
            self.event('do', stage=ctx['stage'], status=status, delivery=ctx['delivery'], passes=ctx['pass'],
                       attempts=len(attempts), calls_by_route=dict(calls), reason=extra.get('reason'))
            return result
        def count(name, route):
            calls[route] = calls.get(route, 0) + 1
            self.event('do_stage', stage=name, route=route, ms=ms.get(name, 0), pass_no=ctx['pass'])
        def over():return self.clock()-t0-ms.get('act', 0)/1000-ms.get('confirm', 0)/1000 > budget_s
        def hard():return self.clock()-t0 > 3*budget_s  # click and confirm time count here: slow stages cannot run on indefinitely
        def over_all():return over() or hard()
        def remaining():return max(1.0, min(20.0, budget_s - (self.clock()-t0-ms.get('act', 0)/1000-ms.get('confirm', 0)/1000)))
        def budget(**more):
            return finish('deferred', reason='budget_exceeded', budget_exceeded=True, budget_s=budget_s, **more,
                          hint='The wall budget ran out before the next step (a hard cap of 3x budget_s counts click time too); no further step ran and nothing was clicked after it. Inspect observation.snapshot before acting again.')
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
                more['retry_with'] = 'cua_do again with accept_unknown=[ids] naming exactly the unknown records your judgment excludes'
            return finish('deferred', **keep_keys, **more)
        def identity_of(reading, state, roots, selected):
            """What the selected record IS: its extracted strings (records mode) or its description."""
            if not reading:return None
            index = self.node(state, selected)['element_index']
            root = next(r for r in roots if index in self.subtree(state, r)[1])
            fields = next(r['fields'] for r in reading['extraction']['records'] if r['record_id'] == root)
            return {k: re.sub(r'\s+', ' ', str(v)).strip() for k, v in sorted(fields.items()) if v is not None}
        def attempt():
            ctx['pass'] += 1
            pid_, window_ = ctx['pid'], ctx['window_id']
            snapshot = guarded('observe', lambda: self.observe(pid_, window_, timeout=remaining()))['snapshot'];state = self.state(snapshot)
            count('observe', 'cua-driver')
            self.reject_answer_leak(state, goal)
            if over_all():return budget()
            reading, pick, roots = None, {}, []
            if spec:
                fields, predicates, supplied, coverage = spec
                ctx['stage'] = 'read'
                if supplied:roots, targets, found = list(supplied), {}, {}
                else:
                    roots, targets, found = self.discover_records(state, operation);coverage = True
                    if roots is None:
                        return finish('deferred', reason='records_ambiguous', found=found,
                                      hint='Could not tell one repeated-control record per control. Pass records.record_ids (observed record roots) or refine the goal; nothing was guessed or clicked.')
                def read_once():
                    try:return self.read(snapshot, goal, fields, roots, predicates, coverage)
                    except Gap as gap:
                        if str(gap).startswith(('Overlapping', 'Record has no observed text')):raise self._Ambiguous(str(gap))
                        raise
                reading = guarded('read', read_once);count('read', 'nuextract3')
                if reading['filter']['unknown_ids'] and not accept_unknown and not over_all():
                    # An unknown/garbled field: ONE re-read (READ_BUDGET caps it at 2), then stop and defer with the strings.
                    attempts.append({'pass': ctx['pass'], 'stage': 'read', 'kind': 'reread_unknown_field'})
                    reading = guarded('read', read_once);count('read', 'nuextract3')
                if over_all():return budget()
                ctx['stage'] = 'filter';filt = reading['filter']
                if not filt['eligible_ids']:
                    if filt['unknown_ids']:return deferred(self.incomplete_scope_defer(filt, reading))
                    return finish('deferred', reason='no_eligible_record', excluded_count=len(filt['excluded_ids']),
                                  hint='No record satisfies the predicates; nothing was clicked. Refine the fields/predicates.')
                # The judged path (record_actions/candidate_ids) skips the coverage gate, so it is used only when
                # coverage is guaranteed (discovered) or the caller names the unknowns it excludes (accept_unknown).
                if targets:pick = {'record_actions': {r: targets[r] for r in filt['eligible_ids']}}
                elif accept_unknown:pick = {'candidate_ids': list(filt['eligible_ids'])}
            mode = 'semantic'
            choose_args = dict(operation=operation, text=text)
            if reading:choose_args.update(reading=reading['reading'], accept_unknown=list(accept_unknown or []) or None, **pick)
            else:
                tokens = self.quoted_tokens(goal)
                same = [n for i, n in state['nodes'].items() if i not in state['aliases'] and len(tokens) == 1 and n.get('label') == tokens[0]]
                offered = [i for i, n in state['nodes'].items() if i not in state['aliases'] and n.get('enabled') is not False and self._operation_compatible(n, operation)]
                if len(same) == 1:mode = 'exact';choose_args.update(exact_name=tokens[0], exact_role=same[0].get('role'))
                elif not offered and operation == 'click' and self.perception_state == 'healthy':mode = 'regions'
            def choose_once():
                made = self.choose(snapshot, goal, mode=mode, **choose_args)
                # The dispatcher turns a chooser transport failure into a defer; that is a failed call, not a judgment.
                if 'selection' not in made and (made.get('decision') or {}).get('reason') == 'provider_failed':raise RuntimeError('chooser provider_failed')
                return made
            choice = guarded('choose', choose_once)
            count('choose', 'exact_observed_control' if mode == 'exact' else (choice['route'] if isinstance(choice.get('route'), str) else 'chooser'))
            if 'selection' not in choice:return deferred({**choice, 'reason': choice.get('reason') or (choice.get('decision') or {}).get('reason')})
            if over_all():
                self.selections.pop(choice.get('selection'), None)  # bound but never delivered: leave no usable authority behind
                return budget()
            selection = choice['selection'];ctx['selection'] = selection
            item = self.selections[selection]
            action = next(a for a in item['request']['actions'] if a['id'] == choice['selected_id'])
            judgment = choice.get('judgment') if choice.get('route') == 'grounded_singleton' else ('exact' if mode == 'exact' else 'chooser')
            picked = {'id': choice['selected_id'], 'description': action['description'][:120]}
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
        def after_click(before, reading, roots, picked, judgment, goal_fields):
            ctx['stage'] = 'verify';began = self.clock()
            pid_, window_ = ctx['pid'], ctx['window_id']
            base = {'selected': picked, 'judgment': judgment, 'verified': False}
            if over_all():return budget(**base)
            confirmation = None
            try:
                current = self.state(self.observe(pid_, window_, timeout=remaining())['snapshot'])
                new, replaced = self._new_modals(current, before)
                if new or replaced:
                    early, confirmation = confirm(current, new, replaced, reading, goal_fields, picked)
                    if early:return early
                    if over_all():return budget(**base)
                    ctx['stage'] = 'verify'  # the confirm click landed: a failure from here on is a verification failure, not a dialog failure
                    current = self.state(self.observe(pid_, window_, timeout=remaining())['snapshot'])
                target = self.node(before, picked['id']) if operation == 'type_text' and picked['id'] in {'e'+str(i) for i in before['nodes']} else None
                check = self._expect_check(current, before, expect, target, text if operation == 'type_text' else None) if expect else None
                if check and check['status'] == 'satisfied':verification = check
                elif check and check.get('unproven'):
                    # Presence that was already there (or the typed text echoed back) proves nothing, and no presence-based step can prove it either.
                    verification = {k: v for k, v in check.items() if k != 'unproven'}
                elif not expect and not self._visual_available():
                    verification = {'status': 'unverified', 'route': 'none', 'reason': 'no_expect_and_no_visual_provider'}
                elif over_all():return budget(**base)
                else:
                    # Deterministic escalation, all server-side: AX quote, Perception exact-presence (never on digits), then the screenshot model.
                    seen = self.verify(pid_, window_, 'The window shows "%s"' % expect if expect else 'The requested outcome is now visible: ' + goal, 'visual')
                    why = seen.get('reason') or (check or {}).get('reason')
                    verification = {'status': seen['status'], 'route': seen['route'], **({'reason': why} if why else {}),
                                    **({'present_before': check['present_before']} if check else {})}
            except (Gap, ValueError, RuntimeError, TimeoutError, OSError) as error:
                if ctx['stage'] == 'confirm':
                    if isinstance(error, DriverCallFailed):raise
                    return finish('deferred', reason='confirm_error', error_type=type(error).__name__,
                                  hint='The confirm dialog could not be handled; the first click was delivered. Inspect observation.snapshot.')
                verification = {'status': 'unknown', 'route': 'verify_error', 'error_type': type(error).__name__}
            ms['verify'] = ms.get('verify', 0) + round((self.clock()-began)*1000);count('verify', verification['route'])
            extra = {'selected': picked, 'judgment': judgment, 'verification': verification,
                     **({'confirmation': confirmation} if confirmation else {}),
                     **({'evidence': {'eligible': len(reading['filter']['eligible_ids']), 'excluded': len(reading['filter']['excluded_ids']),
                                      'unknown': len(reading['filter']['unknown_ids'])}} if reading else {})}
            if verification['status'] == 'satisfied':return finish('done', **extra, verified=True)
            # (A) a click that may have been delivered and could not be verified: the caller decides; never a re-click.
            return finish('deferred', reason='delivery_unverified', verified=False, **extra,
                          hint='The click was delivered but the outcome could not be verified. Do not click again blindly; inspect observation.snapshot (cua_verify/cua_observe) first.')
        def confirm(current, new, replaced, reading, fields_spec, picked):
            """A dialog after the first click. The goal never authorized pressing anything in it, so confirming is OPT-IN:
            only with `confirm` (an exact control label), a COMPLETE displayed-identity match with the selected record (S4.2 s7),
            and exactly ONE enabled control in the new dialog with that label. Never the chooser, never a lone control by default."""
            ctx['stage'] = 'confirm';snapshot = next(h for h, s in self.snapshots.items() if s is current)
            if replaced or len(new) != 1:
                return finish('deferred', reason='confirm_dialog_ambiguous', modal_count=len(new), selected=picked, verified=False,
                              hint='A dialog was already open, was replaced, or several appeared; the first click is done. Inspect observation.snapshot and act deliberately.'), None
            modal = 'e'+str(new[0]);nodes = current['nodes']
            buttons = [i for i in sorted(self.subtree(current, modal)[1]) if i not in current['aliases'] and nodes[i].get('enabled') is not False and 'AXPress' in nodes[i].get('actions', [])]
            labels = self._bounded([(nodes[i].get('label') or '')[:40] for i in buttons])
            fields = fields_spec[0] if fields_spec else {}
            identity = keep.get('picked_identity') or {}
            complete = bool(reading) and len(identity) == len(fields) and all(identity.values())
            state, extracted = 'not_checked' if not reading else 'unknown', None
            if complete:
                dialog = self.read(snapshot, goal, fields, [modal], [{'field': k, 'op': 'eq', 'value': v} for k, v in identity.items()], True)
                calls['nuextract3'] = calls.get('nuextract3', 0) + 1
                filt = dialog['filter'];extracted = self._bounded({modal: dialog['extraction']['records'][0]['fields']})
                state = 'matched' if filt['eligible_ids'] else ('unknown' if filt['unknown_ids'] else 'mismatch')
            # The wall budget binds the confirm step too: a slow dialog read must not be followed by a second click.
            if over_all():return budget(selected=picked, verified=False), None
            held = {'selected': picked, 'verified': False, 'dialog': {'controls': labels, 'identity': state}, **({'evidence': {'extracted': extracted}} if extracted else {})}
            if not confirm_label:
                return finish('deferred', reason='confirm_dialog_present', **held,
                              hint='The first click is done: do not repeat this goal. A dialog is showing and nothing in it was pressed. Press its control deliberately '
                                   '(cua_do with a fresh goal that quotes the control label, which does not re-click the first control; or cua_choose exact + cua_act). '
                                   'To have this goal confirm on its own, pass confirm=<exact control label>.'), None
            if not reading:return finish('deferred', reason='confirm_dialog_needs_identity', **held), None
            if state != 'matched':
                return finish('deferred', reason='confirm_identity_mismatch' if state == 'mismatch' else 'confirm_identity_unknown', **held,
                              hint='The dialog does not display the complete identity of the selected record; nothing further was clicked.'), None
            norm = lambda v: re.sub(r'\s+', ' ', str(v or '').strip()).casefold()
            hits = [i for i in buttons if norm(nodes[i].get('label')) == norm(confirm_label)]
            if len(hits) != 1:
                return finish('deferred', reason='confirm_control_not_found' if not hits else 'confirm_dialog_ambiguous', **held), None
            choice = self.choose(snapshot, goal, mode='exact', exact_name=nodes[hits[0]].get('label'), exact_role=nodes[hits[0]].get('role'), operation='click')
            count('confirm', 'exact_observed_control')
            if 'selection' not in choice:return deferred({**choice, 'reason': choice.get('reason') or 'confirm_unselected'}, **held), None
            ctx['selection'] = choice['selection']
            if over_all():
                self.selections.pop(choice['selection'], None);ctx['selection'] = None
                return budget(selected=picked, verified=False), None
            try:deliver(choice['selection'])
            except StaleUI:return finish('deferred', reason='confirm_ui_changed', **held, hint='The dialog changed before it was confirmed; the first click was delivered. Inspect observation.snapshot.'), None
            finally:count('confirm_click', 'cua-driver')
            return None, {'status': 'confirmed', 'identity': 'matched', 'selected_id': choice['selected_id']}
        try:
            if not isinstance(goal, str) or not goal.strip():raise Gap('bad_request: goal is required')
            # Before any Driver/provider call: observed IDs are unknowable yet, so ANY element-ID token is a leak.
            self.reject_answer_leak({'nodes': {int(m): 0 for m in self.OBSERVED_ID.findall(goal)}}, goal)
            if operation not in ('click', 'type_text'):raise Gap('bad_request: operation must be click or type_text')
            if operation == 'type_text' and text is None:raise Gap('bad_request: type_text requires text')
            if confirm_label is not None and (not isinstance(confirm_label, str) or not confirm_label.strip()):raise Gap('bad_request: confirm must be the exact label of a dialog control')
            if expect is not None and (not isinstance(expect, str) or not expect.strip()):raise Gap('bad_request: expect must be nonempty text')
            if not isinstance(budget_s, (int, float)) or isinstance(budget_s, bool) or budget_s <= 0:raise Gap('bad_request: budget_s must be positive seconds')
            spec = self._do_records(records) if records is not None else None
            ctx['stage'] = 'window';began = self.clock()
            if title is not None:
                if pid is not None or window_id is not None:raise Gap('bad_request: give title or pid+window_id, not both')
                found = guarded('window', lambda: self.windows(title))['windows']
                if len(found) != 1:
                    raise Gap('window_%s: %d windows match the exact title; use cua_windows to disambiguate' % ('not_found' if not found else 'ambiguous', len(found)))
                ctx.update(pid=found[0]['pid'], window_id=found[0]['window_id'])
            elif pid is None or window_id is None:raise Gap('bad_request: supply title, or pid and window_id')
            count('window', 'driver_inventory')
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
            return finish('failed', reason='driver_call_failed', message=str(gap), attempts=tries.get(ctx['stage'], 1),
                          retryable=ctx['delivery'] == 'none', **({'selection': ctx['selection']} if given_back else {}))
        except self._Ambiguous as gap:
            return finish('deferred', reason='records_ambiguous', message=str(gap))
        except Gap as gap:
            return finish('refused', reason=self._do_reason(str(gap)), message=str(gap))
        except (ValueError, RuntimeError, TimeoutError, OSError) as error:
            return finish('failed', reason='provider_failure', error_type=type(error).__name__, attempts=tries.get(ctx['stage'], 1),
                          retryable=ctx['delivery'] == 'none')

    def close(self):
        for provider in self.providers.values():
            try:provider.close()
            except Exception:self.event('cleanup',status='worker_close_failed')
        self.providers.clear()
        self.snapshots.clear();self.selections.clear();self.readings.clear();self.latest.clear()
        return {'status':'closed','trace':self.events,'driver_version':self.driver_version,'driver_version_state':self.driver_version_state,
                'perception_version':self.perception_version,'perception_state':self.perception_state}
