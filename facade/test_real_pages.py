"""The 17 suite pages as REAL Chrome exposed them (live capture 2026-09-28, read-only, no clicks; facade/fixtures/real/, sanitized, raw driver format).

Asserts per page what the look and cua_do discovery must produce, and the three defects the capture found in the shared record inference (D1 the page's
heading level and title leaking into the first record of a flat list, D2 'selected: false' noise on every plain button, D3 heading levels in the page text).
Facts the capture established (docs/PLAN-B.md): the Driver exposes only actions, depth, element_index, element_token, enabled, frame, in_web_content, label,
parent_index, role, screenshot_frame, selected and value: checked/expanded/pressed/current/busy do not exist on real Chrome (radio state is value '0'/'1' and selected).
Fakes only: no Driver, model, desktop or network.
"""
import json
import unittest

import look as lk
import real_driver as rd
from core import Facade
from test_core import FakeChooser
from test_live_shapes import UnknownVision


def facade_for(page, script=None):
    d = rd.RealDriver(page);d.script = script
    return Facade(d, generic_factory=FakeChooser, visual_factory=UnknownVision, sleep=lambda s: None), d


def looked(page, **kw):
    f, d = facade_for(page);return f, d, f.look('Demo', **kw)


def lines(look):
    return [r['lines'] for r in look['records']]


def state_of(f, d):
    return f.state(f.observe(1, 2)['snapshot'])


class EveryPage(unittest.TestCase):
    def test_all_seventeen_pages_load_and_are_complete_trees(self):
        self.assertEqual(len(rd.PAGES), 17)
        for page in rd.PAGES:
            tree = rd.load(page)
            self.assertTrue(tree['elements'] and tree['window_title'], page)
            keys = {k for e in tree['elements'] for k in e}
            self.assertLessEqual(keys, {'element_index', 'parent_index', 'role', 'label', 'value', 'actions', 'enabled', 'depth', 'frame', 'selected', 'in_web_content', 'screenshot_frame', 'element_token'}, page)

    def test_the_look_works_on_every_page_and_never_reports_a_silent_cut(self):
        for page in rd.PAGES:
            f, d, look = looked(page)
            self.assertEqual(look['status'], 'ok', page);self.assertIs(look['untrusted_page_text'], True)
            self.assertLessEqual(len(json.dumps(look)), 6000, page)
            shown = len(look['records']);t = look['truncated']
            self.assertEqual(shown + t['records'] + t['bytes'], look['counts']['records'], page)  # nothing dropped without being counted
            self.assertEqual(d.executed, [], page)

    def test_inert_state_keys_do_not_exist_on_real_chrome(self):
        # The look and the look_id also cover checked/expanded/pressed/current/busy: on real Chrome those keys never exist (documented as inert).
        for page in rd.PAGES:
            for e in rd.load(page)['elements']:
                self.assertFalse({'checked', 'expanded', 'pressed', 'current', 'busy', 'description'} & set(e), (page, e['role']))


