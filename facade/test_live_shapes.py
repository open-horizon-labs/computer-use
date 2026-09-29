"""cua_do against REAL captured Chrome AX shapes (facade/fixtures/live_booking_ax.json, live_orders_ax.json).

The tidy fixtures in test_do.py hid the live failures: Chrome advertises AXPress on every static text, cell and row, the
booking page is a flat AXList whose field texts and Book button are siblings, orders rows hold TWO buttons (Track, Cancel)
plus AXColumn projections, and the confirm dialog is page content (no AXSheet) whose buttons can lack AXPress on the first
read. Each test names the tempting wrong patch it fails. Fakes only: no Driver, model, desktop or network.
"""
import copy
import importlib.util
import json
import re
import unittest
from pathlib import Path

from core import Facade, Gap
from test_core import FakeDriver, FakeVision, FakeChooser

FIX = Path(__file__).resolve().parent / 'fixtures'
PRIMITIVES = re.compile(r'cua_(?:windows|observe|read|choose|act|verify|trace|finish)\b')


def load(name):
    return json.loads((FIX / name).read_text())


def add(els, parent, role, **kw):
    els.append({'element_index': max(e['element_index'] for e in els) + 1, 'parent_index': parent, 'role': role,
                'actions': kw.pop('actions', ['AXPress']), 'enabled': True, **kw})


class LiveDriver(FakeDriver):
    """observe() serves a captured tree; `script(driver, elements)` may return a replacement list (post-click content, churn)."""
    def __init__(self, fixture):
        super().__init__()
        self.fix = load(fixture);self.script = None;self.on_tool = None;self.post_click_obs = 0;self.no_press_obs = 0;self.observe_args = []
    def call(self, tool, args, timeout=20):
        if self.on_tool:self.on_tool(tool)
        return super().call(tool, args, timeout)
    def observe(self, *args):
        self.version += 1;self.observe_args.append(args)
        sid = 's' + format(self.version, '08x')
        els = copy.deepcopy(self.fix['elements'])
        if self.script:els = self.script(self, els) or els
        for e in els:e.update(element_token=sid + ':' + str(e['element_index']), enabled=e.get('enabled', True))
        raw = {'snapshot_id': sid, 'pid': 1, 'window_id': 2, 'window_title': self.fix['window_title'], 'elements': els, '_image': b'pixels'}
        if self.capture_id:raw['capture_id'] = self.capture_id
        return raw


class LiveReader:
    """NuExtract stand-in: regexes (multiline) over each record's own text; `missing(call, record, field)` garbles one."""
    def __init__(self, patterns):
        self.patterns, self.requests, self.closed = patterns, [], False;self.missing = lambda call, rid, field: False
    def extract(self, req, sid):
        self.requests.append(copy.deepcopy(req));call = len(self.requests)
        rows = []
        for r in req['records']:
            fields = {}
            for name in req['fields']:
                hit = re.search(self.patterns[name], r['text'], re.M)
                fields[name] = None if not hit or self.missing(call, r['id'], name) else hit.group(1)
            rows.append({'record_id': r['id'], 'fields': fields})
        return {'snapshot_id': sid, 'records': rows}
    def close(self):self.closed = True


class UnknownVision(FakeVision):
    def __init__(self):super().__init__();self.calls = 0
    def inspect(self, snapshot, postcondition, timeout):self.calls += 1;return {'state': 'unknown'}


BOOKING_PATTERNS = {'provider': r'^(Dr\. [^\n]+|Morgan Lee, NP)$', 'service': r'^(Consultation|Follow-up|Telehealth)$',
                    'duration': r'^(\d+ min|half-hour)$', 'start': r'^(Starts [^\n]+)$'}
BOOKING_FIELDS = {'provider': {'description': 'Provider name'}, 'service': {'description': 'Service'},
                  'duration': {'description': 'Duration'}, 'start': {'description': 'Start time'}}
BOOKING_ONE = [{'field': 'provider', 'value': 'Dr. Morgan Reyes'}, {'field': 'service', 'value': 'Follow-up'},
               {'field': 'start', 'op': 'contains', 'value': '1:45 PM'}]  # exactly one of 12 identical Book records
