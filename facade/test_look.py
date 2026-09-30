"""cua_look (option B, CE-FACADE-005): a deterministic, read-only look at the strings a page displays.

The live failure it closes: the LLM wrote its filter blind (`duration contains "30"`) and the right slot was displayed as "half-hour".
Each test names the tempting wrong patch it fails. Fakes and captured fixtures only: no Driver, model, desktop or network.
"""
import json
import unittest

import shapes as sh
import test_live_shapes as lv
from core import Facade, MUTATING_TOOLS, DriverCallFailed
from test_core import FakeChooser, FakeVision
from test_do import LineReader, NamedChooser


class Boom:
    """A provider that must never be started: constructing or calling it fails the test."""
    def __init__(self, name):self.name = name
    def __call__(self):raise AssertionError('%s provider started' % self.name)


def facade_for(driver, reader=None, **kw):
    return Facade(driver, reader_factory=(lambda: reader) if reader else Boom('reader'), generic_factory=Boom('chooser'), visual_factory=Boom('visual'),
                  sleep=lambda s: None, **kw)


class LookReal(lv.LiveBase):
    """Against the REAL captured Chrome trees."""
    def look(self, **kw):
        kw.setdefault('title', 'Demo');return self.f.look(**kw)

    def test_the_default_look_calls_no_model_and_no_reader(self):
        # Wrong patch: run NuExtract in the default look "to be helpful" (seconds of latency and a model on the common path).
        f = facade_for(lv.LiveDriver('live_booking_ax.json'))
        r = f.look('Demo')
        self.assertEqual(r['status'], 'ok');self.assertEqual(f.providers, {})
        self.assertNotIn('values', json.dumps(r));self.assertNotIn('extraction', r)
        self.assertEqual([e for e in f.events if e['operation'] in ('read', 'provider_start')], [])

    def test_real_booking_look_shows_the_half_hour_string_the_blind_filter_missed(self):
        # The live failure: duration contains "30" never matched the right slot, displayed as "half-hour". Wrong patch: normalize or hide the string.
        r = self.look()
        self.assertEqual((r['record_kind'], r['counts']['records'], r['status']), ('flat-list', 12, 'ok'))
        slot = next(x for x in r['records'] if 'Telehealth' in x['lines'])
        self.assertEqual(slot['lines'], ['Dr. Morgan Reyes', 'Telehealth', 'half-hour', 'Starts 3:00 PM', 'Video visit'])
        self.assertEqual(slot['controls'], ['Book'])
        self.assertIn('half-hour', json.dumps(r))
        self.assertEqual((r['truncated'], r['notes']), ({'records': 0, 'lines': 0, 'bytes': 0}, []))

    def test_each_record_shows_only_its_own_lines(self):
        # Wrong patch: group by nearest text or by whole-list text (Priya's card mentions Dr. Morgan Reyes but is not his record).
        r = self.look()
        priya = next(x for x in r['records'] if 'Dr. Priya Shah' in x['lines'])
        self.assertEqual(priya['lines'], ['Dr. Priya Shah', 'Follow-up', '30 min', 'Starts 2:15 PM', 'Covering for Dr. Morgan Reyes'])
        self.assertEqual([x['r'] for x in r['records']], ['r%d' % n for n in range(1, 13)])

    def test_real_orders_look_is_table_rows_with_cells_as_lines_and_the_header_apart(self):
        # Wrong patch: dump the JSON cells blob as one line, or list the header cells (and Chrome's second copy of them) as page text.
        f = facade_for(lv.LiveDriver('live_orders_ax.json'))
        r = f.look('Demo')
        self.assertEqual((r['record_kind'], r['counts']['records'], r['header']), ('table-rows', 7, ['Order', 'Item', 'Status', 'Actions']))
        self.assertEqual(r['records'][3], {'r': 'r4', 'controls': ['Track', 'Cancel'], 'lines': ['#1044', 'Walnut desk lamp', 'Processing']})
        self.assertNotIn('Actions', r['text']);self.assertNotIn('Status', r['text'])
        self.assertEqual(r['counts'], {'records': 7, 'controls': 29, 'page_controls': 14, 'non_page_controls': 15})

    def test_the_browser_chrome_is_not_a_page_control(self):
        r = self.look()
        self.assertEqual((r['counts']['non_page_controls'], r['counts']['page_controls']), (1, 12))
        self.assertNotIn('Memory usage', json.dumps(r))

    def test_look_is_read_only_no_click_no_window_move(self):
        # Wrong patch: scroll or click to reveal more of the page, or move the window to make it fit.
        tools = []
        self.driver.on_tool = tools.append
        self.look()
        self.assertEqual(self.driver.executed, [])
        self.assertFalse(set(tools) & MUTATING_TOOLS, tools)
        self.assertLessEqual(set(tools), {'start_session', 'list_windows'})

    def test_look_id_is_stable_for_the_same_strings_and_changes_when_a_line_changes(self):
        # Wrong patch: a random or per-call id (a plan could not prove the page is unchanged), or an id that ignores line text.
        a, b = self.look()['look_id'], self.look()['look_id']
        self.assertEqual(a, b);self.assertRegex(a, r'^lk_[0-9a-f]{10}$')
        def edit(d, els):
            for e in els:
                if e['element_index'] == 22:e['label'] = e['value'] = 'Starts 1:35 PM'
        self.driver.script = edit
        self.assertNotEqual(self.look()['look_id'], a)

    def test_look_id_is_independent_of_control_state_and_the_page_chrome(self):
        # The id names what the LLM SAW (record lines), not memory-usage strings in the tab strip.
        a = self.look()['look_id']
        def chrome(d, els):
            for e in els:
                if e['element_index'] == 381:e['label'] = 'Fixture page - Memory usage - 12.0 MB'
        self.driver.script = chrome
        self.assertEqual(self.look()['look_id'], a)

    def test_heading_text_shown_twice_by_chrome_is_flagged_as_no_proof_for_expect(self):
        # Chrome shows a heading twice (the heading and its text child), so it cannot prove an expect (exactly ONE element). Wrong patch: offer it as page text unmarked.
        r = self.look()
        self.assertIn('Clinic Slots facade-booking-0-1790630020', r['repeated_text'])

    def test_a_window_that_is_not_there_is_refused_without_naming_a_primitive(self):
        r = self.f.look('Nope')
        self.assertEqual((r['status'], r['reason']), ('refused', 'window_not_found'))
        self.assertNotRegex(json.dumps(r), r'cua_(?:windows|observe|read|choose|act|verify)')

    def test_bad_arguments_are_refused_before_any_driver_call(self):
        for kw in ({'max_records': 0}, {'max_records': 501}, {'max_bytes': 100}, {'focus': ''}, {'focus': []}, {'fields': {'a': {}}}, {'fields': {}}, {'max_records': True}):
            calls = []
            self.driver.on_tool = calls.append
            r = self.f.look(title='Demo', **kw)
            self.assertEqual((r['status'], r['reason']), ('refused', 'bad_request'), kw);self.assertEqual(calls, [], kw)
        r = self.f.look(title='Demo', pid=1, window_id=2);self.assertEqual(r['reason'], 'bad_request')
        r = self.f.look();self.assertEqual(r['reason'], 'bad_request')

    def test_a_transient_driver_failure_is_retried_once_and_a_second_is_failed_without_raw_text(self):
        real, seen = self.driver.observe, []
        def flaky(*a):
            seen.append(1)
            if len(seen) <= 1:raise DriverCallFailed('driver_call_failed: get_window_state exited 1; /Users/x/secret')
            return real(*a)
        self.driver.observe = flaky
        self.assertEqual(self.look()['status'], 'ok')
        def broken(*a):raise DriverCallFailed('driver_call_failed: get_window_state exited 1; /Users/x/secret')
        self.driver.observe = broken
        r = self.look()
        self.assertEqual((r['status'], r['reason'], r['retryable']), ('failed', 'driver_call_failed', True))
        self.assertNotIn('secret', json.dumps(r))

    def test_several_page_areas_defer_instead_of_reading_the_wrong_one(self):
        f = facade_for(sh.ShapeDriver(sh.two_web_areas()))
        r = f.look('Demo')
        self.assertEqual((r['status'], r['reason']), ('deferred', 'web_area_ambiguous'))