class RecordPages(unittest.TestCase):
    def test_booking_is_a_flat_list_of_twelve_with_the_half_hour_slot(self):
        f, d, look = looked('booking')
        self.assertEqual((look['record_kind'], look['counts']['records']), ('flat-list', 12))
        self.assertEqual(lines(look)[9], ['Dr. Morgan Reyes', 'Telehealth', 'half-hour', 'Starts 3:00 PM', 'Video visit'])
        self.assertEqual(lines(look)[0], ['Dr. Morgan Reyes', 'Consultation', '60 min', 'Starts 1:30 PM'])
        self.assertTrue(all(r['controls'] == ['Book'] for r in look['records']))
        roots, targets, found, why, _ = f.discover_records(state_of(f, d), 'click', None)
        self.assertEqual((len(roots), why), (12, None))

    def test_orders_is_table_rows_with_track_and_cancel(self):
        f, d, look = looked('orders')
        self.assertEqual((look['record_kind'], look['counts']['records'], look['header']), ('table-rows', 7, ['Order', 'Item', 'Status', 'Actions']))
        self.assertEqual(look['records'][3], {'r': 'r4', 'controls': ['Track', 'Cancel'], 'lines': ['#1044', 'Walnut desk lamp', 'Processing']})
        st = state_of(f, d)
        self.assertEqual(f.discover_records(st, 'click', None)[3], 'control_needed')
        roots, targets, _, why, _ = f.discover_records(st, 'click', 'Cancel')
        self.assertEqual((len(roots), len(targets), why), (7, 7, None))

    def test_invoices_reports_the_byte_cap_and_does_not_silently_drop(self):
        f, d, look = looked('invoices')
        self.assertEqual((look['record_kind'], look['counts']['records']), ('table-rows', 100))
        self.assertGreater(look['truncated']['records'] + look['truncated']['bytes'], 0)
        self.assertRegex(' '.join(look['notes']), r'more records|did not fit')
        self.assertEqual(look['records'][0]['lines'], ['INV-001', 'Proseware Inc', '$990.88', '2026-07-21'])
        wide = f.look('Demo', max_records=100, max_bytes=30000)
        self.assertEqual((len(wide['records']), wide['truncated']), (100, {'records': 0, 'lines': 0, 'bytes': 0}))
        for cap in (1500, 2500, 4000):  # max_bytes bounds the COMPLETE response (the capture: 6015 > 6000 when it bounded an estimate)
            small = f.look('Demo', max_records=100, max_bytes=cap)
            self.assertLessEqual(len(json.dumps(small)), cap, cap)
            self.assertEqual(len(small['records']) + small['truncated']['records'] + small['truncated']['bytes'], 100)
        focus = f.look('Demo', focus='Northwind')
        self.assertEqual(focus['focus']['matched'], 6);self.assertEqual(focus['counts']['records'], 100)

    def test_flat_ax_first_record_carries_neither_the_heading_nor_its_level(self):
        # D1. Wrong patch: leave Chrome's heading (value = its LEVEL '1', text = the window title) glued to the first record of the flat list.
        f, d, look = looked('flat_ax')
        self.assertEqual((look['record_kind'], look['counts']['records']), ('flat-list', 6))
        self.assertEqual(lines(look)[0], ['Priya Nair', 'Mobile +1 404 555 0142'])
        self.assertNotIn('1', [x for r in lines(look) for x in r])
        self.assertNotIn('Contacts', json.dumps(lines(look)))
        self.assertEqual(lines(look)[1], ['Priya Nair', 'Work +1 404 555 0177'])

    def test_ax_dup_records_keep_their_own_section_context_and_field_values(self):
        f, d, look = looked('ax_dup')
        self.assertEqual((look['record_kind'], look['counts']['records']), ('flat-list', 2))
        self.assertEqual(lines(look)[0], ['Notification preferences'])
        self.assertEqual(lines(look)[1], ['Shipping address', 'Street', 'field: Street = 14 Elm Street', 'City', 'field: City = Springfield'])

    def test_nested_records_have_no_level_numerals_and_keep_the_section_headings(self):
        f, d, look = looked('nested')
        self.assertEqual((look['record_kind'], look['counts']['records']), ('flat-list', 8))
        first = lines(look)[0]
        self.assertFalse([x for x in first if x.isdigit()], first);self.assertNotIn('Directory capture-nested', first)
        self.assertEqual(first, ['Engineering', 'Platform', 'Sam Okafor'])  # genuine section headings that precede the record's own fields are good context

    def test_the_page_text_has_no_heading_level_numerals(self):
        # D3. Wrong patch: a heading's value (its level) taken as page text.
        for page in ('booking', 'orders', 'flat_ax', 'ax_dup', 'nested', 'dynamic', 'swap', 'form', 'wizard', 'destructive'):
            f, d, look = looked(page)
            self.assertFalse([t for t in look['text'] if t.isdigit()], (page, look['text']))
        f, d, look = looked('flat_ax')
        self.assertIn('Contacts capture-flat_ax', look['text'])  # the title heading is page text, not a record's

    def test_dynamic_and_swap_are_table_rows(self):
        f, d, dyn = looked('dynamic');f2, d2, swap = looked('swap')
        self.assertEqual((dyn['record_kind'], dyn['counts']['records'], swap['record_kind'], swap['counts']['records']), ('table-rows', 6, 'table-rows', 5))
        self.assertIn('Schedule updated: 3 new requests', dyn['text'])
        self.assertEqual(lines(swap)[0], ['Printer toner low'])

    def test_plain_buttons_add_no_state_noise_to_any_record(self):
        # D2. Wrong patch: emit a state line for every control that has selected:false (Chrome sets it on every button).
        for page in ('booking', 'orders', 'invoices', 'flat_ax', 'ax_dup', 'nested', 'dynamic', 'swap'):
            f, d, look = looked(page)
            self.assertNotIn('state:', json.dumps(look), page);self.assertNotIn('unselected', json.dumps(look), page)

    def test_a_where_lines_plan_cannot_select_the_first_flat_record_by_the_page_title(self):
        f, d, look = looked('flat_ax')
        r = f.do('Call the contact', title='Demo', expect=None, look_id=look['look_id'], steps=[{'do': 'press', 'where': {'lines': [{'line': 'contains', 'value': 'Contacts'}]}, 'expect': 'x'}])
        self.assertEqual((r['status'], r['reason'], d.executed), ('stopped', 'no_matching_record', []))

    def test_cua_do_record_context_agrees_with_the_look(self):
        # The shared code (record_context, sibling_record, subtree): the first record's text for the reader and the chooser must not carry the heading or its level.
        f, d = facade_for('flat_ax');st = state_of(f, d)
        first_call = next(i for i, n in sorted(st['nodes'].items()) if n.get('label') == 'Call')
        text = f.record_context(st, first_call).split('\n')
        self.assertEqual(text, ['Priya Nair', 'Mobile +1 404 555 0142'])
        f2, d2 = facade_for('ax_dup');st2 = state_of(f2, d2)
        save = sorted(i for i, n in st2['nodes'].items() if n.get('label') == 'Save')[0]
        self.assertEqual(f2.record_context(st2, save).split('\n'), ['Notification preferences'])

    def test_cua_do_record_context_of_nested_has_no_heading_level_numerals(self):
        # Shared subtree text: a heading's value is its level. Wrong patch: read a heading's `value`.
        f, d = facade_for('nested');st = state_of(f, d)
        first = next(i for i, n in sorted(st['nodes'].items()) if n.get('label') == 'Message')
        text = f.record_context(st, first).split('\n')
        self.assertFalse([x for x in text if x.isdigit()], text);self.assertNotIn('Directory capture-nested', text)
        self.assertEqual(text, ['Engineering', 'Platform', 'Sam Okafor'])

    def test_look_id_ignores_selected_false_noise_but_sees_real_state(self):
        # Wrong patch: hash selected:false on every button (real state and inert noise then look alike).
        f, d, a = looked('booking')
        def strip(dr, els):
            for e in els:e.pop('selected', None)
        f2, d2 = facade_for('booking', strip)
        self.assertEqual(f2.look('Demo')['look_id'], a['look_id'])
        def select(dr, els):
            for e in els:
                if e['role'] == 'AXButton':e['selected'] = True;break
            return els
        f3, d3 = facade_for('booking', select)
        self.assertNotEqual(f3.look('Demo')['look_id'], a['look_id'])


