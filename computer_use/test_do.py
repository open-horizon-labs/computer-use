"""do: the dispatcher runs the evidence chain (S4.1-S4.2, S4.6-S4.8) and recovers in code.
Each test names the tempting wrong patch it fails. Fakes only: no Driver, model, desktop or network."""
import copy
import json
import re
import unittest

from core import Facade, Gap, DriverCallFailed
from test_core import FakeDriver, FakeChooser, FakeReader, FakeVision

PROVIDERS = [('Provider A', 'Consultation', '60 min', '1:30 PM'), ('Provider B', 'Follow-up', '30 min', '2:00 PM'),
             ('Provider C', 'Follow-up', '30 min', '2:15 PM'), ('Provider D', 'Consultation', '45 min', '2:30 PM'),
             ('Provider E', 'Follow-up', '30 min', '1:45 PM'), ('Provider F', 'Follow-up', '30 min', '2:45 PM'),
             ('Provider G', 'Follow-up', '30 min', '3:15 PM'), ('Provider H', 'Follow-up', '30 min', '4:00 PM'),
             ('Provider I', 'Follow-up', '30 min', '2:05 PM'), ('Provider J', 'Telehealth', 'half-hour', '3:00 PM'),
             ('Provider K', 'Follow-up', '30 min', '11:00 AM'), ('Provider L', 'Consultation', '30 min', '2:20 PM')]
FIELDS = {'provider': {'description': 'Provider name'}, 'service': {'description': 'Service'},
          'duration': {'description': 'Duration'}, 'start': {'description': 'Start time'}}
PATTERNS = {'provider': r'(Provider \w+)', 'service': r'(Consultation|Follow-up|Telehealth)',
            'duration': r'(\d+ min|half-hour)', 'start': r'(Starts [0-9:]+ [AP]M)'}
ORDER_FIELDS = {'order': {'description': 'Order number'}, 'customer': {'description': 'Customer name'}}
ORDER_PATTERNS = {'order': r'(\d{4})', 'customer': r'(Cedar|Birch|Maple|Oak|Elm)'}
ORDERS = [(1041, 'Birch'), (1042, 'Cedar'), (1043, 'Maple'), (1044, 'Cedar'), (1045, 'Oak'), (1046, 'Elm')]


def button(i):
    return 'e%d' % (5 * (i + 1))  # flat booking layout: 4 texts then the control per record


def flat_window(sid, rows, shift=False, extra_button=False, header=None, footer=None, banner=None, textfield=None):
    """Flat AX like Chrome's: each record's texts precede its identical control, no wrapper groups."""
    nodes = [{'element_index': 0, 'role': 'AXWindow', 'label': 'Clinic Slots'}]
    def add(role, **kw):
        nodes.append({'element_index': len(nodes), 'parent_index': 0, 'role': role, **kw})
    if shift:add('AXGroup')  # same content, every later index moves by one
    if banner:add('AXStaticText', value=banner)
    if header:add('AXStaticText', value=header)
    for texts, label in rows:
        for value in texts:add('AXStaticText', value=value)
        add('AXButton', label=label, actions=['AXPress'])
        if extra_button:add('AXButton', label='Details', actions=['AXPress'])
    if footer:add('AXStaticText', value=footer)
    if textfield is not None:add('AXTextField', label='Name', value=textfield)
    return nodes


def booking_rows(providers=PROVIDERS, label='Book'):
    return [((n, s, d, 'Starts ' + t), label) for n, s, d, t in providers]


def order_rows(orders=ORDERS):
    return [(('Order %d' % i, 'Customer ' + c, 'Placed today'), 'Cancel order') for i, c in orders]


class FlatDriver(FakeDriver):
    """observe() builds a flat page; hooks change it per observation number to script UI churn."""
    def __init__(self):
        super().__init__()
        self.rows = booking_rows();self.layout = {};self.rows_at = None;self.confirm_text = None;self.confirm_copies = 1
        self.modal = None;self.pre_modal = None;self.shift_at = lambda v: False;self.observed = [];self.typed = '';self.field = False;self.extra_sheet = False
        self.on_tool = None;self.observe_args = []
    def call(self, tool, args, timeout=20):
        if self.on_tool:self.on_tool(tool)
        if tool == 'type_text':self.typed = args['text']
        return super().call(tool, args, timeout)
    def observe(self, *args):
        self.version += 1
        rows = self.rows_at(self.version) if self.rows_at else self.rows
        sid = 's' + format(self.version, '08x')
        self.observe_args.append(args)
        nodes = flat_window(sid, rows, shift=self.shift_at(self.version), **({'textfield': self.typed} if self.field else {}), **self.layout)
        clicks = len(self.executed)
        def sheet(spec, label='Confirm', first=False):
            at = 1 if first else len(nodes)  # a pre-existing dialog sits before the records, like a page-level overlay
            block = [{'element_index': 0, 'parent_index': 0, 'role': 'AXSheet', 'label': label}] + [{'element_index': 0, 'parent_index': 0, 'role': r, **kw} for r, kw in spec]
            for k, n in enumerate(block):n['element_index'] = at + k;n['parent_index'] = 0 if k == 0 else at
            for n in nodes:
                if first and n['element_index'] >= at:n['element_index'] += len(block)
                if first and n.get('parent_index', 0) >= at:n['parent_index'] += len(block)
            nodes[at - 1 if first else len(nodes):at - 1 if first else len(nodes)] = block
            nodes.sort(key=lambda n: n['element_index'])
        if self.pre_modal and clicks == 0:sheet(self.pre_modal, first=True)
        elif self.modal and clicks == 1:
            sheet(self.modal)
            if self.extra_sheet:sheet([('AXStaticText', {'value': 'Other'})], 'Other')
        elif self.confirm_text and clicks >= (2 if self.modal else 1):
            for _ in range(self.confirm_copies):nodes.append({'element_index': len(nodes), 'parent_index': 0, 'role': 'AXGroup', 'label': self.confirm_text})
        for n in nodes:n.update(element_token=sid + ':' + str(n['element_index']), enabled=True)
        self.observed.append(sid)
        x = {'snapshot_id': sid, 'pid': 1, 'window_id': 2, 'window_title': 'Clinic Slots', 'elements': nodes, '_image': b'pixels'}
        if self.capture_id:x['capture_id'] = self.capture_id
        return x


class LineReader:
    """NuExtract stand-in: fields come from regexes over the record's own text. `missing(call, record, field)` garbles one."""
    def __init__(self, patterns=PATTERNS):
        self.patterns, self.requests, self.closed = patterns, [], False
        self.missing = lambda call, rid, field: False;self.on_call = None;self.fail_calls = ()
    def extract(self, req, sid):
        self.requests.append(copy.deepcopy(req));call = len(self.requests)
        if self.on_call:self.on_call(call)
        if call in self.fail_calls:raise RuntimeError('endpoint down')
        rows = []
        for r in req['records']:
            fields = {}
            for name in req['fields']:
                hit = re.search(self.patterns[name], r['text'])
                fields[name] = None if not hit or self.missing(call, r['id'], name) else hit.group(1)
            rows.append({'record_id': r['id'], 'fields': fields})
        return {'snapshot_id': sid, 'records': rows}
    def close(self):self.closed = True


class NamedChooser(FakeChooser):
    """Picks the offered action whose name contains `prefer` (a decision the real chooser makes on evidence)."""
    def __init__(self, prefer=None):super().__init__();self.prefer = prefer
    def __call__(self, step, request):
        self.requests.append(copy.deepcopy(request))
        pick = next((a for a in request['actions'] if self.prefer and self.prefer in a['name']), request['actions'][0])
        return {'choice': pick['id'], 'route': 'julia-1', 'action_authorized': True}


class UnknownVision(FakeVision):
    def __init__(self):super().__init__();self.calls = 0
    def inspect(self, snapshot, postcondition, timeout):self.calls += 1;return {'state': 'unknown'}


class Clock:
    def __init__(self):self.t = 0.0
    def __call__(self):return self.t
    def advance(self, seconds):self.t += seconds