class LookShapes(unittest.TestCase):
    def look(self, els, script=None, reader=None, **kw):
        d = sh.ShapeDriver(els);d.script = script
        f = facade_for(d, reader);return f, d, f.look(**({'title': 'Demo'} | kw))

    def test_a_100_row_list_is_bounded_and_every_cut_is_counted_never_silent(self):
        # Wrong patch: slice to max_records and say nothing (the LLM then filters a list it thinks it saw whole).
        f, d, r = self.look(sh.invoices())
        self.assertEqual((len(r['records']), r['counts']['records']), (40, 100))
        self.assertEqual(r['truncated']['records'], 60)
        self.assertEqual(len(r['records']) + r['truncated']['records'] + r['truncated']['bytes'], 100)
        self.assertRegex(' '.join(r['notes']), r'60 more records.*focus.*max_records')
        self.assertLessEqual(len(json.dumps(r)), 6000)

    def test_max_bytes_bounds_the_response_and_reports_the_records_it_dropped(self):
        f, d, r = self.look(sh.invoices(), max_records=100, max_bytes=2500)
        self.assertLessEqual(len(json.dumps(r)), 2500)
        self.assertGreater(r['truncated']['bytes'], 0)
        self.assertEqual(len(r['records']) + r['truncated']['bytes'] + r['truncated']['records'], 100)
        self.assertRegex(' '.join(r['notes']), r'did not fit max_bytes=2500')

    def test_raising_max_records_shows_them_all(self):
        f, d, r = self.look(sh.invoices(), max_records=100, max_bytes=30000)
        self.assertEqual((len(r['records']), r['truncated']), (100, {'records': 0, 'lines': 0, 'bytes': 0}))

    def test_long_and_many_lines_are_cut_visibly_and_counted(self):
        # Wrong patch: silently clip (a cut line looks complete). The cut carries an ellipsis and truncated.lines counts it.
        els, web = sh.base();ul = sh.E(els, web, 'AXList')
        for n in 'AB':
            li = sh.E(els, ul, 'AXGroup')
            for k in range(8):sh.E(els, li, 'AXStaticText', 'line %s%d' % (n, k), 'line %s%d' % (n, k))
            sh.E(els, li, 'AXStaticText', 'x' * 100, 'x' * 100);sh.E(els, li, 'AXButton', 'Open')
        f, d, r = self.look(els)
        rec = r['records'][0]
        self.assertEqual(len(rec['lines']), 6);self.assertTrue(all(len(x) <= 60 for x in rec['lines']))
        self.assertGreater(r['truncated']['lines'], 0);self.assertIn('lines were cut', ' '.join(r['notes']))
        longer = self.look(els, script=None)[2]
        self.assertEqual(longer['truncated']['lines'], r['truncated']['lines'])

    def test_a_cut_line_carries_an_ellipsis(self):
        els, web = sh.base();ul = sh.E(els, web, 'AXList')
        for n in 'AB':
            li = sh.E(els, ul, 'AXGroup');sh.E(els, li, 'AXStaticText', 'y' * 90, 'y' * 90);sh.E(els, li, 'AXButton', 'Open')
        r = self.look(els)[2]
        self.assertEqual(r['records'][0]['lines'], ['y' * 59 + '…'])

    def test_focus_keeps_only_records_that_mention_it_and_reports_how_many_were_left_out(self):
        # Wrong patch: focus that drops records without counting them, or that matches the whole list text.
        f, d, r = self.look(sh.invoices(), focus='Northwind')
        self.assertEqual(r['focus'], {'terms': ['northwind'], 'matched': 6, 'filtered_out': 94})
        self.assertEqual(len(r['records']), 6);self.assertTrue(all('Northwind' in ' '.join(x['lines']) for x in r['records']))
        self.assertEqual(r['counts']['records'], 100)
        self.assertEqual([x['r'] for x in r['records']], ['r17', 'r41', 'r55', 'r63', 'r78', 'r90'])  # numbered by page position, stable under focus

    def test_focus_words_are_alternatives_and_a_list_is_phrases(self):
        f, d, words = self.look(sh.invoices(), focus='INV-063 INV-017')
        self.assertEqual([x['r'] for x in words['records']], ['r17', 'r63'])
        f, d, phrases = self.look(sh.invoices(), focus=['northwind traders'])
        self.assertEqual(phrases['focus']['matched'], 5)  # Northwind Trading (r17) is not that phrase

    def test_focus_changes_the_look_id_and_records_over_the_cap_are_counted_after_it(self):
        f, d, all_ = self.look(sh.invoices());f2, d2, some = self.look(sh.invoices(), focus='Northwind')
        self.assertNotEqual(all_['look_id'], some['look_id'])
        f3, d3, capped = self.look(sh.invoices(), focus='2026', max_records=5)
        self.assertEqual((len(capped['records']), capped['truncated']['records'] + 5, capped['focus']['matched']), (5, capped['focus']['matched'], capped['focus']['matched']))
        self.assertEqual(capped['truncated']['records'], capped['focus']['matched'] - 5)

    def test_rows_without_cells_show_their_texts_as_lines(self):
        # Wrong patch: build row lines only from AXCell children (a row whose texts are direct children showed no lines at all).
        import test_core
        d = test_core.FakeDriver();f = facade_for(d)
        r = f.look('Demo')
        self.assertEqual([(x['controls'], x['lines']) for x in r['records']], [(['Inspect first'], ['Used $80']), (['Inspect second'], ['New $90'])])

    def test_a_single_card_is_the_single_record_kind_and_cards_are_cards(self):
        self.assertEqual(self.look(sh.cards(names='B'))[2]['record_kind'], 'single')
        self.assertEqual(self.look(sh.cards())[2]['record_kind'], 'cards')
        r = self.look(sh.cards(label=lambda n: 'Book Dr ' + n))[2]
        self.assertEqual((r['record_kind'], [x['controls'] for x in r['records']]), ('cards', [['Book Dr A'], ['Book Dr B'], ['Book Dr C']]))

    def test_disabled_controls_are_listed_apart_never_as_pressable(self):
        r = self.look(sh.cards(disabled='B'))[2]
        rec = next(x for x in r['records'] if 'Dr. B' in x['lines'])
        self.assertEqual((rec['controls'], rec['disabled']), ([], ['Book']))

    def test_page_controls_and_inputs_outside_the_records_are_listed_for_wizards_and_forms(self):
        f, d, r = self.look(sh.wizard_els(2))
        self.assertEqual((r['record_kind'], r['controls'], r['text']), ('none', ['Back', 'Next', 'Cancel'], ['Step 2 of 3: Billing']))
        els, web = sh.base();sh.E(els, web, 'AXTextField', 'Name', 'Ada', actions=['AXFocus']);sh.E(els, web, 'AXButton', 'Save')
        r = self.look(els)[2]
        self.assertEqual((r['inputs'], r['controls']), ([{'label': 'Name', 'value': 'Ada'}], ['Save']))

    def test_a_role_tagged_dialog_is_listed_with_its_controls_and_lines(self):
        els = sh.cards();sheet = sh.E(els, 0, 'AXSheet', 'Confirm', actions=[]);sh.E(els, sheet, 'AXStaticText', 'Book Dr. B?', 'Book Dr. B?');sh.E(els, sheet, 'AXButton', 'Yes');sh.E(els, sheet, 'AXButton', 'No')
        r = self.look(els)[2]
        self.assertEqual(r['dialogs'], [{'controls': ['Yes', 'No'], 'lines': ['Confirm', 'Book Dr. B?']}])  # the sheet's own title, then its text

    def _canvas_look(self, els):
        regions = {'regions': [{'id': 't0', 'kind': 'text', 'text': 'Sign in', 'bounds': {'x': 10, 'y': 40, 'width': 80, 'height': 24}}]}
        d = sh.ShapeDriver(els);d.perception_payload = {'installed': True, 'healthy': True};d.capture_id = 'cap';d.parse_result = regions
        f = facade_for(d);return f, f.look('Demo')

    def test_native_window_menu_bar_and_window_buttons_are_not_page_controls_so_canvas_is_offered(self):
        # Wrong patches: drop only the AXMenuBar (window buttons keep page_controls at 3 and the canvas route never runs).
        f, r = self._canvas_look(sh.emulator())
        self.assertEqual([t['text'] for t in r['canvas']['text_regions']], ['Sign in'])
        handle = next(iter(f.snapshots));state = f.snapshots[handle]
        self.assertEqual(len(f._content_ids(state)), 2)  # the window and the drawn surface
        self.assertEqual(r.get('controls', []), [])
        self.assertEqual((r['counts']['page_controls'], r['counts']['non_page_controls']), (0, 80))  # 77 menu items + 3 title-bar buttons, none of them page content

    def test_native_toolbar_buttons_stay_page_controls(self):
        # Wrong patch: drop every non-content role including toolbars.
        f, r = self._canvas_look(sh.emulator(toolbar=True))
        self.assertNotIn('canvas', r)
        state = next(iter(f.snapshots.values()))
        labels = {state['nodes'][i].get('label') for i in f._content_ids(state)}
        self.assertTrue({'Back', 'Home'} <= labels);self.assertNotIn('Item 0', labels);self.assertNotIn('Close', labels)

    def test_native_frames_are_checked_against_the_window_not_the_screen(self):
        # Wrong patch: compare frames with the screen. The item at y=10 is on screen but above the window (y=200); the one inside is kept.
        els = sh.emulator(menu_items=0, toolbar=False)
        above = sh.E(els, 0, 'AXMenuItem', 'Above window');els[above]['frame'] = sh.frame(150, 10, 40, 20)
        inside = sh.E(els, 0, 'AXButton', 'Inside window');els[inside]['frame'] = sh.frame(150, 300, 40, 20)
        noframe = sh.E(els, 0, 'AXButton', 'No frame')
        straddle = sh.E(els, 0, 'AXButton', 'Straddles edge');els[straddle]['frame'] = sh.frame(90, 300, 40, 20)  # partly outside: not ENTIRELY outside
        f, _ = self._canvas_look(els)
        state = next(iter(f.snapshots.values()))
        labels = {state['nodes'][i].get('label') for i in f._content_ids(state)}
        # Wrong patch: drop anything not fully inside the window (the straddling control would vanish).
        self.assertEqual(labels & {'Above window', 'Inside window', 'No frame', 'Straddles edge'}, {'Inside window', 'No frame', 'Straddles edge'})

    def test_pages_with_a_web_area_are_not_filtered_by_the_native_rule(self):
        # Wrong patch: apply the native filter to web-area pages too (a web area with a close-button subrole or off-window frame would vanish).
        els, web = sh.base();els[0]['frame'] = sh.frame(100, 200, 400, 800)
        b = sh.E(els, web, 'AXButton', 'Close');els[b].update(subrole='AXCloseButton', frame=sh.frame(0, 0, 10, 10))
        m = sh.E(els, web, 'AXMenuBar', actions=[]);sh.E(els, m, 'AXMenuItem', 'Item')
        f = facade_for(sh.ShapeDriver(els));f.look('Demo')
        state = next(iter(f.snapshots.values()))
        self.assertEqual(f._content_ids(state), {1, b, m, m + 1})

    def test_every_real_chrome_fixture_keeps_the_web_area_subtree_as_content(self):
        # Wrong patch: apply the native-window filter to web pages too (their content is the web area subtree, unchanged).
        from pathlib import Path
        names = sorted(str(p.relative_to(lv.FIX)) for p in lv.FIX.rglob('*ax.json'))
        checked = 0
        for name in names:
            d = lv.LiveDriver(name);f = facade_for(d);f.look('Demo');state = next(iter(f.snapshots.values()))
            web = Facade._top_web_areas(state)
            if not web:continue
            checked += 1
            self.assertEqual(f._content_ids(state), f.subtree(state, 'e'+str(web[0]))[1], name)
        self.assertGreaterEqual(checked, 10)

    def test_canvas_lists_drawn_text_only_when_ax_has_no_pressable_controls_and_perception_is_healthy(self):
        # Wrong patch: OCR text on every look (it never feeds typed values and costs a parse), or on a page with real controls.
        regions = {'regions': [{'id': 't%d' % i, 'kind': 'text', 'text': t, 'bounds': {'x': 10, 'y': y, 'width': 80, 'height': 24}}
                               for i, (t, y) in enumerate([('Toolbar', 10), ('Export', 40), ('Footer', 500), ('Export', 530)])]}
        d = sh.ShapeDriver(sh.canvas());d.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'};d.capture_id = 'cap';d.parse_result = regions
        f = facade_for(d);r = f.look('Demo')
        texts = {t['text']: t for t in r['canvas']['text_regions']}
        self.assertEqual((texts['Export']['count'], sorted(texts['Export']['near'])), (2, ['Footer', 'Toolbar']))
        self.assertEqual(texts['Toolbar']['count'], 1)
        with_ax = sh.ShapeDriver(sh.toolbar());with_ax.perception_payload = d.perception_payload;with_ax.capture_id = 'cap';with_ax.parse_result = regions
        r2 = facade_for(with_ax).look('Demo')
        self.assertNotIn('canvas', r2);self.assertEqual(with_ax.parse_calls, [])
        off = sh.ShapeDriver(sh.canvas());off.capture_id = 'cap'
        r3 = facade_for(off).look('Demo')
        self.assertNotIn('canvas', r3);self.assertIn('Perception', ' '.join(r3['notes']));self.assertEqual(off.parse_calls, [])

    def test_canvas_list_is_bounded_and_says_what_it_left_out(self):
        many = {'regions': [{'id': 't%d' % i, 'kind': 'text', 'text': 'Label %02d' % i, 'bounds': {'x': 10, 'y': 30 * i, 'width': 80, 'height': 20}} for i in range(45)]}
        d = sh.ShapeDriver(sh.canvas());d.perception_payload = {'installed': True, 'healthy': True};d.capture_id = 'cap';d.parse_result = many
        r = facade_for(d).look('Demo')
        self.assertEqual(len(r['canvas']['text_regions']), 30);self.assertIn('15 more drawn texts', ' '.join(r['notes']))

    def test_a_failed_perception_parse_is_a_note_never_a_crash(self):
        d = sh.ShapeDriver(sh.canvas());d.perception_payload = {'installed': True, 'healthy': True};d.capture_id = 'cap'
        def parse_fails(tool):
            if tool == 'parse_visual_regions':raise DriverCallFailed('driver_call_failed: parse_visual_regions exited 1')
        d.on_tool = parse_fails
        r = facade_for(d).look('Demo')
        self.assertEqual(r['status'], 'ok');self.assertIn('could not be read', ' '.join(r['notes']))


