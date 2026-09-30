"""CE-FACADE-007 slice 2 (#33, #29): cua_look reads the page text from the Driver's semantic_v2 snapshot beside the AX tree, bounded.

The AX tree is the REAL captured Chrome booking page; the Driver's browser tools are faked with the response shape documented in the Driver's
browser-semantic-snapshots reference (page.url/title, outline, refs, content_refs, snapshot.complete/omitted/continuation). No desktop, browser or
network. Each test names the tempting wrong patch it fails.
"""
import json
import unittest

import dom
import test_browser as tb
import test_live_shapes as lv
from core import DriverCallFailed, MUTATING_TOOLS


class SemanticDriver(tb.BrowserDriver):
    """BrowserDriver whose semantic snapshot is scripted: `segments` is a list of responses served in order (the first to the snapshot, the rest to
    continuations); `hang` (seconds) makes a semantic call raise the Driver's timeout unless the caller's timeout exceeds it; `took` advances
    the injected clock per call so the total budget is exercised."""
    def __init__(self, clock=None):
        super().__init__()
        self.segments = [];self.hang = None;self.took = 0;self.clock = clock;self.timeouts = [];self.semantic_args = [];self.bind_hang = False
    def call(self, tool, args, timeout=20):
        if tool == 'get_browser_state':
            self.timeouts.append(timeout)
            if self.took and self.clock:self.clock.now += min(self.took, timeout)
            if 'target_id' not in args:
                if self.bind_hang:raise DriverCallFailed('driver_call_failed: get_browser_state timed out after %ss' % timeout, tool, 'timeout')
            elif args.get('snapshot_format') == 'semantic_v2' and self.segments is not None and (self.segments or self.hang):
                self.semantic_args.append(dict(args))
                if self.hang and timeout < self.hang:
                    raise DriverCallFailed('driver_call_failed: get_browser_state timed out after %ss' % timeout, tool, 'timeout')
                if self.segments:return self.segments.pop(0)
        return super().call(tool, args, timeout)


class Clock:
    def __init__(self):self.now = 1000.0
    def __call__(self):return self.now


def snap(outline, complete=True, continuation=None, omitted=None, url='https://shop.example/list', refs=None):
    return {'status': 'ok', 'mode': 'snapshot', 'target_id': 'bt-1', 'tab_id': 'tab-1',
            'snapshot': {'id': 'p1', 'format': 'semantic_v2', 'complete': complete, 'scope': 'viewport', 'selected_nodes': 10, 'total_nodes': 10, 'node_budget': 300,
                         'omitted': {'css_hidden': 0, 'offscreen': 0, 'page_occluded': 0, 'no_layout': 0, 'unknown': 0, 'budget': 0, 'unprovable_frame': 0, **(omitted or {})},
                         'continuation': continuation},
            'page': {'url': url, 'title': 'Booking'}, 'outline': outline, 'refs': refs or [], 'content_refs': [], 'oopif': {'status': 'attached', 'frames': 0}}


def outline_of(records, extra=None, drop=()):
    """The page as the Driver's outline would show it: one listitem per AX record, each line a text node; `extra` {record index: [dom-only lines]}; `drop` AX lines the DOM lacks."""
    rows = ['- main', '  - list']
    for n, rec in enumerate(records):
        rows.append('    - listitem')
        for line in rec['lines'] + (extra or {}).get(n, []):
            if line not in drop:
                rows.append('      - text "%s"' % line.replace('"', '\\"'))
        rows.append('      - button "Book"')
    return '\n'.join(rows)


class Base(lv.LiveBase):
    def setUp(self):
        super().setUp()
        self.clock = Clock();self.driver = SemanticDriver(self.clock)
        self.f = lv.Facade(self.driver, generic_factory=lambda: self.chooser, reader_factory=lambda: self.reader, visual_factory=lambda: self.visual, sleep=self.naps.append, clock=self.clock)
        self.ax = self.f.look('Demo')  # the AX-only look: the driver serves no semantic snapshot yet
    def look(self, **kw):
        return self.f.look('Demo', **kw)