def rec(predicates, fields=FIELDS, **more):
    return {'fields': fields, 'predicates': predicates, **more}


ONE = [{'field': 'service', 'value': 'Follow-up'}, {'field': 'start', 'op': 'contains', 'value': '1:45 PM'}]  # Provider E only
TWO = [{'field': 'service', 'value': 'Consultation'}, {'field': 'duration', 'op': 'neq', 'value': '60 min'}]  # D and L
D_ONLY = [{'field': 'service', 'value': 'Consultation'}, {'field': 'duration', 'value': '45 min'}]


class DoBase(unittest.TestCase):
    def setUp(self):
        self.driver = FlatDriver();self.driver.confirm_text = 'Booked Provider E 1:45 PM'
        self.reader = LineReader();self.chooser = NamedChooser();self.visual = FakeVision()
        self.starts = [];self.naps = [];self.clock = Clock();self.factory_ok = True
        def generic():self.starts.append('generic');return self.chooser
        def visual():
            if not self.factory_ok:raise RuntimeError('visual worker not configured')
            return self.visual
        self.f = Facade(self.driver, generic_factory=generic, reader_factory=lambda: self.reader, visual_factory=visual,
                        sleep=self.naps.append, clock=self.clock)
    def do(self, goal='Book the Follow-up slot that starts at 1:45 PM', **kw):
        kw.setdefault('title', 'Demo');return self.f.do(goal, **kw)
    def kinds(self, result):return [a['kind'] for a in result['trace_summary']['attempts']]


class BookingPath(DoBase):
    def test_clean_booking_is_one_call_one_read_no_chooser_one_click(self):
        # Wrong patches: route the filter-unique singleton through the chooser; read twice.
        r = self.do(records=rec(ONE), expect='Booked Provider E')
        self.assertEqual((r['status'], r['judgment'], r['verified']), ('done', 'filter', True))
        self.assertEqual(len(self.reader.requests), 1);self.assertEqual(self.chooser.requests, []);self.assertEqual(self.starts, [])
        self.assertEqual(len(self.driver.executed), 1);self.assertEqual(self.driver.executed[0]['element_token'], 's00000002:25')
        self.assertEqual(r['selected']['id'], button(4));self.assertFalse(r['trace_summary']['follow_up_needed'])
        self.assertEqual(r['verification']['status'], 'satisfied')
        self.assertEqual(r['observation']['snapshot'], self.f.latest[(1, 2)])  # the LLM can continue from this handle
        self.assertEqual(self.driver.version, 3)  # observe, act's revalidation, verification: no extra observations
        self.assertEqual(r['trace_summary']['attempts'], [])

    def test_stages_and_do_summary_are_traced_content_free(self):
        self.do(records=rec(ONE), expect='Booked Provider E')
        ops = [e['operation'] for e in self.f.events]
        self.assertEqual(ops.count('do'), 1);self.assertGreaterEqual(ops.count('do_stage'), 5)
        self.assertNotIn('Provider E', json.dumps(self.f.events))

    def test_two_eligible_records_make_exactly_one_chooser_call_over_only_those_controls(self):
        # Wrong patches: offer all 12 controls to the chooser; skip the chooser and take the first.
        self.chooser.prefer = None
        r = self.do(records=rec(TWO), expect='Booked')
        self.assertEqual(len(self.chooser.requests), 1);self.assertEqual([a['id'] for a in self.chooser.requests[0]['actions']], [button(3), button(11)])
        self.assertEqual((r['status'], r['judgment'], r['selected']['id']), ('done', 'chooser', button(3)))
        self.assertEqual(len(self.reader.requests), 1)

    def test_unknown_competitor_without_accept_unknown_defers_and_never_clicks(self):
        # Wrong patch: authorize the unique eligible record anyway (then trace it): S4.2 section 4.
        self.reader.missing = lambda call, rid, field: rid == button(11) and field == 'duration'
        r = self.do(records=rec(D_ONLY), expect='Booked')
        self.assertEqual((r['status'], r['reason']), ('deferred', 'unknown_competitors_unacknowledged'))
        self.assertEqual(self.driver.executed, []);self.assertEqual(self.f.selections, {})
        self.assertIn(button(11), r['evidence']['extracted']);self.assertEqual(r['unknown_ids'], [button(11)])
        self.assertEqual(r['delivery'], 'none')
        again = self.do(records=rec(D_ONLY), expect='Booked', accept_unknown=[button(11)])
        self.assertEqual(again['status'], 'done');self.assertEqual(len(self.driver.executed), 1)
        self.assertEqual(again['selected']['id'], button(3));self.assertEqual(again['judgment'], 'filter')

    def test_accept_unknown_must_name_a_record_that_is_unknown(self):
        r = self.do(records=rec(D_ONLY), accept_unknown=[button(0)])
        self.assertEqual(r['status'], 'refused');self.assertEqual(self.driver.executed, [])

    def test_no_eligible_record_defers_without_click(self):
        r = self.do(records=rec([{'field': 'provider', 'value': 'Provider Z'}]))
        self.assertEqual((r['status'], r['reason']), ('deferred', 'no_eligible_record'));self.assertEqual(self.driver.executed, [])

    def test_supplied_roots_without_coverage_claim_keep_the_incomplete_scope_gate(self):
        # Wrong patch: treat caller-supplied roots as judged (skips the coverage gate of S4.2 section 4).
        r = self.do(records=rec(ONE, record_ids=[button(i) for i in range(12)]))
        self.assertEqual(r['status'], 'deferred');self.assertEqual(r['reason'], 'unknown_or_incomplete_scope')
        self.assertEqual(self.driver.executed, [])
        ok = self.do(records=rec(ONE, record_ids=[button(i) for i in range(12)], coverage_complete=True), expect='Booked')
        self.assertEqual(ok['status'], 'done')

    def test_semantic_mode_without_records_uses_the_chooser_over_offered_controls(self):
        self.driver.rows = [(t, 'Book' if i % 2 else 'Reserve') for i, (t, _) in enumerate(booking_rows())]
        r = self.do('Reserve the slot with Provider A')
        self.assertEqual(len(self.chooser.requests), 1);self.assertEqual(self.reader.requests, [])
        self.assertEqual(r['judgment'], 'chooser');self.assertEqual(len(self.driver.executed), 1)

    def test_quoted_unique_label_resolves_exactly_without_a_chooser(self):
        self.driver.rows = booking_rows()[:3] + [(('Provider Z',), 'Export')]
        r = self.do('Press "Export"', expect='Booked')
        self.assertEqual((r['judgment'], self.chooser.requests, self.reader.requests), ('exact', [], []))
        self.assertEqual(len(self.driver.executed), 1)

    def test_quoted_repeated_label_is_not_exact(self):
        # Wrong patch: exact mode on a repeated label (would pick the first 'Book').
        r = self.do('Press "Book"')
        self.assertNotEqual(r.get('judgment'), 'exact')
        self.assertEqual(len(self.chooser.requests), 1)


class Discovery(DoBase):
    def test_two_repeated_controls_defer_control_needed_and_never_guess(self):
        # Wrong patch: pick the first repeated control kind ('Book') when 'Details' repeats as well.
        self.driver.layout = {'extra_button': True}
        r = self.do(records=rec(ONE))
        self.assertEqual((r['status'], r['reason']), ('deferred', 'control_needed'))
        self.assertEqual({c['label'] for c in r['found']['repeated_controls']}, {'Book', 'Details'})
        self.assertEqual(self.reader.requests, []);self.assertEqual(self.driver.executed, [])

    def test_flat_records_with_text_on_both_sides_are_ambiguous(self):
        self.driver.layout = {'header': 'Available appointments', 'footer': 'Times are local'}
        r = self.do(records=rec(ONE))
        self.assertEqual(r['reason'], 'records_ambiguous');self.assertEqual(self.driver.executed, [])

    def test_a_single_record_is_the_record(self):
        # Wrong patch: a page with one card (nothing repeats) cannot form records, a dead end for a do-only caller.
        self.driver.rows = booking_rows()[:1]
        self.assertEqual(self.do(records=rec(ONE))['reason'], 'no_eligible_record')
        r = self.do(records=rec([{'field': 'provider', 'value': 'Provider A'}]))
        self.assertEqual(len(self.driver.executed), 1)