class LookFields(unittest.TestCase):
    """fields opt-in: NuExtract per record through the existing read path, in chunks, S4.8 strings."""
    def setUp(self):
        self.reader = LineReader({'vendor': r'(Northwind Trad\w+|Contoso Supply|\w+ \w+)', 'amount': r'(\$[\d,\.]+)'})
        self.driver = sh.ShapeDriver(sh.invoices());self.f = facade_for(self.driver, self.reader)
        self.fields = {'vendor': {'description': 'Vendor'}, 'amount': {'description': 'Amount'}}

    def test_fields_reads_the_shown_records_once_per_chunk_and_adds_values(self):
        # Wrong patch: one reader call for every record (the extractor has a whole-call deadline: 100 rows never fit), or one call per record.
        r = self.f.look('Demo', fields=self.fields, max_records=25)
        self.assertEqual(len(r['records']), 25)
        self.assertEqual(len(self.reader.requests), 3)  # 10 + 10 + 5
        self.assertEqual([len(q['records']) for q in self.reader.requests], [10, 10, 5])
        self.assertEqual(r['extraction'], {'calls': 3, 'chunks': 3, 'records': 25, 'failed': 0, 'skipped': 0})
        self.assertEqual(r['records'][0]['values']['amount'], '$990.88')
        self.assertIn('extract', r['ms_by_stage'])

    def test_fields_reads_only_the_records_it_shows(self):
        r = self.f.look('Demo', fields=self.fields, focus='Northwind')
        self.assertEqual(sum(len(q['records']) for q in self.reader.requests), 6)
        self.assertTrue(all('values' in x for x in r['records']))

    def test_without_fields_the_reader_is_never_called(self):
        self.f.look('Demo');self.assertEqual(self.reader.requests, [])

    def test_a_typed_schema_is_ignored_the_values_are_displayed_strings(self):
        r = self.f.look('Demo', fields={'amount': {'description': 'Amount', 'type': 'money', 'currency': 'USD'}}, max_records=3)
        self.assertEqual(r['records'][0]['values']['amount'], '$990.88');self.assertIn('types are ignored', ' '.join(r['notes']))

    def test_a_failing_chunk_degrades_to_a_counted_note_never_silently(self):
        # Wrong patch: swallow the reader error and show records without values as if they had none.
        self.reader.fail_calls = (2,)
        r = self.f.look('Demo', fields=self.fields, max_records=25)
        self.assertEqual(r['status'], 'ok');self.assertEqual((r['extraction']['failed'], r['extraction']['calls']), (10, 2))
        self.assertEqual(r['truncated']['values'], 10)
        self.assertEqual(sum('values' in x for x in r['records']), 15);self.assertIn('values could not be read', ' '.join(r['notes']))

    def test_the_extraction_budget_stops_further_chunks_and_says_so(self):
        import look
        clock = [0.0]
        f = facade_for(self.driver, self.reader, clock=lambda: clock[0])
        self.reader.on_call = lambda call: clock.__setitem__(0, clock[0] + look.EXTRACT_BUDGET_S + 1)
        r = f.look('Demo', fields=self.fields, max_records=25)
        self.assertEqual((r['extraction']['calls'], r['extraction']['skipped']), (1, 15));self.assertIn('extraction budget', ' '.join(r['notes']))

    def test_values_count_against_max_bytes_and_records_dropped_for_size_are_reported(self):
        r = self.f.look('Demo', fields=self.fields, max_records=100, max_bytes=3000)
        self.assertLessEqual(len(json.dumps(r)), 3000);self.assertGreater(r['truncated']['bytes'], 0)
        self.assertEqual(len(r['records']) + r['truncated']['bytes'] + r['truncated']['records'], 100)


