"""cua_do on the shapes a review found the two captured trees did not cover. Each test names the tempting wrong patch it fails.
Synthetic shapes (facade/shapes.py) plus the real orders tree; no tree from an unrelated real site exists yet."""
import json
import re
import unittest

import shapes as sh
from shapes import E, base
from test_live_shapes import (LiveBase, LiveOrders, LiveReader, ORDER_FIELDS, ORDER_ONE, ORDER_PATTERNS, UnknownVision, add, load, orders_flow)

PRIMITIVES = re.compile(r'cua_(?:windows|observe|read|choose|act|verify|trace|finish)\b')


def button_of(els, name):
    """Element index of the button in the record that shows the text 'Dr. <name>': the nearest ancestor holding exactly one button."""
    by = {e['element_index']: e for e in els}
    text = next(e for e in els if e.get('value') == 'Dr. ' + name)
    node = text['parent_index']
    while node is not None:
        inside = []
        stack = [node]
        while stack:
            x = stack.pop();inside += [e['element_index'] for e in els if e['parent_index'] == x and e['role'] == 'AXButton'];stack += [e['element_index'] for e in els if e['parent_index'] == x]
        if len(inside) == 1:return inside[0]
        node = by[node]['parent_index']


def clicked(driver):
    return [int(c['element_token'].split(':')[1]) for c in driver.executed]


class Toast(unittest.TestCase):
    def test_a_success_toast_with_an_undo_button_is_done_in_one_call(self):
        # P1-A. Wrong patch: any new controls after a click are a confirm dialog (the booking succeeded and it deferred).
        els = sh.cards()
        r, d, _ = sh.run(els, script=sh.toast(), expect='Booked:')
        self.assertEqual((r['status'], r['verified'], clicked(d)), ('done', True, [button_of(els, 'B')]))
        self.assertNotIn('dialog', r)

    def test_identity_text_inside_a_toast_never_authorizes_pressing_its_button(self):
        # P1-A. Wrong patch: a matching identity in the toast plus confirm='Undo' presses Undo (2 clicks, done).
        els = sh.cards()
        r, d, _ = sh.run(els, script=sh.toast(), expect='Booked:', confirm='Undo')
        self.assertEqual((r['status'], len(d.executed)), ('done', 1))
        self.assertNotIn('confirmation', r)

    def test_a_toast_with_two_buttons_is_still_the_outcome_when_it_satisfies_expect(self):
        # Wrong patch: two controls make any new region a dialog even when the region IS the success message.
        r, d, _ = sh.run(sh.cards(), script=sh.toast(buttons=('Undo', 'Dismiss')), expect='Booked:')
        self.assertEqual((r['status'], len(d.executed)), ('done', 1))

    def test_a_toast_on_the_real_orders_page_is_the_outcome_not_a_dialog(self):
        # P1-A on the real orders shape: cancelling shows 'Order #1044 cancelled' + Undo instead of a confirm dialog.
        class Orders(LiveOrders):
            def setUp(self):
                LiveBase.setUp(self)
                def script(d, els):
                    if d.executed:add(els, 15, 'AXStaticText', label='Order #1044 cancelled', value='Order #1044 cancelled');add(els, 15, 'AXButton', label='Undo')
                self.driver.script = script
            def runTest(self):pass
        o = Orders();o.setUp()
        r = o.cancel(control='Cancel', confirm='Undo')
        self.assertEqual((r['status'], len(o.driver.executed)), ('done', 1))