class GoalAndWindow(DoBase):
    def wrap(self):
        self.calls = []
        real = self.driver.call
        self.driver.call = lambda tool, args, timeout=20: (self.calls.append(tool), real(tool, args, timeout))[1]

    def test_answer_leaking_goal_rejected_before_any_driver_or_provider_call(self):
        # Wrong patch: run the leak guard only after observing (it needs element IDs).
        self.wrap()
        for goal in ('Book e25', 'The correct one is Provider E', 'the answer is Provider E'):
            r = self.do(goal, records=rec(ONE))
            self.assertEqual(r['status'], 'refused', goal)
        self.assertEqual((self.calls, self.driver.version, self.reader.requests, self.starts), ([], 0, [], []))

    def test_zero_or_two_window_matches_refuse_with_no_driver_action(self):
        # Wrong patch: take the first window when the exact title is ambiguous.
        self.wrap()
        self.assertEqual(self.do(records=rec(ONE), title='Other')['reason'], 'window_not_found')
        real = self.driver.call
        two = [{'pid': 1, 'window_id': 2, 'title': 'Demo'}, {'pid': 1, 'window_id': 3, 'title': 'Demo'}]
        self.driver.call = lambda tool, args, timeout=20: {'windows': two} if tool == 'list_windows' else real(tool, args, timeout)
        r = self.do(records=rec(ONE))
        self.assertEqual((r['status'], r['reason'], r['stage']), ('refused', 'window_ambiguous', 'window'))
        self.assertEqual((self.driver.version, self.driver.executed, self.reader.requests), (0, [], []))

    def test_title_and_pid_together_or_neither_are_refused(self):
        self.assertEqual(self.do(records=rec(ONE), pid=1, window_id=2)['status'], 'refused')
        self.assertEqual(self.f.do('Book it', records=rec(ONE))['status'], 'refused')

    def test_pid_and_window_id_address_the_window_directly(self):
        r = self.f.do('Book the Follow-up at 1:45 PM', pid=1, window_id=2, records=rec(ONE), expect='Booked')
        self.assertEqual(r['status'], 'done')

    def test_bad_records_refused_before_any_driver_call(self):
        self.wrap()
        bad = [rec([{'field': 'nope', 'value': 'x'}]), rec([{'field': 'service', 'op': 'gt', 'value': 'x'}]), {'fields': {}}]
        for records in bad:self.assertEqual(self.do(records=records)['status'], 'refused')
        self.assertEqual(self.calls, [])