class InputPages(unittest.TestCase):
    def test_form_has_three_inputs_and_three_controls(self):
        f, d, look = looked('form')
        self.assertEqual((look['record_kind'], look['counts']['page_controls']), ('none', 3))
        self.assertEqual([i['label'] for i in look['inputs']], ['Full name', 'Email address', 'Postal code'])
        self.assertEqual(look['controls'], ['Submit application', 'Reset', 'Cancel'])

    def test_a_typed_value_shows_in_the_look_and_changes_the_look_id(self):
        f, d, a = looked('form')
        def typed(dr, els):
            for e in els:
                if e.get('label') == 'Email address':e['value'] = 'a@example.org'
        f2, d2 = facade_for('form', typed);b = f2.look('Demo')
        self.assertIn({'label': 'Email address', 'value': 'a@example.org'}, b['inputs']);self.assertNotEqual(a['look_id'], b['look_id'])

    def test_only_reset_is_flagged_by_the_widened_destructive_list_on_the_real_controls(self):
        import plan
        flagged = {}
        for page in rd.PAGES:
            for e in rd.load(page)['elements']:
                if e['role'] in ('AXButton', 'AXLink', 'AXRadioButton', 'AXCheckBox') and e.get('in_web_content') and e.get('label') and plan.destructive_verbs(e['label']):
                    flagged[(page, e['label'])] = plan.destructive_verbs(e['label'])
        self.assertEqual(flagged, {('form', 'Reset'): ['reset']})

    def test_wizard_radios_read_their_state_from_value_and_selected(self):
        # Real Chrome: radios expose value '0'/'1' with selected false/true. Wrong patch: read only a checked key (it never exists).
        f, d, look = looked('wizard')
        self.assertEqual(look['controls'], ['Basic', 'Pro', 'Team', 'Cancel'])
        self.assertEqual(look.get('toggles'), [{'label': 'Basic', 'state': 'unchecked'}, {'label': 'Pro', 'state': 'unchecked'}, {'label': 'Team', 'state': 'unchecked'}])
        def pro(dr, els):
            for e in els:
                if e.get('label') == 'Pro':e['value'] = '1';e['selected'] = True
        f2, d2 = facade_for('wizard', pro);b = f2.look('Demo')
        self.assertEqual((b.get('toggles') or [None] * 3)[1], {'label': 'Pro', 'state': 'checked'});self.assertNotEqual(b['look_id'], look['look_id'])
        def value_only(dr, els):
            for e in els:
                if e.get('label') == 'Team':e['value'] = '1'
        f3, d3 = facade_for('wizard', value_only)
        self.assertEqual(f3.look('Demo')['toggles'][2]['state'], 'checked')
        def selected_only(dr, els):
            for e in els:
                if e.get('label') == 'Basic':e['selected'] = True
        f4, d4 = facade_for('wizard', selected_only)
        self.assertEqual(f4.look('Demo')['toggles'][0]['state'], 'checked')

    def test_toggle_marker_unit(self):
        self.assertIsNone(lk.toggle_marker({'role': 'AXButton', 'selected': False}))
        self.assertEqual(lk.toggle_marker({'role': 'AXButton', 'selected': True}), 'selected')
        self.assertEqual(lk.toggle_marker({'role': 'AXRadioButton', 'value': '0', 'selected': False}), 'unchecked')
        self.assertEqual(lk.toggle_marker({'role': 'AXCheckBox', 'value': '1'}), 'checked')
        self.assertEqual(lk.toggle_marker({'role': 'AXRadioButton', 'value': '0', 'selected': True}), 'checked')

    def test_destructive_page_has_one_control(self):
        f, d, look = looked('destructive')
        self.assertEqual((look['counts']['page_controls'], look['controls']), (1, ['Export data']))
        self.assertIn('Your data', look['text'])