class Bounded(Base):
    def test_a_hanging_semantic_call_is_bounded_and_the_look_falls_back_to_ax(self):
        # #29: the semantic call ran 120 s with no output. Wrong patch: call get_browser_state with the Driver's default timeout (or none) and wait for it.
        self.driver.hang = 120;self.driver.timeouts.clear()
        r = self.look()
        self.assertEqual(r['status'], 'ok', 'a semantic timeout is never a transport failure')
        self.assertEqual(r['degraded'], 'semantic_timeout')
        self.assertTrue(any('accessibility tree only' in n for n in r['notes']), r['notes'])
        self.assertTrue(self.driver.timeouts and all(t <= dom.SEMANTIC_TIMEOUT_S for t in self.driver.timeouts), self.driver.timeouts)
        self.assertLess(dom.SEMANTIC_TIMEOUT_S, 20, 'well under the look budget')
        self.assertEqual((r['records'], r['look_id']), (self.ax['records'], self.ax['look_id']), 'the AX look is unchanged')
        self.assertEqual(r['sources'], {'ax': True, 'dom': False})

    def test_a_bind_that_hangs_is_bounded_the_same_way(self):
        self.driver.bind_hang = True;self.driver.timeouts.clear()
        r = self.look()
        self.assertEqual((r['status'], r['degraded']), ('ok', 'semantic_timeout'))
        self.assertTrue(all(t <= dom.SEMANTIC_TIMEOUT_S for t in self.driver.timeouts), self.driver.timeouts)
        self.assertEqual(self.driver.semantic_args, [], 'no snapshot is attempted after a bind that timed out')

    def test_the_total_semantic_budget_bounds_continuations(self):
        # Wrong patch: follow continuations until the snapshot is complete (an oversized page would then read for minutes).
        self.driver.took = 4
        self.driver.segments = [snap(outline_of(self.ax['records']), complete=False, continuation='bc-%d' % n) for n in range(6)]
        self.driver.timeouts.clear()
        r = self.look()
        self.assertEqual(self.driver.timeouts, [6.0, 6.0, 2.0], 'each call is capped by what is left of the budget')
        self.assertEqual(len(self.driver.semantic_args), 2, 'the snapshot and ONE continuation: the budget is spent')
        self.assertEqual(r['sources']['segments'], 2);self.assertFalse(r['sources']['dom_complete'])
        self.assertTrue(any('partial' in n for n in r['notes']), r['notes'])

    def test_timing_is_recorded_not_a_call_count_change_for_the_llm(self):
        self.driver.segments = [snap(outline_of(self.ax['records']))]
        r = self.look()
        self.assertIn('dom', r['ms_by_stage'])
        self.assertEqual(r['look_id'], self.ax['look_id'])

    def test_a_refusal_is_a_typed_degradation_not_a_failure(self):
        self.driver.refuse = {'get_browser_state': 'browser_requires_setup'}
        r = self.look()
        self.assertEqual((r['status'], r['degraded']), ('ok', 'semantic_refused'))
        self.assertIn('browser_requires_setup', json.dumps(r['notes']))
        self.assertEqual(r['records'], self.ax['records'])

    def test_a_refusal_never_triggers_setup_from_a_read_only_look(self):
        # Wrong patch: reuse browser.bind(), which prepares the existing-profile endpoint: a look would change the user's browser.
        self.driver.refuse = {'get_browser_state': 'browser_requires_setup'}
        self.look()
        self.assertEqual(self.driver.called('browser_prepare'), [])

    def test_a_window_the_driver_does_not_bind_looks_as_before(self):
        # An answer with no target_id is not a browser-bound page: no degraded flag, no sources, the shape is unchanged.
        r = lv.Facade(lv.LiveDriver('live_booking_ax.json'), generic_factory=lambda: self.chooser, reader_factory=lambda: self.reader, visual_factory=lambda: self.visual, sleep=self.naps.append).look('Demo')
        self.assertNotIn('degraded', r);self.assertNotIn('sources', r);self.assertNotIn('sources_disagree', r)
        self.assertEqual(r['truncated'], {'records': 0, 'lines': 0, 'bytes': 0})


    def test_a_snapshot_with_no_page_text_is_reported_not_compared(self):
        # Wrong patch: compare against an empty outline and report every AX line as a disagreement.
        self.driver.segments = [snap('')]
        r = self.look()
        self.assertEqual((r['status'], r['degraded']), ('ok', 'semantic_empty'))
        self.assertNotIn('sources_disagree', r)