if __name__ == '__main__':unittest.main()


def _thin(els, keep=3):
    """The same window, but its web area holds only `keep` nodes: a page still loading, or any site's holding page."""
    web = next(e['element_index'] for e in els if e.get('role') == 'AXWebArea')
    inside, frontier = set(), {web}
    while frontier:
        frontier = {e['element_index'] for e in els if e.get('parent_index') in frontier};inside |= frontier
    kept = set(sorted(inside)[:keep])
    return [e for e in els if e['element_index'] not in inside or e['element_index'] in kept]


class LookWaitsForAPageThatIsNotReady(lv.LiveBase):
    """Site-agnostic: a thin web area is retried 0.5 s then 1 s later; nothing here names a site, title or phrase."""
    def build(self, thin_for):
        self.naps = []
        d = lv.LiveDriver('live_booking_ax.json')
        d.script = lambda drv, els: _thin(els) if drv.version <= thin_for else None
        return d, Facade(d, reader_factory=Boom('reader'), generic_factory=Boom('chooser'), visual_factory=Boom('visual'), sleep=self.naps.append)

    def test_a_thin_page_that_fills_in_is_looked_at_again_after_half_a_second(self):
        # Wrong patch: report the thin first observation (the agent then sees a holding page and gives up).
        d, f = self.build(thin_for=1)
        r = f.look('Demo')
        self.assertEqual((r['status'], r['counts']['records'], self.naps, d.version), ('ok', 12, [0.5], 2))

    def test_a_page_that_stays_thin_is_retried_twice_then_returned_as_is(self):
        # Wrong patch: loop until ready (unbounded), or return nothing after the retries.
        d, f = self.build(thin_for=99)
        r = f.look('Demo')
        self.assertEqual((self.naps, d.version), ([0.5, 1.0], 3))
        self.assertIn(r['status'], ('ok', 'deferred'))

    def test_a_full_page_is_observed_once_with_no_wait(self):
        # Wrong patch: always sleep before looking (every look pays 1.5 s).
        d, f = self.build(thin_for=0)
        f.look('Demo')
        self.assertEqual((self.naps, d.version), ([], 1))

    def test_a_different_title_makes_no_difference(self):
        # Wrong patch: a title/phrase list (eBay's wording, then the next site's). The rule is the page's structure.
        for title in ('Pardon Our Interruption', 'Anything at all', ''):
            d, f = self.build(thin_for=1)
            d.fix = dict(d.fix, window_title=title)
            f.look(pid=1, window_id=2)
            self.assertEqual(self.naps, [0.5], title)

    def test_only_a_look_waits_never_an_action_observation(self):
        # Wrong patch: retry inside every observe (an action's revalidation would then see a page settle and miss the change).
        d, f = self.build(thin_for=99)
        f.observe(1, 2)
        self.assertEqual((self.naps, d.version), ([], 1))