class Recovery(DoBase):
    """S4.2 section 7 in code: bounded recovery, never a stale reuse, never a re-click."""
    def test_stale_ui_reobserves_and_reruns_the_pipeline_with_a_new_selection(self):
        # Row 1. Wrong patch: rebind the consumed selection / its element tokens to the fresh snapshot (S4.3).
        self.driver.rows_at = lambda v: booking_rows([(n, s, d, '1:35 PM' if (n == 'Provider A' and v >= 2) else t) for n, s, d, t in PROVIDERS])
        r = self.do(records=rec(ONE), expect='Booked Provider E')
        self.assertEqual(r['status'], 'done');self.assertEqual(len(self.driver.executed), 1)
        first, second = list(self.f.selections)[:2]
        self.assertEqual(len(self.f.selections), 2);self.assertNotEqual(self.f.selections[first]['snapshot'], self.f.selections[second]['snapshot'])
        self.assertTrue(self.f.selections[first]['used']);self.assertEqual(self.driver.executed[0]['element_token'], 's00000004:25')
        self.assertEqual((r['trace_summary']['passes'], self.kinds(r)), (2, ['stale_ui']));self.assertEqual(len(self.reader.requests), 2)
        with self.assertRaisesRegex(Gap, 'already consumed'):self.f.act(first)

    def test_shifted_indices_same_content_finds_the_record_by_its_fields(self):
        # Row 2. Wrong patch: click the old element id (e25 is a different element after the shift).
        self.driver.shift_at = lambda v: v >= 2
        r = self.do(records=rec(ONE), expect='Booked Provider E')
        self.assertEqual(r['status'], 'done');self.assertEqual(r['selected']['id'], 'e26')
        self.assertEqual(self.driver.executed[0]['element_token'], 's00000004:26');self.assertEqual(len(self.driver.executed), 1)

    def test_passes_are_capped_at_two_when_the_ui_never_settles(self):
        # Wrong patch: loop until stable.
        self.driver.rows_at = lambda v: booking_rows([(n, s, d, '1:%02d PM' % (v if n == 'Provider A' else 30)) if n == 'Provider A' else (n, s, d, t) for n, s, d, t in PROVIDERS])
        r = self.do(records=rec(ONE))
        self.assertEqual((r['status'], r['reason'], r['trace_summary']['passes']), ('deferred', 'ui_changed_repeatedly', 2))
        self.assertEqual((self.driver.executed, self.driver.version, len(self.reader.requests)), ([], 4, 2))

    def test_second_pass_ambiguity_defers_without_a_click(self):
        # Case B on the second pass. Wrong patch: click the unique eligible record ignoring the new unknown competitor.
        self.driver.rows_at = lambda v: booking_rows([(n, s, d, '1:35 PM' if (n == 'Provider A' and v >= 2) else t) for n, s, d, t in PROVIDERS])
        self.reader.missing = lambda call, rid, field: call >= 2 and rid == button(11) and field == 'duration'
        r = self.do(records=rec(D_ONLY))
        self.assertEqual((r['status'], r['reason'], self.driver.executed), ('deferred', 'unknown_competitors_unacknowledged', []))
        self.assertEqual(r['trace_summary']['passes'], 2)

    def test_second_pass_picking_a_different_record_defers_as_a_real_change(self):
        # Case C. Wrong patch: click whatever the fresh pipeline selects.
        def rows(v):
            swap = {'Provider D': '30 min', 'Provider L': '45 min'} if v >= 2 else {}
            return booking_rows([(n, s, swap.get(n, d), t) for n, s, d, t in PROVIDERS])
        self.driver.rows_at = rows
        r = self.do(records=rec(D_ONLY))
        self.assertEqual((r['status'], r['reason'], self.driver.executed), ('deferred', 'record_changed', []))
        self.assertEqual(len(self.f.selections), 1)  # the consumed first selection only; the fresh one was revoked, never usable

    def test_second_pass_no_longer_matching_defers(self):
        self.driver.rows_at = lambda v: booking_rows([(n, s, '30 min' if (n == 'Provider D' and v >= 2) else d, t) for n, s, d, t in PROVIDERS])
        r = self.do(records=rec(D_ONLY))
        self.assertEqual((r['reason'], self.driver.executed), ('no_eligible_record', []))

    def test_recovery_honors_the_wall_budget(self):
        # Wrong patch: a second pass that ignores what the first already spent.
        self.driver.rows_at = lambda v: booking_rows([(n, s, d, '1:35 PM' if (n == 'Provider A' and v >= 2) else t) for n, s, d, t in PROVIDERS])
        self.reader.on_call = lambda call: self.clock.advance(12)
        r = self.do(records=rec(ONE), budget_s=20)
        self.assertEqual((r['status'], r['reason'], r['budget_exceeded'], r['stage']), ('deferred', 'budget_exceeded', True, 'read'))
        self.assertEqual((self.driver.executed, r['trace_summary']['passes']), ([], 2))

    def test_garbled_identity_blocks_stale_recovery(self):
        # P1-3. Wrong patch: compare identities that dropped None fields ({} == {} is vacuously "the same record").
        self.driver.rows_at = lambda v: booking_rows([(n, s, d, '1:35 PM' if (n == 'Provider A' and v >= 2) else t) for n, s, d, t in PROVIDERS])
        self.reader.missing = lambda call, rid, field: rid == button(4) and field == 'duration'
        r = self.do(records=rec(ONE))
        self.assertEqual((r['status'], r['reason'], self.driver.executed, len(self.reader.requests)), ('deferred', 'record_changed_unverifiable', [], 1))
        self.assertEqual(self.f.selections and all(s['used'] for s in self.f.selections.values()), True)

    def test_two_records_with_the_same_identity_block_stale_recovery(self):
        # P1-3. Wrong patch: recovery by identity when the identity is not position-independent.
        twin = [(n, s, d, t) if n != 'Provider F' else ('Provider E', 'Follow-up', '30 min', '1:45 PM') for n, s, d, t in PROVIDERS]
        self.driver.rows_at = lambda v: booking_rows([(n, s, d, '1:35 PM' if (n == 'Provider A' and v >= 2) else t) for n, s, d, t in twin])
        r = self.do(records=rec(ONE))
        self.assertEqual((r['status'], r['reason'], self.driver.executed), ('deferred', 'record_changed_unverifiable', []))

    def test_delivered_click_that_cannot_be_verified_is_deferred_and_never_reclicked(self):
        # Case A after a recovered stale pass. Wrong patch: click again because verification was unknown.
        self.driver.rows_at = lambda v: booking_rows([(n, s, d, '1:35 PM' if (n == 'Provider A' and v >= 2) else t) for n, s, d, t in PROVIDERS])
        self.driver.confirm_text = None;self.visual = UnknownVision()
        r = self.do(records=rec(ONE), expect='Booked Provider E')
        self.assertEqual((r['status'], r['reason'], r['delivery']), ('deferred', 'delivery_unverified', 'delivered'))
        self.assertEqual(len(self.driver.executed), 1);self.assertFalse(r['verified'])
        self.assertEqual(r['verification']['status'], 'unknown')

    def test_transient_driver_failure_before_the_click_is_retried_once_after_a_backoff(self):
        # Row 3. Wrong patch: surface the raw failure to the LLM, or retry without bound.
        real = self.driver.observe;seen = []
        def flaky(*a):
            seen.append(1)
            if len(seen) == 1:raise DriverCallFailed('driver_call_failed: get_window_state exited 1')
            return real(*a)
        self.driver.observe = flaky
        r = self.do(records=rec(ONE), expect='Booked')
        self.assertEqual((r['status'], self.naps, self.kinds(r)), ('done', [0.3], ['retry_after_transient_failure']))

    def test_persistent_driver_failure_returns_failed_retryable_with_attempts(self):
        self.driver.observe = lambda *a: (_ for _ in ()).throw(DriverCallFailed('driver_call_failed: get_window_state exited 1'))
        r = self.do(records=rec(ONE))
        self.assertEqual((r['status'], r['retryable'], r['attempts'], r['stage'], self.naps), ('failed', True, 2, 'observe', [0.3]))
        self.assertEqual((self.driver.executed, r['reason']), ([], 'driver_call_failed'))

    def test_transient_reader_failure_is_retried_once_and_persistent_one_is_failed(self):
        self.reader.fail_calls = (1,)
        self.assertEqual(self.do(records=rec(ONE), expect='Booked')['status'], 'done')
        self.assertEqual(len(self.reader.requests), 2)
        self.setUp();self.reader.fail_calls = (1, 2)
        r = self.do(records=rec(ONE))
        self.assertEqual((r['status'], r['retryable'], r['attempts'], r['stage'], self.driver.executed), ('failed', True, 2, 'read', []))

    def test_failure_of_the_act_revalidation_before_the_click_is_retried_and_returns_the_selection_if_persistent(self):
        real = self.driver.observe;state = {'fail': True}
        def flaky(*a):
            if self.driver.version >= 1 and state['fail']:raise DriverCallFailed('driver_call_failed: get_window_state exited 1')
            return real(*a)
        self.driver.observe = flaky
        r = self.do(records=rec(ONE))
        self.assertEqual((r['status'], r['retryable'], r['attempts'], r['stage']), ('failed', True, 2, 'act'))
        self.assertEqual(self.driver.executed, []);self.assertIn(r['selection'], self.f.selections)
        state['fail'] = False  # transient over: the given-back selection still works through the advanced tool
        self.assertTrue(self.f.act(r['selection'])['requires_verification']);self.assertEqual(len(self.driver.executed), 1)

    def test_transient_chooser_failure_is_retried_once_before_any_click(self):
        # Row 3 (choose stage). Wrong patch: hand the chooser's transport error to the driving LLM.
        class Flaky(NamedChooser):
            def __call__(inner, step, request):
                inner.requests.append(1)
                if len(inner.requests) == 1:raise RuntimeError('endpoint down')
                return {'choice': request['actions'][0]['id'], 'route': 'julia-1', 'action_authorized': True}
        self.chooser = Flaky()
        r = self.do(records=rec(TWO), expect='Booked')
        self.assertEqual((r['status'], len(self.chooser.requests), self.kinds(r), len(self.driver.executed)), ('done', 2, ['retry_after_transient_failure'], 1))
        self.setUp();self.chooser = type('Down', (NamedChooser,), {'__call__': lambda inner, step, request: (_ for _ in ()).throw(RuntimeError('down'))})()
        r = self.do(records=rec(TWO))
        self.assertEqual((r['status'], r['stage'], r['attempts'], r['retryable'], self.driver.executed), ('failed', 'choose', 2, True, []))

    def test_click_failure_is_never_retried_and_is_not_retryable(self):
        # Wrong patch: retry act() on any DriverCallFailed (the click may already have been delivered).
        real = self.driver.call;clicks = []
        def bad(tool, args, timeout=20):
            if tool == 'click':clicks.append(1);raise DriverCallFailed('driver_call_failed: click exited 1; the action may have been delivered, so verify before retrying')
            return real(tool, args, timeout)
        self.driver.call = bad
        r = self.do(records=rec(ONE))
        self.assertEqual((r['status'], r['retryable'], r['delivery'], len(clicks), self.naps), ('failed', False, 'uncertain', 1, []))
        self.assertNotIn('selection', r);self.assertTrue(all(s['used'] for s in self.f.selections.values()))

    def test_garbled_field_is_reread_once_then_deferred_with_the_strings(self):
        # Row 4. Wrong patch: re-read until it parses (READ_BUDGET caps at 2; S4.8 forbids re-read loops).
        self.reader.missing = lambda call, rid, field: rid == button(11) and field == 'duration'
        r = self.do(records=rec(D_ONLY))
        self.assertEqual(r['reason'], 'unknown_competitors_unacknowledged');self.assertEqual(len(self.reader.requests), 2)
        self.assertEqual(self.kinds(r), ['reread_unknown_field']);self.assertEqual(self.driver.executed, [])

    def test_garbled_first_read_recovered_by_the_single_reread(self):
        self.reader.missing = lambda call, rid, field: call == 1 and rid == button(11) and field == 'duration'
        r = self.do(records=rec(D_ONLY), expect='Booked')
        self.assertEqual((r['status'], len(self.reader.requests), r['selected']['id']), ('done', 2, button(3)))

    def test_no_reread_when_the_caller_already_judged_the_unknowns(self):
        self.reader.missing = lambda call, rid, field: rid == button(11) and field == 'duration'
        self.do(records=rec(D_ONLY), accept_unknown=[button(11)], expect='Booked')
        self.assertEqual(len(self.reader.requests), 1)