class Sources(Base):
    def setUp(self):
        super().setUp()
        self.priya = next(n for n, r in enumerate(self.ax['records']) if 'Dr. Priya Shah' in r['lines'])

    def with_dom(self, **kw):
        self.driver.segments = [snap(outline_of(self.ax['records'], **kw))]
        return self.look()

    def test_a_dom_line_the_ax_look_omits_is_shown_on_its_record_and_counted(self):
        # The eBay case: the price is in the DOM and not in the AX tree. Wrong patch: show only AX (the price is lost) or only DOM (no record structure).
        r = self.with_dom(extra={self.priya: ['Copay $25']})
        rec = r['records'][self.priya]
        self.assertEqual(rec['dom_lines'], ['Copay $25'])
        self.assertEqual(rec['lines'], self.ax['records'][self.priya]['lines'], 'the AX lines stay exactly as the AX look showed them')
        self.assertEqual(r['sources_disagree']['dom_only'], 1);self.assertEqual(r['sources_disagree']['in_records'], 1)
        self.assertEqual(r['sources'], {'ax': True, 'dom': True, 'page': {'url': 'https://shop.example/list', 'title': 'Booking'}, 'dom_complete': True, 'segments': 1})
        self.assertTrue(any('evidence only' in n for n in r['notes']), r['notes'])
        self.assertEqual([x for n, x in enumerate(r['records']) if n != self.priya and 'dom_lines' in x], [])

    def test_the_dom_never_replaces_or_drops_the_ax_look(self):
        # Wrong patch (two): prefer the DOM silently (its outline replaces the AX lines), or drop AX records when a DOM snapshot is present.
        r = self.with_dom(extra={self.priya: ['Copay $25']}, drop={'Video visit'})
        self.assertEqual([x['lines'] for x in r['records']], [x['lines'] for x in self.ax['records']])
        self.assertEqual(r['counts'], self.ax['counts']);self.assertEqual(r['look_id'], self.ax['look_id'])
        self.assertGreaterEqual(r['sources_disagree']['ax_only'], 1, 'AX lines the DOM lacks are counted, not removed')
        self.assertTrue(any('not in the DOM outline' in n for n in r['notes']), r['notes'])

    def test_agreement_is_reported_as_zero_disagreement_not_omitted(self):
        r = self.with_dom()
        self.assertEqual((r['sources_disagree']['dom_only'], r['sources_disagree']['ax_only']), (0, 0))
        self.assertGreater(r['sources_disagree']['compared_ax_lines'], 0)
        self.assertFalse(any('dom_lines' in x for x in r['records']))

    def test_a_dom_only_line_no_record_owns_is_unplaced_not_guessed(self):
        # Wrong patch: attach a stray DOM line to the nearest record.
        outline = outline_of(self.ax['records']) + '\n- paragraph "Free shipping on orders over $50"'
        self.driver.segments = [snap(outline)]
        r = self.look()
        self.assertEqual(r['dom_unplaced'], ['Free shipping on orders over $50'])
        self.assertEqual((r['sources_disagree']['dom_only'], r['sources_disagree']['in_records']), (1, 0))
        self.assertFalse(any('dom_lines' in x for x in r['records']))

    def test_a_line_shared_by_several_records_does_not_place_a_dom_line(self):
        # 'Follow-up' is in many records; a group that matches two records equally must not pick one.
        outline = '- main\n  - list\n    - listitem\n      - text "Follow-up"\n      - text "30 min"\n      - text "Limited offer"'
        self.driver.segments = [snap(outline)]
        r = self.look()
        self.assertEqual(r['dom_unplaced'], ['Limited offer'])

    def test_the_look_id_ignores_dom_lines_so_a_plan_can_still_prove_the_page(self):
        # The executor re-proves the look on the AX tree only. Wrong patch: hash dom_lines into look_id (every plan would stop page_changed_since_look).
        r = self.with_dom(extra={self.priya: ['Copay $25']})
        plan = self.f.do('Book Dr. Priya Shah', title='Demo', expect=None, look_id=r['look_id'],
                         steps=[{'do': 'press', 'where': {'lines': [{'line': 'eq', 'value': 'Dr. Priya Shah'}, {'line': 'eq', 'value': '30 min'}]}, 'control': 'Book', 'expect': None}])
        self.assertEqual(plan['status'], 'delivered_unverified', plan)
        self.assertEqual(len(self.driver.executed), 1)

    def test_a_filter_over_a_dom_only_line_selects_nothing(self):
        # Actions stay on the AX path: a where.lines condition over text only the DOM showed must not click. Wrong patch: match dom_lines in the executor.
        r = self.with_dom(extra={self.priya: ['Copay $25']})
        plan = self.f.do('Book the $25 copay slot', title='Demo', expect=None, look_id=r['look_id'],
                         steps=[{'do': 'press', 'where': {'lines': [{'line': 'contains', 'value': 'Copay $25'}]}, 'control': 'Book', 'expect': None}])
        self.assertNotIn(plan['status'], ('done', 'delivered_unverified'), plan)
        self.assertEqual(plan['reason'], 'no_matching_record')
        self.assertEqual(self.driver.executed, [])

    def test_partial_snapshots_report_what_was_omitted(self):
        self.driver.segments = [snap(outline_of(self.ax['records']), complete=False, omitted={'offscreen': 82, 'budget': 18})]
        r = self.look()
        self.assertEqual(r['sources']['dom_omitted'], {'offscreen': 82, 'budget': 18})
        self.assertFalse(r['sources']['dom_complete'])

    def test_a_continuation_is_used_once_and_only_with_the_snapshot_it_came_from(self):
        self.driver.segments = [snap(outline_of(self.ax['records']), complete=False, continuation='bc-1'), snap('- text "More"', complete=True)]
        r = self.look()
        first, second = self.driver.semantic_args
        self.assertNotIn('continuation', first);self.assertEqual(second['continuation'], 'bc-1')
        self.assertEqual({k: v for k, v in second.items() if k != 'continuation'}, first, 'same target, tab, format; no new query or scope')
        self.assertTrue(r['sources']['dom_complete']);self.assertEqual(r['sources']['segments'], 2)

    def test_the_look_only_reads(self):
        # Wrong patch: act through DOM refs (browser_click/type) or navigate to get a fresher snapshot.
        self.driver.segments = [snap(outline_of(self.ax['records']), refs=[{'ref': 'p1:8', 'role': 'button', 'name': 'Book', 'actions': ['click']}])]
        tools = []
        self.driver.on_tool = tools.append
        self.look()
        self.assertEqual(self.driver.executed, [])
        self.assertFalse(set(tools) & MUTATING_TOOLS, tools)
        self.assertEqual([t for t, _ in self.driver.browser_calls if t != 'get_browser_state'], [])
        self.assertTrue(all(a.get('snapshot_format') == 'semantic_v2' or 'pid' in a for a in (x for t, x in self.driver.browser_calls)))

    def test_the_response_stays_within_the_look_byte_bound(self):
        r = self.with_dom(extra={n: ['Copay $%d' % n, 'Insurance accepted', 'Parking validated'] for n in range(12)})
        self.assertLessEqual(len(json.dumps(r)), 6000 + 400)
        self.assertEqual(r['truncated']['dom_lines'], 0)


class Outline(unittest.TestCase):
    def test_the_documented_outline_lines_parse(self):
        nodes = dom.parse_outline('- heading "Message"\n- textbox "Reply body"\n  - paragraph: Some text\n- text "say \\"hi\\""')
        self.assertEqual([n['text'] for n in nodes], [['Message'], ['Reply body'], ['Some text'], ['say "hi"']])
        self.assertEqual([n['parent'] for n in nodes], [None, None, 1, None])

    def test_garbage_yields_no_lines_not_a_guess(self):
        self.assertEqual(dom.parse_outline('<<<not an outline>>>\n???'), [])


if __name__ == '__main__':
    unittest.main()