ORDER_PATTERNS = {'order': r'(#\d{4})', 'status': r'(Shipped|Processing|Delivered)',
                  'item': r'(Walnut desk lamp shade \(replacement\)|Walnut desk organizer|Walnut floor lamp|Walnut desk lamp|Brass desk lamp)'}
ORDER_FIELDS = {'order': {'description': 'Order number'}, 'item': {'description': 'Item'}, 'status': {'description': 'Status'}}
ORDER_ONE = [{'field': 'order', 'value': '#1044'}]
# item eq 'Walnut desk lamp' would leave #1046 'Walnut desk lamp shade (replacement)' unknown by design (a longer value containing the target is ambiguous, S4.2)
BOOK_44 = 'e44'
CANCEL_1044 = 'e67'


def booked(text='Booked: Dr. Morgan Reyes, Follow-up, 1:45 PM'):
    def script(driver, els):
        if driver.executed:add(els, 15, 'AXStaticText', label=text, value=text)
    return script


def orders_flow(driver):
    """Click 1 (Cancel) replaces the table with the confirm dialog as PAGE CONTENT (no AXSheet); click 2 restores the table plus a status line."""
    def script(d, els):
        clicks = len(d.executed)
        if clicks == 1:
            d.post_click_obs += 1
            acts = ['AXShowMenu', 'AXScrollToVisible'] if d.post_click_obs <= d.no_press_obs else ['AXPress', 'AXShowMenu', 'AXScrollToVisible']
            keep = [e for e in els if e['element_index'] == 0 or e['element_index'] == 15 or e['element_index'] >= 483]
            text = 'Cancel order #1044 (Walnut desk lamp)?'
            return keep + [{'element_index': 16, 'parent_index': 15, 'role': 'AXStaticText', 'label': text, 'value': text, 'actions': ['AXShowMenu', 'AXScrollToVisible'], 'enabled': True},
                           {'element_index': 17, 'parent_index': 15, 'role': 'AXButton', 'label': 'Yes, cancel order', 'actions': acts, 'enabled': True},
                           {'element_index': 18, 'parent_index': 15, 'role': 'AXButton', 'label': 'Keep order', 'actions': acts, 'enabled': True}]
        if clicks >= 2:add(els, 15, 'AXStaticText', label='Order #1044 cancelled', value='Order #1044 cancelled')
    return script


class LiveBase(unittest.TestCase):
    fixture = 'live_booking_ax.json'
    patterns = BOOKING_PATTERNS
    def setUp(self):
        self.driver = LiveDriver(self.fixture);self.reader = LiveReader(self.patterns);self.chooser = FakeChooser();self.visual = UnknownVision()
        self.starts = [];self.naps = []
        def generic():self.starts.append('generic');return self.chooser
        self.f = Facade(self.driver, generic_factory=generic, reader_factory=lambda: self.reader, visual_factory=lambda: self.visual, sleep=self.naps.append)
    def do(self, goal, **kw):
        kw.setdefault('title', 'Demo');kw.setdefault('expect', None);return self.f.do(goal, **kw)