class Verification(DoBase):
    def test_expect_already_on_the_page_is_unproven_after_a_click_that_changed_nothing(self):
        # P1-4. Wrong patch: presence after the click is proof even when the text was already there before it.
        self.driver.layout = {'banner': 'Confirmation ready'};self.driver.confirm_text = None;self.visual = UnknownVision()
        r = self.do(records=rec(ONE), expect='Confirmation ready')
        self.assertEqual((r['status'], r['reason'], r['verification']['reason'], self.visual.calls), ('deferred', 'delivery_unverified', 'expect_present_before_action', 0))
        self.assertEqual(len(self.driver.executed), 1)

    def test_typed_text_does_not_satisfy_expect_by_itself(self):
        # P1-4. Wrong patch: the field's own value counts as evidence that typing worked.
        self.driver.rows = [];self.driver.field = True;self.visual = UnknownVision()
        r = self.do('Type the name into "Name"', operation='type_text', text='hello', expect='hello')
        self.assertEqual((r['status'], r['verification']['reason'], len(self.driver.executed)), ('deferred', 'expect_echoes_typed_text', 1))
        self.assertEqual(self.visual.calls, 0)

    def test_typing_can_still_be_verified_by_different_text(self):
        self.driver.rows = [];self.driver.field = True;self.driver.confirm_text = 'Saved';self.visual = UnknownVision()
        real = self.driver.observe
        r = self.do('Type the name into "Name"', operation='type_text', text='hello', expect='Saved')
        self.assertEqual(r['status'], 'done')

    def test_expect_absent_escalates_to_the_screenshot_model_which_can_satisfy(self):
        # Row 5. Wrong patch: stop at the AX check and report unknown.
        self.driver.confirm_text = None
        r = self.do(records=rec(ONE), expect='Booking confirmed')
        self.assertEqual((r['status'], r['verification']['route']), ('done', 'systemone_vision'))

    def test_unknown_after_every_applicable_step_is_deferred_not_success(self):
        # Wrong patch: report delivery as success. Absent expect + no visual provider: unknown, status not done.
        self.driver.confirm_text = None;self.factory_ok = False
        r = self.do(records=rec(ONE), expect='Booking confirmed')
        self.assertEqual((r['status'], r['verification']['status'], r['verified'], r['delivery']), ('deferred', 'unknown', False, 'delivered'))
        self.assertEqual(len(self.driver.executed), 1)

    def test_no_expect_is_delivered_unverified_never_success_even_with_a_visual_provider(self):
        # Wrong patch: let the screenshot model or the goal stand in for expect.
        r = self.do(records=rec(ONE))
        self.assertEqual((r['status'], r['verification']['status'], r['trace_summary']['follow_up_needed']), ('delivered_unverified', 'unverified', True));self.assertEqual(len(self.driver.executed), 1)

    def test_expect_in_two_elements_is_unknown_not_satisfied(self):
        # Wrong patch: any hit satisfies.
        self.driver.confirm_copies = 2;self.visual = UnknownVision()
        r = self.do(records=rec(ONE), expect='Booked Provider E')
        self.assertEqual((r['status'], r['verification']['status'], r['verification']['reason']), ('deferred', 'unknown', 'expect_ambiguous'))

    def test_expect_matches_case_insensitively_and_exact_beats_contains(self):
        self.driver.confirm_text = 'BOOKED PROVIDER E 1:45 PM'
        r = self.do(records=rec(ONE), expect='booked provider e 1:45 pm')
        self.assertEqual(r['verification']['route'], 'ax_expect_exact')

    def test_absence_is_unknown_never_failed(self):
        self.driver.confirm_text = None;self.visual = UnknownVision()
        r = self.do(records=rec(ONE), expect='Something else')
        self.assertEqual(r['verification']['status'], 'unknown');self.assertNotEqual(r['status'], 'failed')

    def test_perception_exact_presence_is_tried_before_the_screenshot_model(self):
        self.driver.confirm_text = None;self.visual = UnknownVision()
        self.driver.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'};self.driver.capture_id = 'cap'
        self.driver.parse_result = {'regions': [{'id': 't1', 'kind': 'text', 'text': 'Confirmed', 'bounds': {'x': 1, 'y': 1, 'width': 9, 'height': 9}}]}
        r = self.do(records=rec(ONE), expect='Confirmed')
        self.assertEqual((r['status'], r['verification']['route'], self.visual.calls), ('done', 'perception_ocr_fuzzy', 0))

    def test_perception_never_satisfies_a_digit_bearing_quote(self):
        # Wrong patch: accept OCR presence for digits ("60 min" -> "600 min").
        self.driver.confirm_text = None;self.visual = UnknownVision()
        self.driver.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'};self.driver.capture_id = 'cap'
        self.driver.parse_result = {'regions': [{'id': 't1', 'kind': 'text', 'text': 'Booked 1:45 PM', 'bounds': {'x': 1, 'y': 1, 'width': 9, 'height': 9}}]}
        r = self.do(records=rec(ONE), expect='Booked 1:45 PM')
        self.assertEqual((r['status'], self.visual.calls), ('deferred', 1))