class CanvasPages(unittest.TestCase):
    def press(self, page, control=None, near=None, goal=None):
        f, d = facade_for(page)
        kw = {'control': control} if control else {}
        if near:kw['near'] = near
        r = f.do(goal or 'Press "%s"' % control, title='Demo', expect=None, **kw)
        return r, d

    def test_the_look_lists_the_drawn_texts_when_ax_has_no_controls(self):
        for page in rd.CANVAS:
            f, d, look = looked(page)
            self.assertEqual(look['counts']['page_controls'], 0, page)
            self.assertTrue(look['canvas']['text_regions'], page)
        f, d, look = looked('canvas')
        self.assertEqual([t['text'] for t in look['canvas']['text_regions']], ['Save', 'Export', 'Export All', 'Reset'])

    def test_canvas_exact_unique_labels_click(self):
        for label in ('Save', 'Export', 'Export All', 'Reset'):
            r, d = self.press('canvas', label)
            self.assertEqual((r['status'], len(d.executed), r['judgment']), ('delivered_unverified', 1, 'exact'), label)
            self.assertIn('capture_id', d.executed[0])

    def test_canvas_regions_two_exports_defer_and_near_picks_one(self):
        r, d = self.press('canvas_regions', 'Export')
        self.assertEqual((r['status'], r['reason'], d.executed), ('deferred', 'region_ambiguous', []))
        self.assertEqual(sorted(m['near'] for m in r['matches']), ['Footer', 'Toolbar'])
        rt, dt = self.press('canvas_regions', 'Export', near='Toolbar')
        rf, df = self.press('canvas_regions', 'Export', near='Footer')
        self.assertEqual((rt['status'], rf['status'], len(dt.executed), len(df.executed)), ('delivered_unverified', 'delivered_unverified', 1, 1))
        self.assertLess(dt.executed[0]['y'], df.executed[0]['y'])  # the toolbar one is higher on the page

    def test_canvas_garbled_the_ocr_twin_rule_fails_closed_and_the_unique_label_works(self):
        for label in ('Save', 'Sove', 'Sava'):
            r, d = self.press('canvas_garbled', label)
            self.assertEqual((r['status'], d.executed), ('deferred', []), label)
            self.assertIn(r['reason'], ('region_uncorroborated', 'region_ambiguous'))
        r, d = self.press('canvas_garbled', 'Save', goal='Press "Save"')
        self.assertEqual(r['reason'], 'region_uncorroborated')
        r, d = self.press('canvas_garbled', 'Save As')
        self.assertEqual((r['status'], len(d.executed)), ('delivered_unverified', 1))

    def test_canvas_icon_has_no_text_label_and_lists_the_glyph(self):
        f, d = facade_for('canvas_icon')
        r = f.do('Click the download icon', title='Demo', expect=None)
        self.assertEqual((r['status'], r['reason'], d.executed), ('deferred', 'region_label_needed', []))
        self.assertIn('↓', [t['text'] for t in r['found']['region_texts']])

    def test_canvas_small_and_lowcontrast_unique_labels_click_and_twins_fail_closed(self):
        for page, ok, vetoed in (('canvas_small', ('Restore', 'Refresh', 'Rename', 'Remove', 'Reset'), ('Archive', 'Archived')),
                                 ('canvas_lowcontrast', ('Defer', 'Review', 'Discard', 'Approve All'), ())):
            for label in ok:
                r, d = self.press(page, label)
                self.assertEqual((r['status'], len(d.executed)), ('delivered_unverified', 1), (page, label))
            for label in vetoed:
                r, d = self.press(page, label)
                self.assertEqual((r['status'], d.executed), ('deferred', []), (page, label))


if __name__ == '__main__':unittest.main()