class LiveBooking(LiveBase):
    def setUp(self):
        super().setUp();self.driver.script = booked()
    def book(self, **kw):
        return self.do('Book the Follow-up slot with Dr. Morgan Reyes that starts at 1:45 PM', records={'fields': BOOKING_FIELDS, 'predicates': BOOKING_ONE},
                       **({'expect': 'Booked:'} | kw))

    def test_live_booking_is_one_call_one_read_no_chooser_one_click(self):
        # F1. Wrong patch: define records by any repeated press-capable node (static text, cells, rows all advertise AXPress) ->
        # records_ambiguous on the real page. The record is the repeated ACTIONABLE control.
        r = self.book()
        self.assertEqual((r['status'], r['judgment'], r['verified']), ('done', 'filter', True))
        self.assertEqual((len(self.reader.requests), self.chooser.requests, self.starts), (1, [], []))
        self.assertEqual((r['selected']['id'], len(self.driver.executed)), (BOOK_44, 1))
        self.assertTrue(self.driver.executed[0]['element_token'].endswith(':44'))
        self.assertEqual(len(self.reader.requests[0]['records']), 12)
        self.assertFalse(r['trace_summary']['follow_up_needed'])

    def test_live_booking_reads_each_record_from_its_own_sibling_texts(self):
        self.book()
        texts = {r['id']: r['text'] for r in self.reader.requests[0]['records']}
        self.assertIn('Starts 1:45 PM', texts[BOOK_44]);self.assertNotIn('Starts 2:30 PM', texts[BOOK_44])
        self.assertNotIn('Covering for', texts[BOOK_44])

    def test_control_needed_lists_only_the_repeated_actionable_labels(self):
        # F1. Wrong patch: dump every repeated element (static texts, cells) into the deferral, which made the LLM drop to primitives.
        def two_kinds(d, els):
            add(els, 18, 'AXButton', label='Details');add(els, 18, 'AXButton', label='Details')
        self.driver.script = two_kinds
        r = self.book()
        self.assertEqual((r['status'], r['reason'], self.driver.executed), ('deferred', 'control_needed', []))
        self.assertEqual({(c['role'], c['label'], c['count']) for c in r['found']['repeated_controls']}, {('AXButton', 'Book', 12), ('AXButton', 'Details', 2)})
        self.assertNotIn('AXStaticText', json.dumps(r['found']));self.assertNotIn('Follow-up', json.dumps(r))
        self.assertIn('control=', r['hint']);self.assertEqual(self.reader.requests, [])

    def test_control_picks_the_repeated_kind_when_several_exist(self):
        # F2. Wrong patch: press the first repeated kind found.
        def two_kinds(d, els):
            booked()(d, els);add(els, 15, 'AXButton', label='Details');add(els, 15, 'AXButton', label='Details')  # a toolbar beside the list, not among its records
        self.driver.script = two_kinds
        r = self.book(control='  book ')
        self.assertEqual((r['status'], r['selected']['id']), ('done', BOOK_44))

    def test_control_that_matches_nothing_defers_control_not_found_with_the_labels(self):
        r = self.book(control='Reserve')
        self.assertEqual((r['reason'], self.driver.executed, self.reader.requests), ('control_not_found', [], []))
        self.assertIn('Book', json.dumps(r['found']))

    def test_expect_absent_from_the_live_page_is_never_done(self):
        r = self.book(expect='Payment received')
        self.assertEqual((r['status'], r['reason'], len(self.driver.executed)), ('deferred', 'delivery_unverified', 1))


class LiveExpect(LiveBase):
    def test_null_expect_ends_delivered_unverified_never_done(self):
        # F3. Wrong patch: let the screenshot model or the goal stand in for expect and report done.
        self.visual = FakeVision()
        self.driver.script = booked()
        r = self.do('Book the Follow-up slot with Dr. Morgan Reyes that starts at 1:45 PM', records={'fields': BOOKING_FIELDS, 'predicates': BOOKING_ONE}, expect=None)
        self.assertEqual((r['status'], r['reason'], r['verified'], r['trace_summary']['follow_up_needed']), ('delivered_unverified', 'expect_not_given', False, True))
        self.assertEqual(len(self.driver.executed), 1);self.assertFalse(PRIMITIVES.search(json.dumps(r)))

    def test_verify_only_never_clicks_and_reports_what_it_can_prove(self):
        self.driver.script = booked()
        self.do('Book the Follow-up slot with Dr. Morgan Reyes that starts at 1:45 PM', records={'fields': BOOKING_FIELDS, 'predicates': BOOKING_ONE}, expect='Booked:')
        clicks = len(self.driver.executed)
        yes = self.do('Check the booking', operation='verify', expect='Booked:')
        no = self.do('Check the booking', operation='verify', expect='Refund issued')
        self.assertEqual((yes['status'], yes['verified'], no['status'], no['reason']), ('observed', False, 'deferred', 'not_verified'))
        self.assertEqual(len(self.driver.executed), clicks)
        self.assertEqual(self.do('x', operation='verify', expect=None)['status'], 'refused')
        self.assertEqual(self.do('x', operation='verify', expect='y', control='Book')['status'], 'refused')