class ConfirmDialog(DoBase):
    CONFIRM = 'Yes, cancel order'
    MODAL = [('AXStaticText', {'value': 'Cancel order 1042 for Cedar?'}),
             ('AXButton', {'label': 'Keep order', 'actions': ['AXPress']}), ('AXButton', {'label': 'Yes, cancel order', 'actions': ['AXPress']})]
    def setUp(self):
        super().setUp()
        self.driver.rows = order_rows();self.driver.confirm_text = 'Order 1042 cancelled';self.reader.patterns = ORDER_PATTERNS
        self.chooser.prefer = 'Yes'
    def cancel(self, confirm=None, **kw):
        self.driver.modal = kw.get('modal', self.MODAL)
        more = {'confirm': confirm} if confirm is not None else {}
        return self.do('Cancel the order 1042 for customer Cedar', records=rec([{'field': 'order', 'value': '1042'}, {'field': 'customer', 'value': 'Cedar'}], fields=ORDER_FIELDS), expect='Order 1042 cancelled', **more)

    # --- review of PR 15: safety fixes -------------------------------------------------------------
    def test_confirm_prefire_failure_after_the_first_click_returns_no_selection(self):
        # P1-1. Wrong patch: given_back = selection unused, without asking whether ANY click was already delivered.
        real = self.driver.observe
        self.driver.observe = lambda *a: (_ for _ in ()).throw(DriverCallFailed('driver_call_failed: get_window_state exited 1')) if (self.driver.version >= 3 and len(self.driver.executed) == 1) else real(*a)
        r = self.cancel(confirm=self.CONFIRM)
        self.assertEqual((r['status'], r['delivery'], r['retryable'], len(self.driver.executed)), ('failed', 'delivered', False, 1))
        self.assertNotIn('selection', r)
        self.driver.observe = real
        for handle in list(self.f.selections):
            with self.assertRaises(Gap):self.f.act(handle)  # nothing left that could click the dialog
        self.assertEqual(len(self.driver.executed), 1)

    def dialog(self, *controls, text='Cancel order 1042 for Cedar?'):
        return [('AXStaticText', {'value': text}), *[('AXButton', {'label': c, 'actions': ['AXPress']}) for c in controls]]

    def test_a_single_dialog_control_is_never_clicked_without_confirm(self):
        # P1-2. Wrong patch: click the only control because the dialog's identity matched (the goal never authorized it).
        r = self.cancel(modal=self.dialog('Delete'))
        self.assertEqual((r['status'], r['reason'], len(self.driver.executed)), ('deferred', 'confirm_dialog_present', 1))
        self.assertEqual((r['dialog']['controls'], r['dialog']['identity']), (['Delete'], 'matched'));self.assertIn('first click is done', r['hint'])

    def test_confirm_must_equal_a_control_label_exactly(self):
        # Wrong patch: substring or fuzzy label match ('Cancel order' would hit 'Yes, cancel order').
        r = self.cancel(modal=self.dialog('Keep order', 'Yes, cancel order'), confirm='Cancel order')
        self.assertEqual((r['reason'], len(self.driver.executed), self.chooser.requests), ('confirm_control_not_found', 1, []))

    def test_a_slow_dialog_read_cannot_be_followed_by_a_second_click(self):
        # Review of the fixes: confirm ignored the budget, so a 100 s dialog read was followed by a click.
        # Wrong patch: check the budget only before the first click and after the whole confirm step.
        self.reader.on_call = lambda call: self.clock.advance(100) if call == 2 else None
        self.driver.modal = self.MODAL
        r = self.do('Cancel the order 1042 for customer Cedar', records=rec([{'field': 'order', 'value': '1042'}, {'field': 'customer', 'value': 'Cedar'}], fields=ORDER_FIELDS),
                    expect='Order 1042 cancelled', confirm=self.CONFIRM, budget_s=20)
        self.assertEqual((r['status'], r['reason'], r['delivery'], len(self.driver.executed)), ('deferred', 'budget_exceeded', 'delivered', 1))
        self.assertNotIn('selection', r)

    def test_confirm_clicks_the_named_control_case_and_space_insensitively_without_the_chooser(self):
        r = self.cancel(confirm='  yes,  CANCEL order ')
        self.assertEqual((r['status'], len(self.driver.executed), self.chooser.requests), ('done', 2, []))

    def test_two_dialog_controls_with_the_confirm_label_are_ambiguous(self):
        r = self.cancel(modal=self.dialog('Yes, cancel order', 'Yes, cancel order'), confirm='Yes, cancel order')
        self.assertEqual((r['reason'], len(self.driver.executed)), ('confirm_dialog_ambiguous', 1))

    def test_confirm_needs_a_complete_identity_match(self):
        # Wrong patch: confirm on a dialog that displays only some of the identity.
        r = self.cancel(modal=self.dialog('Yes, cancel order', text='Cancel order 1042?'), confirm='Yes, cancel order')
        self.assertEqual((r['reason'], len(self.driver.executed)), ('confirm_identity_partial', 1))
        self.assertEqual((r['identity_shown'], r['identity_not_shown']), (['order'], ['customer']))

    def test_a_preexisting_dialog_is_not_the_confirm_dialog(self):
        # Wrong patch: count modals; an unchanged pre-existing one must never be mistaken for the new dialog.
        same = self.dialog('Dismiss', text='Session expiring');self.driver.pre_modal = same;self.visual = UnknownVision()
        r = self.cancel(confirm='Yes, cancel order', modal=same)
        self.assertEqual((r['reason'], len(self.driver.executed)), ('delivery_unverified', 1))

    def test_a_replaced_dialog_is_ambiguous_not_confirmed(self):
        # Wrong patch: equal modal counts before and after mean "nothing new".
        self.driver.pre_modal = self.dialog('Dismiss', text='Session expiring')
        r = self.cancel(confirm='Yes, cancel order')
        self.assertEqual((r['reason'], len(self.driver.executed)), ('confirm_dialog_ambiguous', 1))

    def test_an_extra_dialog_beside_a_preexisting_one_is_ambiguous(self):
        self.driver.pre_modal = self.dialog('Dismiss', text='Session expiring');self.driver.extra_sheet = True
        r = self.cancel(confirm='Yes, cancel order')
        self.assertEqual((r['reason'], len(self.driver.executed)), ('confirm_dialog_ambiguous', 1))

    def test_confirm_dialog_is_confirmed_only_after_its_displayed_identity_matches(self):
        # Row 6. Wrong patch: click the dialog's affirmative control without reading what it says.
        r = self.cancel(confirm=self.CONFIRM)
        self.assertEqual((r['status'], r['confirmation']['identity']), ('done', 'matched'))
        self.assertEqual(len(self.driver.executed), 2);self.assertEqual(len(self.reader.requests), 2);self.assertEqual(self.chooser.requests, [])

    def test_a_dialog_is_reported_not_pressed_when_the_goal_gave_no_confirm_label(self):
        # Wrong patch: the identity match alone authorizes pressing the dialog's affirmative control.
        r = self.cancel()
        self.assertEqual((r['status'], r['reason'], len(self.driver.executed)), ('deferred', 'confirm_dialog_present', 1))
        self.assertEqual((r['dialog']['controls'], r['dialog']['identity']), (['Keep order', 'Yes, cancel order'], 'matched'))

    def test_confirm_dialog_naming_another_record_defers_and_clicks_nothing_more(self):
        wrong = [('AXStaticText', {'value': 'Cancel order 1043 for Cedar?'})] + self.MODAL[1:]
        r = self.cancel(confirm=self.CONFIRM, modal=wrong)
        self.assertEqual((r['status'], r['reason'], len(self.driver.executed), self.chooser.requests), ('deferred', 'confirm_identity_mismatch', 1, []))
        self.setUp();self.reader.patterns = ORDER_PATTERNS;self.driver.rows = order_rows();self.driver.confirm_text = 'Order 1042 cancelled'
        self.assertEqual(self.cancel(modal=wrong)['dialog']['identity'], 'mismatch')

    def test_confirm_dialog_that_shows_no_identity_defers(self):
        blank = [('AXStaticText', {'value': 'Are you sure?'})] + self.MODAL[1:]
        r = self.cancel(confirm=self.CONFIRM, modal=blank)
        self.assertEqual((r['reason'], len(self.driver.executed)), ('confirm_identity_unknown', 1))

    def test_dialog_without_a_record_identity_is_never_auto_confirmed(self):
        self.driver.rows = [(('Only',), 'Delete'), (('Other',), 'Delete')]
        self.driver.modal = self.MODAL
        r = self.do('Delete "Delete"', confirm=self.CONFIRM)  # not exact (repeated): chooser path, no reading to compare against
        self.assertEqual((r['reason'], len(self.driver.executed)), ('confirm_dialog_needs_identity', 1))
        self.setUp();self.driver.rows = [(('Only',), 'Delete'), (('Other',), 'Delete')];self.driver.modal = self.MODAL
        self.assertEqual(self.do('Delete "Delete"')['reason'], 'confirm_dialog_present')


class Bounds(DoBase):
    def test_hard_cap_counts_click_time_and_stops_verification(self):
        # P2-6. Wrong patch: exclude click time from every budget, so slow stages run on indefinitely.
        self.driver.on_tool = lambda tool: self.clock.advance(10) if tool == 'click' else None
        r = self.do(records=rec(ONE), expect='Booked Provider E', budget_s=2)
        self.assertEqual((r['status'], r['reason'], r['delivery'], len(self.driver.executed), self.driver.version), ('deferred', 'budget_exceeded', 'delivered', 1, 2))

    def test_hard_cap_blocks_the_second_pass(self):
        self.driver.rows_at = lambda v: booking_rows([(n, s, d, '1:35 PM' if (n == 'Provider A' and v >= 2) else t) for n, s, d, t in PROVIDERS])
        real = self.driver.observe
        def slow(*a):
            if self.driver.version == 1:self.clock.advance(10)  # act's revalidation: excluded from the soft budget
            return real(*a)
        self.driver.observe = slow
        r = self.do(records=rec(ONE), budget_s=2)
        self.assertEqual((r['reason'], self.driver.executed, len(self.reader.requests)), ('budget_exceeded', [], 1))

    def test_driver_observation_timeout_is_capped_by_the_remaining_budget(self):
        # Wrong patch: always the Driver's 20 s default.
        self.do(records=rec(ONE), budget_s=5, expect='Booked')
        self.assertLessEqual(self.driver.observe_args[0][3], 5)

    def test_follow_up_needed_replaces_the_hardcoded_call_count(self):
        # P2-5. Wrong patch: a tool that claims how many LLM calls were made.
        done = self.do(records=rec(ONE), expect='Booked Provider E')
        held = self.do(records=rec([{'field': 'provider', 'value': 'Provider Z'}]))
        self.assertNotIn('llm_visible_calls', json.dumps(done));self.assertNotIn('llm_visible_calls', json.dumps(self.f.events))
        self.assertEqual((done['trace_summary']['follow_up_needed'], held['trace_summary']['follow_up_needed']), (False, True))

    def test_reader_that_overruns_the_budget_stops_before_any_click(self):
        # Wrong patch: check the budget only at the end.
        self.reader.on_call = lambda call: self.clock.advance(25)
        r = self.do(records=rec(ONE), budget_s=20)
        self.assertEqual((r['status'], r['stage'], r['budget_exceeded']), ('deferred', 'read', True))
        self.assertEqual((self.driver.executed, self.chooser.requests), ([], []))

    def test_chooser_that_overruns_the_budget_leaves_the_selection_unused(self):
        class Slow(NamedChooser):
            def __call__(inner, step, request):self.clock.advance(25);return NamedChooser.__call__(inner, step, request)
        self.chooser = Slow()
        r = self.do(records=rec(TWO), budget_s=20)
        self.assertEqual((r['status'], r['stage'], self.driver.executed, self.f.selections), ('deferred', 'choose', [], {}))

    def test_budget_must_be_positive(self):
        self.assertEqual(self.do(records=rec(ONE), budget_s=0)['status'], 'refused')

    def test_response_stays_small_for_a_400_element_page(self):
        # Wrong patch: dump the full observation into the response.
        many = [('Provider %03d' % i, 'Follow-up', '30 min', '1:%02d PM' % (i % 60)) for i in range(80)]
        self.driver.rows = booking_rows(many);self.driver.confirm_text = 'Booked Provider 041 1:41 PM'
        r = self.do(records=rec([{'field': 'provider', 'value': 'Provider 041'}]), expect='Booked Provider 041')
        self.assertEqual(r['status'], 'done');self.assertEqual(r['observation']['element_count'] > 380, True)
        self.assertLess(len(json.dumps(r)), 6000)
        self.setUp();self.driver.rows = booking_rows(many);self.reader.missing = lambda call, rid, field: True
        d = self.do(records=rec([{'field': 'provider', 'value': 'Provider 041'}]))
        self.assertEqual(d['status'], 'deferred');self.assertLess(len(json.dumps(d)), 6000)
        self.assertEqual(d['evidence']['extracted']['_truncated'], 60)