class Dialogs(unittest.TestCase):
    def test_five_and_eight_button_dialogs_are_reported_with_all_their_labels(self):
        # P2-C. Wrong patch: a 1..4 control cutoff (the dialog was missed and the LLM was told to re-verify with no labels).
        for labels in (['Yes', 'No', 'Later', 'Help', 'Close'], ['A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'A8']):
            r, d, _ = sh.run(sh.cards(), script=sh.dialog(labels), expect='Booked:')
            self.assertEqual((r['status'], r['reason'], len(d.executed)), ('deferred', 'confirm_dialog_present', 1), labels)
            self.assertEqual(r['dialog']['controls'], labels);self.assertEqual(r['dialog']['identity'], 'matched')

    def test_a_big_dialog_can_be_confirmed_by_exact_label_after_an_identity_match(self):
        els = sh.cards()
        r, d, _ = sh.run(els, script=sh.dialog(['Yes', 'No', 'Later', 'Help', 'Close']), expect='Booked:', confirm='Yes')
        self.assertEqual(len(d.executed), 2)  # first the Book button, then the dialog's Yes: the dialog stayed, so expect is still unproven
        self.assertEqual(r['status'], 'deferred')

    def test_a_list_gaining_a_card_is_not_a_dialog(self):
        # P2-C. Wrong patch: any new control is a dialog (a re-rendered list read as a one-control dialog).
        for link in (False, True):
            els = sh.cards(link=link)
            r, d, _ = sh.run(els, script=sh.growth(link), expect='Booked:', **({'control': 'Book'} if link else {}))
            self.assertEqual((r['status'], r['reason']), ('deferred', 'delivery_unverified'), link)
            self.assertNotIn('dialog', r);self.assertEqual(len(d.executed), 1)

    def test_a_cookie_banner_style_pair_of_buttons_is_a_dialog_that_needs_its_identity(self):
        def banner(els, web):
            g = E(els, web, 'AXGroup');E(els, g, 'AXStaticText', 'We use cookies', 'We use cookies');E(els, g, 'AXButton', 'Accept all');E(els, g, 'AXButton', 'Reject')
        r, d, _ = sh.run(sh.cards(), script=sh.after_click(banner), expect='Booked:', confirm='Accept all')
        self.assertEqual((r['reason'], len(d.executed)), ('confirm_identity_unknown', 1))


class Discovery(unittest.TestCase):
    def test_per_record_labels_are_discovered_from_structure(self):
        # P1-B. Wrong patch: records need the SAME role+label repeated, so 'Book Dr A'/'Book Dr B' end in records_ambiguous.
        els = sh.cards(label=lambda n: 'Book Dr ' + n)
        r, d, reader = sh.run(els)
        self.assertEqual((r['status'], r['reason'] if 'reason' in r else None, clicked(d)), ('delivered_unverified', 'expect_not_given', [button_of(els, 'B')]))
        self.assertEqual(len(reader.requests[0]['records']), 3)

    def test_control_matches_a_per_record_label_exactly_or_by_whole_word_prefix(self):
        els = sh.cards(label=lambda n: 'Book Dr ' + n)
        for control in ('Book', 'book dr b', 'Book Dr B'):
            r, d, _ = sh.run(els, control=control)
            self.assertEqual(clicked(d), [button_of(els, 'B')], control)
        r, d, _ = sh.run(els, control='Boo')
        self.assertEqual((r['reason'], d.executed), ('control_not_found', []))

    def test_one_record_is_the_record(self):
        # P1-B. Wrong patch: a page with a single card (no repetition) is records_ambiguous.
        els = sh.cards(names='B')
        r, d, reader = sh.run(els)
        self.assertEqual((r['status'], clicked(d)), ('delivered_unverified', [button_of(els, 'B')]))
        self.assertIn('Dr. B', reader.requests[0]['records'][0]['text'])

    def test_records_ambiguous_hint_uses_only_cua_do_parameters(self):
        # P1-B. Wrong patch: a hint that says to pass records.record_ids (a cua_do-only LLM cannot obtain them) or a primitive.
        r, d, _ = sh.run(sh.toolbar())
        self.assertEqual((r['status'], r['reason'], d.executed), ('deferred', 'records_ambiguous', []))
        self.assertNotIn('record_ids', r['hint']);self.assertFalse(PRIMITIVES.search(json.dumps(r)))
        self.assertIn('quotes the exact label', r['hint']);self.assertNotIn('Export', r['hint']);self.assertEqual(r['found']['controls'], ['Export', 'Save'])
        followed, d2, _ = sh.run(sh.toolbar(), goal='Click "Export"', records=None)  # the hinted path works
        self.assertEqual((followed['judgment'], len(d2.executed)), ('exact', 1))

    def test_reviewer_shapes_pick_the_right_record(self):
        # Guards (they held before): link+button cards need control, icon-button rows, role=group grid, nested sections.
        els = sh.cards(link=True)
        r, d, _ = sh.run(els)
        self.assertEqual((r['reason'], d.executed), ('control_needed', []))
        self.assertEqual({c['label'] for c in r['found']['repeated_controls']}, {'Profile', 'Book'})
        r, d, _ = sh.run(els, control='Book');self.assertEqual(clicked(d), [button_of(els, 'B')])
        for make in (sh.icon_rows, sh.grid):
            els = make()
            r, d, _ = sh.run(els, records={'fields': sh.NAME_FIELDS, 'predicates': [{'field': 'name', 'value': 'Dr. B'}]})
            self.assertEqual(clicked(d), [button_of(els, 'B')], make.__name__)
        els = sh.nested()
        r, d, _ = sh.run(els, records={'fields': sh.NAME_FIELDS, 'predicates': [{'field': 'name', 'value': 'Dr. BY'}]})
        self.assertEqual(clicked(d), [button_of(els, 'BY')])

    def test_a_disabled_matching_record_is_reported_as_disabled(self):
        # P3-F. Wrong patch: drop disabled controls, so a matching record vanishes and the deferral says nothing satisfies the predicates.
        r, d, _ = sh.run(sh.cards(disabled='B'))
        self.assertEqual((r['status'], r.get('reason'), d.executed), ('deferred', 'record_disabled', []))
        self.assertEqual(r['disabled_count'], 1)

    def test_several_page_areas_defer_web_area_ambiguous_but_an_iframe_is_part_of_its_page(self):
        # P3-G. Wrong patch: silently scope to the first web area (an extension popup listed first).
        r, d, _ = sh.run(sh.two_web_areas())
        self.assertEqual((r['reason'], r['found'], d.executed), ('web_area_ambiguous', {'web_areas': 2}, []))
        self.assertFalse(PRIMITIVES.search(json.dumps(r)))
        els = sh.with_iframe()
        r, d, _ = sh.run(els)
        self.assertEqual(clicked(d), [button_of(els, 'B')])

    def test_a_page_with_nothing_to_press_is_a_dead_end_that_says_so(self):
        # P3-H. Wrong patch: a bare deferral the LLM retries in a loop.
        for kw in ({'goal': 'Click the red dot', 'records': None}, {}):
            r, d, _ = sh.run(sh.canvas(), **kw)
            self.assertEqual((r['status'], r.get('dead_end'), d.executed), ('deferred', True, []), kw)
            self.assertIn('CUA_TASK_ADVANCED=1', r['report_to_user']);self.assertIn('do not loop', r['report_to_user'])
            self.assertFalse(PRIMITIVES.search(json.dumps(r)))

    def test_a_recoverable_deferral_is_not_flagged_dead_end(self):
        r, _, _ = sh.run(sh.toolbar())
        self.assertNotIn('dead_end', r)


class Identity(LiveBase):
    fixture = 'live_orders_ax.json'
    patterns = ORDER_PATTERNS
    def setUp(self):
        super().setUp();self.driver.script = orders_flow(self.driver)

    def test_identity_defaults_to_the_fields_the_eq_predicates_constrain(self):
        # P2-D. Wrong patch: default identity = ALL fields (the dialog shows order and item, not status, so the orders flow always deferred).
        r = self.do('Cancel order #1044', records={'fields': ORDER_FIELDS, 'predicates': ORDER_ONE}, control='Cancel', expect='Order #1044 cancelled', confirm='Yes, cancel order')
        self.assertEqual((r['status'], len(self.driver.executed)), ('done', 2))

    def test_a_dialog_that_shows_part_of_the_identity_defers_with_the_exact_retry(self):
        preds = [{'field': 'order', 'value': '#1044'}, {'field': 'status', 'value': 'Processing'}]
        r = self.do('Cancel order #1044', records={'fields': ORDER_FIELDS, 'predicates': preds}, control='Cancel', expect='Order #1044 cancelled', confirm='Yes, cancel order')
        self.assertEqual((r['status'], r['reason'], len(self.driver.executed)), ('deferred', 'confirm_identity_partial', 1))
        self.assertEqual((r['identity_shown'], r['identity_not_shown']), (['order'], ['status']));self.assertIn('records.identity=["order"]', r['hint'])
        self.setUp()
        retry = self.do('Cancel order #1044', records={'fields': ORDER_FIELDS, 'predicates': preds, 'identity': ['order']}, control='Cancel', expect='Order #1044 cancelled', confirm='Yes, cancel order')
        self.assertEqual((retry['status'], len(self.driver.executed)), ('done', 2))

    def test_no_eq_predicates_means_all_fields(self):
        r = self.do('Cancel #1044', records={'fields': ORDER_FIELDS, 'predicates': [{'field': 'item', 'op': 'contains', 'value': 'lamp'}, {'field': 'order', 'op': 'contains', 'value': '1044'}]},
                    control='Cancel', expect='Order #1044 cancelled', confirm='Yes, cancel order')
        self.assertEqual(r['reason'], 'confirm_identity_partial')  # all three fields, only two shown

class Expect(unittest.TestCase):
    def test_expect_is_never_satisfied_by_a_control_label(self):
        # P2-E. Wrong patch: count any node's label (a 'Cancel booking' button that appears after the click proved the booking).
        def add_button(els, web):E(els, web, 'AXButton', 'Cancel booking')
        r, d, _ = sh.run(sh.cards(), script=sh.after_click(add_button), expect='Cancel booking')
        self.assertEqual((r['status'], len(d.executed)), ('deferred', 1))
        self.assertEqual(r['verification']['reason'], 'expect_is_a_control_label')

    def test_verify_of_a_button_label_is_not_verified(self):
        els, web = base();E(els, web, 'AXButton', 'Book')
        r, d, _ = sh.run(els, goal='check', operation='verify', expect='Book', records=None)
        self.assertEqual((r['status'], r.get('reason'), d.executed), ('deferred', 'not_verified', []))

    def test_verify_only_reports_presence_never_done(self):
        # P2-E. Wrong patch: verify-only says done for text that was already on the page (there is no before-state).
        els, web = base();E(els, web, 'AXStaticText', 'Booked: yes', 'Booked: yes')
        r, d, _ = sh.run(els, goal='check', operation='verify', expect='Booked: yes', records=None)
        self.assertEqual((r['status'], r.get('reason'), r['verified']), ('observed', 'presence_only', False))
        self.assertEqual(r['verification']['present_before'], 'unknown')
        self.assertFalse(r['trace_summary']['follow_up_needed']);self.assertIn('presence', r['hint'])


if __name__ == '__main__':unittest.main()