class LiveOrders(LiveBase):
    fixture = 'live_orders_ax.json'
    patterns = ORDER_PATTERNS
    def setUp(self):
        super().setUp();self.driver.script = orders_flow(self.driver)
    def cancel(self, **kw):
        records = {'fields': ORDER_FIELDS, 'predicates': ORDER_ONE, 'identity': ['order']}
        return self.do('Cancel the Walnut desk lamp order that is still Processing', records=records, **({'expect': 'Order #1044 cancelled'} | kw))

    def test_orders_without_control_defers_control_needed_counting_records_not_projections(self):
        # F1/F2. Wrong patch: count the AXColumn projection's buttons too (14 each) or guess Track.
        r = self.cancel()
        self.assertEqual((r['status'], r['reason'], self.driver.executed), ('deferred', 'control_needed', []))
        self.assertEqual({(c['label'], c['count']) for c in r['found']['repeated_controls']}, {('Track', 7), ('Cancel', 7)})
        self.assertIn("'Cancel'", r['hint'])

    def test_orders_control_cancel_selects_the_right_rows_cancel_and_confirms_by_label(self):
        # F2 + P1-2 on the real shape. Wrong patch: press Track (first button) or the first row's Cancel.
        r = self.cancel(control='Cancel', confirm='Yes, cancel order')
        self.assertEqual((r['status'], r['confirmation']['identity']), ('done', 'matched'))
        self.assertEqual(len(self.driver.executed), 2);self.assertTrue(self.driver.executed[0]['element_token'].endswith(':%s' % CANCEL_1044[1:]))
        self.assertTrue(self.driver.executed[1]['element_token'].endswith(':17'))
        self.assertEqual((self.chooser.requests, self.starts, len(self.reader.requests)), ([], [], 2))
        self.assertEqual(len(self.reader.requests[0]['records']), 7)

    def test_dialog_without_confirm_carries_labels_and_a_second_cua_do_finishes_without_primitives(self):
        # F5c. Wrong patch: tell the LLM to use cua_choose/cua_act, or re-run the goal (re-clicking the first control).
        first = self.cancel(control='Cancel')
        self.assertEqual((first['status'], first['reason'], first['delivery'], len(self.driver.executed)), ('deferred', 'confirm_dialog_present', 'delivered', 1))
        self.assertEqual((first['dialog']['controls'], first['dialog']['identity']), (['Yes, cancel order', 'Keep order'], 'matched'))
        self.assertFalse(PRIMITIVES.search(json.dumps(first)), PRIMITIVES.findall(json.dumps(first)))
        second = self.do('Click "Yes, cancel order"', expect='Order #1044 cancelled')
        self.assertEqual((second['status'], second['judgment'], len(self.driver.executed)), ('done', 'exact', 2))
        self.assertTrue(self.driver.executed[1]['element_token'].endswith(':17'))  # the dialog's button, never the row's Cancel again
        self.assertEqual(len(self.reader.requests), 2);self.assertEqual(self.chooser.requests, [])

    def test_dialog_buttons_without_press_are_reobserved_once_then_deferred_by_label(self):
        # F4. Wrong patch: click blind, or claim the control is not unique when it is merely not press-capable in this snapshot.
        self.driver.no_press_obs = 99
        r = self.cancel(control='Cancel', confirm='Yes, cancel order')
        self.assertEqual((r['status'], r['reason'], len(self.driver.executed)), ('deferred', 'control_not_pressable', 1))
        self.assertEqual([a['kind'] for a in r['trace_summary']['attempts']], ['reobserve_unpressable_control'])

    def test_press_action_missing_only_on_the_first_read_is_recovered_by_one_reobserve(self):
        self.driver.no_press_obs = 1
        r = self.cancel(control='Cancel', confirm='Yes, cancel order')
        self.assertEqual((r['status'], len(self.driver.executed)), ('done', 2))
        self.assertEqual([a['kind'] for a in r['trace_summary']['attempts']], ['reobserve_unpressable_control'])

    def test_exact_call_on_an_unpressable_control_is_reobserved_once_and_never_called_unique(self):
        # F4. Wrong patch: fall back to the chooser over hundreds of page and menu nodes, or click a control the Driver cannot press.
        self.driver.no_press_obs = 99
        self.cancel(control='Cancel')
        before = self.driver.version
        r = self.do('Click "Yes, cancel order"', expect='Order #1044 cancelled')
        self.assertEqual((r['status'], r['reason'], len(self.driver.executed)), ('deferred', 'control_not_pressable', 1))
        self.assertEqual((self.driver.version - before, self.chooser.requests), (2, []))  # the observation and ONE reobserve
        self.assertEqual([a['kind'] for a in r['trace_summary']['attempts']], ['reobserve_unpressable_control'])

    def test_exact_reports_a_control_without_press_as_not_press_capable_not_as_a_duplicate(self):
        # F4 root cause: choose(mode=exact) offers only press-capable nodes, so a dialog button whose AXPress Chrome omitted
        # looked absent and was reported exact_target_not_unique while cua_do (which counted by label) called it unique.
        self.driver.no_press_obs = 99
        self.cancel(control='Cancel')
        snap = self.f.observe(1, 2)['snapshot']
        result = self.f.choose(snap, 'Confirm', mode='exact', exact_name='Yes, cancel order', exact_role='AXButton')
        self.assertEqual((result['status'], result['decision']['reason']), ('defer', 'exact_target_not_unique'))
        self.assertEqual(result['diagnostic'], {'observed_named': 1, 'offered_named': 0, 'not_press_capable': 1})
        self.driver.no_press_obs = 0
        snap = self.f.observe(1, 2)['snapshot']
        ok = self.f.choose(snap, 'Confirm', mode='exact', exact_name='Yes, cancel order', exact_role='AXButton')
        self.assertEqual((ok['status'], ok['selected_id']), ('selected', 'e17'))

    def test_a_restored_table_after_the_dialog_click_is_not_a_second_dialog(self):
        # Wrong patch: any new controls after a click are a dialog (the table's repeated Track/Cancel come back as "new").
        self.cancel(control='Cancel')
        r = self.do('Click "Yes, cancel order"', expect='Order #1044 cancelled')
        self.assertEqual((r['status'], r['delivery']), ('done', 'delivered'))
        self.assertNotIn('dialog', r)