class RegionsAndGuards(DoBase):
    def test_canvas_page_without_ax_controls_uses_regions_when_perception_is_healthy(self):
        self.driver.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'};self.driver.capture_id = 'cap'
        self.driver.rows = [(('Save', 'Export', 'Reset'), 'ignored')]
        real = self.driver.observe
        def canvas(*a):
            x = real(*a);x['elements'] = [e for e in x['elements'] if e['element_index'] == 0];return x
        self.driver.observe = canvas
        self.driver.parse_result = {'regions': [{'id': 't%d' % i, 'kind': 'text', 'text': t, 'bounds': {'x': 5, 'y': 10 + 30 * i, 'width': 50, 'height': 20}}
                                                for i, t in enumerate(['Save', 'Export', 'Reset'])]}
        self.chooser.prefer = None
        class Picks(NamedChooser):
            def __call__(inner, step, request):
                inner.requests.append(request);return {'choice': 't1', 'route': 'julia-1', 'action_authorized': True}
        self.chooser = Picks()
        r = self.do('Press "Export"', expect='Exported', allow_foreground=True)
        self.assertEqual((r['status'], r['selected']['id']), ('done', 't1'))
        self.assertEqual(r['delivery'], 'delivered');self.assertEqual(self.driver.executed[0]['capture_id'], 'cap')

    def test_primitives_still_bind_only_current_snapshots(self):
        # Wrong patch: let do's handles or snapshots leak into the primitives' guarantees.
        first = self.f.observe(1, 2)['snapshot'];self.f.observe(1, 2)
        with self.assertRaises(Gap):self.f.choose(first, 'Reserve', mode='exact', exact_name='Book')

    def test_do_leaves_no_usable_selection_after_a_deferral(self):
        self.reader.missing = lambda call, rid, field: rid == button(11) and field == 'duration'
        self.do(records=rec(D_ONLY))
        self.assertEqual(self.f.selections, {})


if __name__ == '__main__':unittest.main()


class RealCallDriver(FlatDriver):
    """A click goes through the real core.Driver.call parsing (subprocess patched), so the Driver's own answer shape is what is tested."""
    def __init__(self, answer):
        super().__init__();self.answer = answer;self.real = __import__('core').Driver('cua-driver');self.clicks = 0
    def call(self, tool, args, timeout=20):
        if tool != 'click':return super().call(tool, args, timeout)
        self.clicks += 1
        from unittest import mock
        done = mock.Mock(stdout=json.dumps(self.answer))
        with mock.patch('core.subprocess.run', return_value=done):
            return self.real.call(tool, args, timeout)


class DriverEffectRefused(DoBase):
    """#38: a Driver answer with effect "refused" is a refusal, never delivered (#5 saw status delivered with element_outside_target_window)."""
    def run_with(self, answer):
        self.driver = RealCallDriver(answer);self.driver.confirm_text = 'Booked Provider E 1:45 PM'
        self.f.driver = self.driver
        return self.do(records=rec(ONE), expect='Booked Provider E')

    def assertRefused(self, r, code):
        self.assertEqual((r['status'], r['reason']), ('refused', code))
        self.assertNotEqual(r.get('delivery'), 'delivered');self.assertNotIn('verification', r);self.assertEqual(self.driver.clicks, 1)
        self.assertFalse(r.get('verified'))

    def test_top_level_effect_refused_is_a_refusal_with_the_driver_code(self):
        # Wrong patch: map only the top-level status (this answer has no status) so effect refused stays delivered.
        self.assertRefused(self.run_with({'effect': 'refused', 'refusal_code': 'element_outside_target_window'}), 'element_outside_target_window')

    def test_effect_refused_on_a_per_action_result_is_a_refusal(self):
        # Wrong patches: check only value['effect']; or take only results[0].
        r = self.run_with({'effect': 'unverifiable', 'results': [{'effect': 'ok'}, {'effect': 'refused', 'refusal': {'code': 'element_outside_target_window'}}]})
        self.assertRefused(r, 'element_outside_target_window')

    def test_unparseable_refusal_code_is_a_generic_reason_not_echoed_text(self):
        r = self.run_with({'effect': 'refused', 'refusal_code': 'Outside the window at /Users/me/secret'})
        self.assertRefused(r, 'driver_refused');self.assertNotIn('secret', json.dumps(r))

    def test_a_non_refused_effect_is_still_delivered(self):
        # Guards an over-broad patch that refuses every effect.
        r = self.run_with({'effect': 'unverifiable'})
        self.assertEqual(r['status'], 'done')


PARTIAL = {'effect': 'partial', 'path': 'key_events_fg', 'requested_chars': 19, 'delivered_chars': 0, 'retry_from_character': 0, 'retryable': True, 'code': 'type_text_incomplete'}