class Hints(LiveBase):
    def test_no_deferral_or_refusal_sends_the_llm_to_a_primitive_tool(self):
        # F5a. Wrong patch: hints that say "use cua_choose / cua_verify / cua_observe" (those tools are not visible by default).
        book = lambda **kw: self.do('Book the Follow-up slot with Dr. Morgan Reyes that starts at 1:45 PM', records={'fields': BOOKING_FIELDS, 'predicates': BOOKING_ONE}, **kw)
        results = [book(expect='Booked:', title='Nope'), book(expect='Booked:', control='Reserve'), book(expect=None, budget_s=0)]
        self.driver.script = booked()
        results += [book(expect='never shown'), book(expect=None), self.do('Book it', expect='x', accept_unknown=['e1'])]
        self.driver.script = None
        results.append(self.do('check', operation='verify', expect='never shown'))
        self.setUp();self.reader.missing = lambda call, rid, field: rid == 'e44' and field == 'duration'
        results.append(self.do('Book the 45 min', records={'fields': BOOKING_FIELDS, 'predicates': [{'field': 'provider', 'value': 'Dr. Morgan Reyes'}, {'field': 'duration', 'value': '30 min'}]}, expect='Booked:'))
        for r in results:
            self.assertFalse(PRIMITIVES.search(json.dumps(r)), (r.get('reason'), PRIMITIVES.findall(json.dumps(r))))
        self.assertGreaterEqual(len({r.get('reason') for r in results}), 5)


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'needs mcp')
class Schema(unittest.TestCase):
    def test_expect_is_a_required_nullable_parameter_and_the_description_never_invites_skipping_it(self):
        # F3. Wrong patch: keep expect optional (the live LLM never passed it, so every result was unverified).
        import asyncio
        import server
        tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == 'cua_do')
        self.assertIn('expect', tool.inputSchema['required']);self.assertIn('goal', tool.inputSchema['required'])
        kinds = [x.get('type') for x in tool.inputSchema['properties']['expect'].get('anyOf', [])]
        self.assertIn('null', kinds);self.assertIn('string', kinds)
        doc = tool.description.lower()
        self.assertIn('required', doc);self.assertIn('e.g. "booked:"', doc)
        self.assertNotRegex(doc, r'expect (?:is )?optional|may omit|can omit|skip expect|optionally pass expect')
        self.assertEqual([t.name for t in asyncio.run(server.mcp.list_tools())], ['cua_do'])


if __name__ == '__main__':unittest.main()