class PartialType(DoBase):
    """#57: effect partial on a type_text is reported (delivery_detail), never plain delivered, and never retried."""
    def setUp(self):
        super().setUp()
        driver = self.driver;driver.rows = [];driver.field = True;driver.confirm_text = None;self.visual = UnknownVision()
        self.answer = PARTIAL;real = driver.call
        driver.call = lambda tool, args, timeout=20: (real(tool, args, timeout), self.answer)[1] if tool == 'type_text' else real(tool, args, timeout)

    def type_step(self, **kw):return self.do('Type the name into "Name"', operation='type_text', text='hello world', **kw)

    def test_partial_with_expect_satisfied_stays_done_with_the_detail(self):
        # Wrong patch: any partial downgrades the outcome even though the independent check passed.
        self.driver.confirm_text = 'Saved'
        r = self.type_step(expect='Saved')
        self.assertEqual((r['status'], r['verified']), ('done', True))
        self.assertEqual(r['delivery_detail'], {'effect': 'partial', 'requested_chars': 19, 'delivered_chars': 0, 'retryable_reported': True})

    def test_partial_without_or_with_unsatisfied_expect_is_delivered_unverified_with_the_hint(self):
        # Wrong patches: plain delivered / deferred delivery_unverified without the warning; trust delivered_chars 0 as no side effect.
        for expect in (None, 'Saved'):
            r = self.type_step(**({'expect': expect} if expect else {}))
            self.assertEqual((r['status'], r['reason'], r['delivery']), ('delivered_unverified', 'type_incomplete_unverified', 'delivered'))
            self.assertIn('0 of 19 chars', r['hint']);self.assertIn('never repeat the type step blindly', r['hint']);self.assertLessEqual(len(r['hint']), 240)
            self.assertEqual(r['delivery_detail']['delivered_chars'], 0);self.assertTrue(r['trace_summary']['follow_up_needed'])

    def test_code_alone_marks_partial_and_a_per_action_effect_counts(self):
        self.answer = {'code': 'type_text_incomplete'}
        self.assertEqual(self.type_step()['status'], 'delivered_unverified')
        self.answer = {'effect': 'ok', 'results': [{'effect': 'partial', 'requested_chars': 3, 'delivered_chars': 1}]}
        r = self.type_step()
        self.assertEqual((r['status'], r['delivery_detail']['retryable_reported']), ('delivered_unverified', False))

    def test_a_plain_answer_has_no_delivery_detail(self):
        self.answer = {'effect': 'unverifiable'}
        self.assertNotIn('delivery_detail', self.type_step())

    def test_partial_is_never_retried_even_when_recovery_reruns_the_pipeline(self):
        # Wrong patch: treat partial as a failure and retry the type (or re-run it after the stale recovery).
        self.driver.shift_at = lambda v: v == 2
        r = self.type_step(expect='Saved')
        typed = [c for c in self.driver.executed if 'text' in c]
        self.assertEqual(len(typed), 1);self.assertEqual(r['status'], 'delivered_unverified')

    def test_a_plan_step_reports_it_and_never_repeats_the_type(self):
        r = self.f.do('Type the name', title='Demo', steps=[{'do': 'type', 'control': 'Name', 'text': 'hello world', 'expect': None}])
        self.assertEqual(r['status'], 'delivered_unverified');self.assertEqual(r['steps'][0]['delivery_detail']['delivered_chars'], 0)
        self.assertIn('read the field before any retry', r['hint']);self.assertEqual(len([c for c in self.driver.executed if 'text' in c]), 1)


class ForgetfulDaemon(FlatDriver):
    """A Driver daemon that forgets its sessions when restarted: every call naming an unstarted session exits 1, like the real CLI."""
    def __init__(self):
        super().__init__();self.known = set();self.starts = 0;self.raw_calls = []
        self.click_delivers_then_fails = False;self.fail_kind = 'exit';self.start_fails = False
    def restart(self):self.known.clear()
    def check(self, tool, session):
        if session not in self.known:raise DriverCallFailed('driver_call_failed: %s exited 1' % tool, tool, self.fail_kind)
    def call(self, tool, args, timeout=20):
        self.raw_calls.append(tool)
        if tool == 'start_session':
            if self.start_fails:raise DriverCallFailed('driver_call_failed: start_session exited 1', tool, 'exit')
            self.known.add(args['session']);self.starts += 1;return {}
        if tool in ('click', 'type_text') and self.click_delivers_then_fails:
            self.executed.append(args);raise DriverCallFailed('driver_call_failed: %s exited 1; the action may have been delivered' % tool, tool, 'exit')
        self.check(tool, args.get('session'))
        return super().call(tool, args, timeout)
    def observe(self, pid, window_id, session, *rest):
        self.raw_calls.append('get_window_state');self.check('get_window_state', session)
        return super().observe(pid, window_id, session, *rest)


class SessionRecovery(DoBase):
    """#31: a Driver daemon restart drops the facade's session; a READ recovers with one start_session and one retry, an action never does."""
    def setUp(self):
        super().setUp();self.driver = ForgetfulDaemon();self.driver.confirm_text = 'Booked Provider E 1:45 PM';self.f.driver = self.driver
    def restarts(self):return [e for e in self.f.events if e['operation'] == 'driver_session_restarted']

    def test_look_after_a_daemon_restart_recovers_with_one_bounded_retry(self):
        # Wrong patch: call start_session once at startup only (the second look then fails driver_call_failed).
        self.assertEqual(self.f.look(title='Demo')['status'], 'ok')
        self.driver.restart()
        r = self.f.look(title='Demo')
        self.assertEqual(r['status'], 'ok');self.assertEqual(self.driver.starts, 2)
        self.assertEqual([(e['tool'], e['recovered']) for e in self.restarts()], [('list_windows', True)])

    def test_a_click_is_never_repeated_and_no_session_restart_follows_a_failed_click(self):
        # Wrong patch: retry every driver_call_failed (a click that failed after delivery would be sent twice).
        self.driver.click_delivers_then_fails = True
        r = self.do(records=rec(ONE), expect='Booked Provider E')
        self.assertEqual((r['status'], r['reason'], r['delivery']), ('failed', 'driver_call_failed', 'uncertain'))
        self.assertEqual(len(self.driver.executed), 1);self.assertEqual(self.driver.raw_calls.count('click'), 1)
        self.assertEqual((self.driver.starts, self.restarts()), (1, []))
        self.assertEqual(r['detail'], {'tool': 'click', 'exit_class': 'exit', 'session_restart_tried': False})

    def test_the_read_is_retried_once_not_until_it_works(self):
        # Wrong patch: loop the restart-and-retry. A daemon that keeps failing costs one start_session and one extra read.
        self.f.look(title='Demo');self.driver.restart()
        real = self.driver.call
        def dead(tool, args, timeout=20):
            if tool == 'start_session':return real(tool, args, timeout)
            raise DriverCallFailed('driver_call_failed: %s exited 1' % tool, tool, 'exit')
        self.driver.call = dead
        r = self.f.look(title='Demo')
        self.assertEqual((r['status'], r['reason'], r['retryable']), ('failed', 'driver_call_failed', True))
        self.assertEqual(r['detail'], {'tool': 'list_windows', 'exit_class': 'exit', 'session_restart_tried': True})
        self.assertEqual([e['recovered'] for e in self.restarts()], [False]);self.assertEqual(self.driver.starts, 2)

    def test_failed_restart_is_reported_and_stops(self):
        self.f.look(title='Demo');self.driver.restart();self.driver.start_fails = True
        r = self.f.look(title='Demo')
        self.assertEqual((r['status'], r['detail']['session_restart_tried']), ('failed', True))
        self.assertEqual(self.driver.raw_calls.count('start_session'), 2)

    def test_a_timeout_is_not_a_lost_session_and_is_not_restarted(self):
        # Wrong patch: restart on any failure class (a timeout retry doubles the wait for a slow app, not a lost session).
        self.f.look(title='Demo');self.driver.restart();self.driver.fail_kind = 'timeout'
        r = self.f.look(title='Demo')
        self.assertEqual((r['status'], r['detail']), ('failed', {'tool': 'list_windows', 'exit_class': 'timeout', 'session_restart_tried': False}))
        self.assertEqual((self.driver.starts, self.restarts()), (1, []))

    def test_only_read_only_tools_may_restart_the_session(self):
        # Wrong patch: let _read wrap any tool. Every mutating tool stays out of READ_TOOLS.
        import core
        self.f.look(title='Demo');self.driver.restart()
        for tool in sorted(core.MUTATING_TOOLS):
            self.assertNotIn(tool, core.READ_TOOLS)
            with self.assertRaises(DriverCallFailed):self.f._read(tool, lambda: self.driver.call('click', {'session': self.f.session}))
        self.assertEqual(self.driver.starts, 1)

    def test_a_refusal_naming_the_session_is_also_a_lost_session_for_a_read(self):
        self.f.look(title='Demo');first = {'n': 0}
        real = self.driver.call
        def refuse(tool, args, timeout=20):
            if tool == 'list_windows' and not first['n']:first['n'] = 1;raise Gap('Driver refused: unknown_session')
            return real(tool, args, timeout)
        self.driver.call = refuse
        self.assertEqual(self.f.look(title='Demo')['status'], 'ok')
        self.assertEqual([e['recovered'] for e in self.restarts()], [True])

    def test_detail_carries_no_driver_output(self):
        self.driver.click_delivers_then_fails = True
        r = self.do(records=rec(ONE), expect='Booked Provider E')
        self.assertEqual(set(r['detail']), {'tool', 'exit_class', 'session_restart_tried'})
