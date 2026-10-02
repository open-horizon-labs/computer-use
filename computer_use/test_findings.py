"""Two live findings (Sonnet 5.5, real Chrome, n=1 per cell) as regression tests. Each names the tempting wrong patch it fails.

1. A SILENT WRONG CLICK reported done: the LLM wrote blind predicates (duration contains "30"); the page shows "half-hour" for the right slot;
   the predicate excluded it and the chooser picked among the leftovers. S4.2 s4: an incomparable value is UNKNOWN, never excluded.
2. A canvas page with two drawn "Export" buttons ended dead_end although Perception was healthy: pixel-only labels resolve against text regions.

Real booking tree (computer_use/fixtures/live_booking_ax.json) for 1; synthetic Perception parse results shaped like the canvas page for 2.
"""
import json
import re
import unittest

import shapes as sh
from core import Facade, Gap
from page_candidates import filter_records
from test_core import FakeChooser, FakeVision
from test_live_shapes import BOOKING_FIELDS, BOOKING_PATTERNS, LiveBase, LiveReader, UnknownVision, booked

PRIMITIVES = re.compile(r'(?i)(?:\b(?:call|calls|called|use|using|run|invoke|then|via)\s+`?|__)(?:windows|observe|read|choose|act|verify|trace|finish)\b')
BLIND = [{'field': 'provider', 'op': 'contains', 'value': 'Morgan Reyes'}, {'field': 'duration', 'op': 'contains', 'value': '30'}]
TELEHEALTH = 'e70'  # the correct slot: Dr. Morgan Reyes, Telehealth, half-hour, 3:00 PM


class ByDescription(FakeChooser):
    """A chooser that judges the record text (what the real chooser sees): picks the offered control whose description mentions `word`."""
    def __init__(self, word):super().__init__();self.word = word
    def __call__(self, step, request):
        self.requests.append(request)
        pick = next((a for a in request['actions'] if self.word in a['description']), request['actions'][0])
        return {'choice': pick['id'], 'route': 'julia-1', 'action_authorized': True}


class BlindPredicates(LiveBase):
    def setUp(self):
        super().setUp();self.driver.script = booked()
    def book(self, **kw):
        return self.do('Book the Morgan Reyes half-hour slot', records={'fields': BOOKING_FIELDS, 'predicates': BLIND}, **({'expect': 'Booked:'} | kw))
    def offered(self):return [a['id'] for a in self.chooser.requests[0]['actions']]

    def test_blind_predicates_defer_instead_of_silently_excluding_half_hour(self):
        # Finding 1. Wrong patches: treat a non-match as exclusion (the right slot vanished and the chooser picked among 5 leftovers);
        # ignore shape; let the chooser pick among the leftovers while a possible competitor is unknown.
        r = self.book()
        self.assertEqual((r['status'], r['delivery'], self.driver.executed), ('deferred', 'none', []))
        self.assertEqual(r['reason'], 'unknown_competitors_unacknowledged')
        self.assertEqual(self.chooser.requests, [])
        self.assertEqual(r['unknown_ids'], [TELEHEALTH]);self.assertIn('half-hour', json.dumps(r['evidence']['extracted']))
        for recipe in ('accept_unknown', 'treat_as_match'):self.assertIn(recipe, r['hint'])
        self.assertFalse(PRIMITIVES.search(json.dumps(r)))

    def test_treat_as_match_brings_the_unknown_record_into_play_and_the_chooser_picks_among_eligible_only(self):
        # (b) Wrong patch: treat_as_match skips the same-record rules (the chooser sees the excluded 60 and 45 minute records) or accepts excluded ids.
        self.chooser = ByDescription('Telehealth')
        r = self.book(treat_as_match=[TELEHEALTH])
        self.assertEqual((r['status'], r['selected']['id'], r['judgment']), ('done', TELEHEALTH, 'controller'))
        self.assertEqual(len(self.driver.executed), 1);self.assertTrue(self.driver.executed[0]['element_token'].endswith(':70'))
        offered = self.offered()
        self.assertEqual((len(offered), TELEHEALTH in offered), (6, True))
        self.assertFalse({'e23', 'e39'} & set(offered))  # the 60 and 45 minute Reyes slots were excluded by a comparable failure

    def test_accept_unknown_still_means_they_do_not_match(self):
        self.chooser = ByDescription('Telehealth')
        r = self.book(accept_unknown=[TELEHEALTH])
        self.assertEqual(r['status'], 'done');self.assertNotEqual(r['selected']['id'], TELEHEALTH)
        self.assertNotIn(TELEHEALTH, self.offered());self.assertEqual(len(self.offered()), 5)

    def test_treat_as_match_may_name_only_unknown_records(self):
        # Wrong patch: a controller verdict can revive an excluded record or invent an id.
        for bad in (['e23'], ['e999'], [TELEHEALTH, 'e23']):
            r = self.book(treat_as_match=bad)
            self.assertEqual((r['status'], self.driver.executed), ('refused', []), bad)
            self.assertEqual(r['reason'], 'treat_as_match_invalid')
        self.assertEqual(self.chooser.requests, [])

    def test_a_comparable_failure_on_another_field_still_excludes(self):
        # S4.2: only an INCOMPARABLE value is unknown. The Telehealth record fails service eq Follow-up comparably, so it stays excluded.
        preds = BLIND + [{'field': 'service', 'value': 'Follow-up'}]
        r = self.do('Book the Morgan Reyes follow-up', records={'fields': BOOKING_FIELDS, 'predicates': preds}, expect='Booked:')
        self.assertEqual(r['status'], 'done');self.assertNotEqual(r['selected']['id'], TELEHEALTH);self.assertNotIn('unknown_ids', r)

    def test_every_result_that_used_predicates_audits_what_they_threw_away(self):
        # (c) Wrong patch: no audit (the suite could not see that the right slot was thrown away), or an unbounded one.
        r = self.book(accept_unknown=[TELEHEALTH])
        self.assertEqual(r['status'], 'done');self.assertIn('excluded_values', r['evidence'])
        audit = r['evidence']['excluded_values']
        self.assertEqual(set(audit), {'provider', 'duration'});self.assertIn('60 min', audit['duration']);self.assertIn('45 min', audit['duration'])
        self.assertNotIn('half-hour', audit['duration'])  # unknown, not excluded
        self.assertTrue(all(len(v) <= 8 and all(len(x) <= 40 for x in v) for v in audit.values()))
        deferred = self.book()
        self.assertIn('excluded_values', deferred['evidence'])

    def test_the_audit_is_bounded(self):
        rows = [{'record_id': 'r%d' % i, 'fields': {'name': str(i) + 'x' * 60}} for i in range(12)]
        fields = {'name': {'description': 'n', 'type': 'text'}}
        extraction = {'snapshot_id': 's', 'records': rows}
        filtered = filter_records(extraction, fields=fields, predicates=[{'field': 'name', 'value': 'nope'}], coverage_complete=True, current_snapshot='s')
        audit = Facade()._excluded_values({'extraction': extraction, 'filter': filtered}, [{'field': 'name', 'value': 'nope'}])
        self.assertEqual((len(audit['name']), max(len(v) for v in audit['name'])), (8, 40))


class Shapes(unittest.TestCase):
    """Unit checks of the shape rule through filter_records."""
    def reclassify(self, values, rule, field='duration'):
        fields = {field: {'description': 'd', 'type': 'text'}}
        extraction = {'snapshot_id': 's', 'records': [{'record_id': 'r%d' % i, 'fields': {field: v}} for i, v in enumerate(values)]}
        filtered = filter_records(extraction, fields=fields, predicates=[rule], coverage_complete=True, current_snapshot='s')
        return Facade()._reclassify_shapes(fields, [rule], extraction, filtered)

    def test_a_digit_bearing_predicate_against_a_digit_free_string_is_unknown(self):
        f = self.reclassify(['30 min', 'half-hour', '60 min'], {'field': 'duration', 'op': 'contains', 'value': '30'})
        self.assertEqual((f['eligible_ids'], f['unknown_ids'], f['excluded_ids']), (['r0'], ['r1'], ['r2']))
        self.assertFalse(f['complete'])

    def test_an_outlier_of_the_fields_shape_is_unknown_when_the_predicate_would_exclude_it(self):
        # Wrong patch: only compare the predicate's shape with the value's, not the value with its field.
        f = self.reclassify(['Follow-up', 'Consultation', '2-for-1 visit', 'Follow-up'], {'field': 'duration', 'value': 'Follow-up'}, field='duration')
        self.assertEqual((f['eligible_ids'], f['unknown_ids'], f['excluded_ids']), (['r0', 'r3'], ['r2'], ['r1']))

    def test_comparable_values_are_still_excluded(self):
        f = self.reclassify(['30 min', '45 min', '60 min'], {'field': 'duration', 'op': 'contains', 'value': '30'})
        self.assertEqual((f['eligible_ids'], f['unknown_ids'], f['excluded_ids']), (['r0'], [], ['r1', 'r2']))
        self.assertTrue(f['complete'])

    def test_a_clock_predicate_against_non_clock_digits_is_unknown(self):
        f = self.reclassify(['Starts 1:45 PM', 'Starts 2:30 PM', 'Starts in 5 days'], {'field': 'duration', 'op': 'contains', 'value': '1:45 PM'})
        self.assertEqual((f['eligible_ids'], f['unknown_ids'], f['excluded_ids']), (['r0'], ['r2'], ['r1']))


def regions(*items):
    return {'regions': [{'id': 't%d' % i, 'kind': 'text', 'text': t, 'bounds': {'x': x, 'y': y, 'width': 80, 'height': 24}} for i, (t, x, y) in enumerate(items)]}


class ShapeDirection(unittest.TestCase):
    """Review of the shape rule (my own brief said 'or the reverse', which was too broad). Only a digit-bearing predicate against a
    digit-free string is incomparable ('30' vs 'half-hour'). Wrong patch: treat ANY digit mismatch as incomparable, which defers ordinary
    text predicates on strings with incidental digits ('Walnut' vs 'Walnut desk lamp 2', 'PM' vs '3:00 PM')."""
    f = Facade.__new__(Facade)

    def test_a_text_predicate_against_a_string_with_incidental_digits_is_comparable(self):
        for predicate, value in (('Walnut', 'Walnut desk lamp 2'), ('PM', '3:00 PM'), ('Reyes', 'Dr. Reyes 3rd floor')):
            self.assertFalse(self.f._incomparable(predicate, value, None), (predicate, value))

    def test_a_digit_bearing_predicate_against_a_word_is_incomparable(self):
        for predicate, value in (('30', 'half-hour'), ('30 min', 'half-hour'), ('3:00 PM', 'noon'), ('$50', 'free')):
            self.assertTrue(self.f._incomparable(predicate, value, None), (predicate, value))

    def test_a_matching_majority_shape_keeps_a_clock_predicate_comparable(self):
        self.assertFalse(self.f._incomparable('AM', '9:00 AM', (True, True, False)))


class CanvasRegions(unittest.TestCase):
    """Pixel-only page: two 'Export' buttons drawn on a canvas, labelled by nearby 'Toolbar' and 'Footer' texts (synthetic parse results)."""
    PAGE = [('Toolbar', 10, 10), ('Export', 10, 40), ('Footer', 10, 500), ('Export', 10, 530)]
    def go(self, parsed=None, healthy=True, goal='Press the Export button', vision=None, **kw):
        driver = sh.ShapeDriver(sh.canvas())
        if healthy:driver.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'};driver.capture_id = 'cap'
        driver.parse_result = parsed if parsed is not None else regions(*self.PAGE)
        self.chooser = FakeChooser()
        facade = Facade(driver, generic_factory=lambda: self.chooser, reader_factory=lambda: LiveReader({}), visual_factory=vision or UnknownVision, sleep=lambda s: None)
        kw.setdefault('expect', None);kw.setdefault('allow_foreground', True)  # the drawn-surface click needs the explicit permission (CanvasForeground tests cover its absence)
        return facade.do(goal, title='Demo', **kw), driver

    def test_a_unique_exact_label_is_clicked_in_capture_space_and_ends_delivered_unverified(self):
        # Finding 2. Wrong patch: control_not_found/dead_end on a pixel-only page although Perception is healthy.
        r, d = self.go(regions(('Toolbar', 10, 10), ('Export', 10, 40)), control='Export')
        self.assertEqual((r['status'], len(d.executed)), ('delivered_unverified', 1))
        self.assertEqual((r['reason'], r['judgment']), ('expect_not_given', 'exact'))
        click = d.executed[0]
        self.assertEqual((click['capture_id'], click['x'], click['y']), ('cap', 50.0, 52.0));self.assertEqual(self.chooser.requests, [])
        self.assertNotIn('dead_end', r)

    def test_a_quoted_goal_label_takes_the_same_path(self):
        r, d = self.go(regions(('Toolbar', 10, 10), ('Export', 10, 40)), goal='Press "Export"')
        self.assertEqual((r['status'], len(d.executed)), ('delivered_unverified', 1))
        self.assertEqual(r['judgment'], 'exact')

    def test_two_exact_labels_defer_with_coarse_positions_and_never_click(self):
        # Wrong patch: take the first exact region when several match.
        r, d = self.go(control='Export')
        self.assertEqual((r['status'], r['reason'], d.executed), ('deferred', 'region_ambiguous', []))
        self.assertEqual([m['near'] for m in r['matches']], ['Toolbar', 'Footer']);self.assertTrue(all(m['x'] % 50 == 0 and m['y'] % 50 == 0 for m in r['matches']))
        self.assertIn('near=', r['hint']);self.assertFalse(PRIMITIVES.search(json.dumps(r)))
        self.assertEqual(self.chooser.requests, [])

    def test_near_picks_the_export_beside_that_text(self):
        # Wrong patch: near is ignored (the first Export is clicked whatever near says).
        r, d = self.go(control='Export', near='Footer')
        self.assertEqual((r['status'], len(d.executed)), ('delivered_unverified', 1))
        self.assertEqual(d.executed[0]['y'], 542.0)
        r, d = self.go(control='Export', near='  toolbar ')
        self.assertEqual(d.executed[0]['y'], 52.0)

    def test_a_near_text_that_is_not_beside_any_export_defers(self):
        for near in ('Nothing', 'Save'):
            r, d = self.go(control='Export', near=near)
            self.assertEqual((r['reason'], d.executed), ('region_ambiguous', []), near)

    def test_a_near_text_beyond_the_pixel_bound_does_not_count(self):
        far = regions(('Toolbar', 10, 10), ('Export', 10, 700), ('Footer', 10, 500), ('Export', 10, 530))
        r, d = self.go(far, control='Export', near='Toolbar')
        self.assertEqual((r['reason'], d.executed), ('region_ambiguous', []))

    def test_near_also_left_of_the_control(self):
        side = regions(('Cancel', 10, 40), ('Save', 100, 40), ('Cancel', 10, 300), ('Save', 100, 300))
        r, d = self.go(side, control='Save', near='Cancel')
        self.assertEqual(r['reason'], 'region_ambiguous')  # two Saves each with a Cancel to the left: the tie is ambiguous, never a guess
        r, d = self.go(regions(('Cancel', 10, 40), ('Save', 100, 40), ('Save', 100, 300)), control='Save', near='Cancel')
        self.assertEqual((d.executed[0]['y'],), (52.0,))

    def test_an_ocr_twin_vetoes_the_label(self):
        # Wrong patch: exact match wins although another text reads "Sove" (the real control may be the garbled one).
        r, d = self.go(regions(('Save', 10, 40), ('Sove', 200, 40)), control='Save')
        self.assertEqual((r['reason'], d.executed), ('region_uncorroborated', []))

    def test_a_header_and_a_button_with_the_same_word_need_near(self):
        page = regions(('Save', 10, 10), ('Actions', 10, 260), ('Save', 10, 290))
        r, d = self.go(page, control='Save');self.assertEqual((r['reason'], d.executed), ('region_ambiguous', []))
        r, d = self.go(page, control='Save', near='Actions');self.assertEqual(d.executed[0]['y'], 302.0)

    def test_no_label_on_a_canvas_says_which_texts_exist(self):
        r, d = self.go(goal='Press the Export button in the toolbar')
        self.assertEqual((r['reason'], d.executed), ('region_label_needed', []))
        self.assertIn({'text': 'Export', 'count': 2}, r['found']['region_texts']);self.assertNotIn('dead_end', r)
        self.assertIn('control=', r['hint']);self.assertIn('near=', r['hint'])

    def test_dead_end_only_when_no_fallback_can_help(self):
        # Wrong patch: dead_end whenever AX has no control (Perception could have helped), or never.
        r, d = self.go(healthy=False, control='Export')
        self.assertEqual((r['reason'], r['dead_end'], d.executed), ('control_not_found', True, []))
        r, d = self.go(regions(), control='Export');self.assertEqual((r['dead_end'], d.executed), (True, []))
        r, d = self.go(regions(('Toolbar', 10, 10)), control='Export')
        self.assertEqual((r['reason'], d.executed), ('control_not_found', []));self.assertNotIn('dead_end', r);self.assertEqual(r['found']['region_texts'], [{'text': 'Toolbar', 'count': 1}])

    def test_the_click_is_verified_as_today(self):
        r, d = self.go(regions(('Toolbar', 10, 10), ('Export', 10, 40)), control='Export', expect='Exported', vision=FakeVision)
        self.assertEqual((r['status'], len(d.executed)), ('done', 1))
        self.assertEqual(r['verification']['route'], 'systemone_vision')

    def test_a_stale_capture_is_never_clicked(self):
        # The capture-bound click keeps its capture; an expired capture cannot be parsed, so there is no fallback and nothing is clicked.
        driver = sh.ShapeDriver(sh.canvas());driver.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'};driver.capture_id = 'cap'
        driver.parse_result = regions(('Export', 10, 40))
        clock = [0.0]
        real = driver.observe
        def slow(*a):
            x = real(*a);clock[0] += 70;return x
        driver.observe = slow
        facade = Facade(driver, generic_factory=FakeChooser, reader_factory=lambda: LiveReader({}), visual_factory=UnknownVision, sleep=lambda s: None, clock=lambda: clock[0])
        r = facade.do('Press "Export"', title='Demo', expect=None, control='Export')
        self.assertEqual(driver.executed, [])


if __name__ == '__main__':unittest.main()


class CanvasForeground(CanvasRegions):
    """Probe 2026-09-29 on our own fixture: a BACKGROUND pixel click on a canvas is turned into an AXPress on the element under it, which
    Chrome delivers at that element's CENTRE (aimed at a corner button, the centre button was pressed and reported as success). So it is
    a wrong click, never sent; a real pointer event needs the Driver's foreground delivery, which only the caller's explicit
    allow_foreground permits. Each test names the wrong patch it fails."""
    ONE = [('Toolbar', 10, 10), ('Export', 10, 40)]

    def test_without_permission_nothing_is_clicked_and_the_reason_says_why(self):
        # Wrong patch: send the background click anyway (it lands at the centre) or report it delivered_unverified.
        r, d = self.go(regions(*self.ONE), control='Export', allow_foreground=None)
        self.assertEqual((r['status'], r['reason'], d.executed, r['delivery']), ('refused', 'pointer_not_deliverable_in_background', [], 'none'))
        self.assertIn('allow_foreground', r['message']);self.assertIn('nothing was clicked', r['message'])

    def test_false_is_not_permission(self):
        r, d = self.go(regions(*self.ONE), control='Export', allow_foreground=False)
        self.assertEqual((r['reason'], d.executed), ('pointer_not_deliverable_in_background', []))

    def test_with_permission_the_one_click_is_delivered_in_foreground_mode(self):
        # Wrong patch: accept the flag but keep delivery_mode background (the Driver would still press the centre).
        r, d = self.go(regions(*self.ONE), control='Export', allow_foreground=True)
        self.assertEqual((r['status'], len(d.executed), d.executed[0]['delivery_mode'], d.executed[0]['capture_id']), ('delivered_unverified', 1, 'foreground', 'cap'))
        # Wrong patch: send the window in `target` AND as top-level pid/window_id (Driver 0.30.4: invalid_action_target, live 2026-09-30).
        self.assertEqual(d.executed[0].get('target', {}).get('kind'), 'window')
        self.assertNotIn('pid', d.executed[0]);self.assertNotIn('window_id', d.executed[0])

    def test_permission_does_not_outlive_the_call_except_for_the_window_it_was_given_for(self):
        # Wrong patch: a facade-level flag that stays set (the next caller's canvas click would front ANOTHER window unasked). The window the user approved keeps its
        # grant for the session (no second ask, and the answer says so); no other window shares it (test_who.ForegroundGrantIsPerWindow).
        driver = sh.ShapeDriver(sh.canvas());driver.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'};driver.capture_id = 'cap'
        driver.parse_result = regions(*self.ONE)
        f = Facade(driver, generic_factory=FakeChooser, reader_factory=lambda: LiveReader({}), visual_factory=UnknownVision, sleep=lambda s: None)
        first = f.do('Press the Export button', title='Demo', expect=None, control='Export', allow_foreground=True)
        second = f.do('Press the Export button', title='Demo', expect=None, control='Export')
        self.assertEqual((first['status'], second['status'], len(driver.executed)), ('delivered_unverified', 'delivered_unverified', 2))
        self.assertEqual(second['foreground_granted_for'], ['Demo'])

    def test_permission_does_not_leak_into_the_primitive_path(self):
        # Wrong patch: set the flag for the call and never clear it (a later choose/act on a canvas would front the window unasked).
        driver = sh.ShapeDriver(sh.canvas());driver.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'};driver.capture_id = 'cap'
        driver.parse_result = regions(('Toolbar', 10, 10), ('Export', 10, 40))
        f = Facade(driver, generic_factory=FakeChooser, reader_factory=lambda: LiveReader({}), visual_factory=UnknownVision, sleep=lambda s: None)
        f.do('Press the Export button', title='Demo', expect=None, control='Export', allow_foreground=True)
        obs = f.observe(1, 2)['snapshot']
        selection = f.region_exact(obs, 'Export', 'Press the Export button')['selection']  # the same exact-label path do took
        with self.assertRaisesRegex(Gap, 'pointer_not_deliverable_in_background'):f.act(selection)
        self.assertEqual(len(driver.executed), 1)

    def test_an_ax_control_is_never_fronted_even_with_permission(self):
        # Wrong patch: apply foreground delivery to every click once the flag is given. An AX press works in the background; fronting it is the policy breach.
        driver = sh.ShapeDriver(sh.cards(names='A'))
        f = Facade(driver, generic_factory=FakeChooser, reader_factory=lambda: LiveReader({}), visual_factory=UnknownVision, sleep=lambda s: None)
        r = f.do('Press Book', title='Demo', expect=None, control='Book', allow_foreground=True)
        self.assertEqual((r['status'], len(driver.executed)), ('delivered_unverified', 1))
        self.assertNotEqual(driver.executed[0].get('delivery_mode'), 'foreground')

    def test_a_plan_step_carries_its_own_permission(self):
        # Wrong patch: a plan ignores the step flag (every canvas step refused) or reads it from the call level (no step-level control).
        r, d = self.go(regions(*self.ONE), allow_foreground=None, steps=[{'do': 'press', 'control': 'Export', 'expect': None, 'allow_foreground': True}])
        self.assertEqual((r['status'], len(d.executed), d.executed[0]['delivery_mode']), ('delivered_unverified', 1, 'foreground'))
        r, d = self.go(regions(*self.ONE), allow_foreground=None, steps=[{'do': 'press', 'control': 'Export', 'expect': None}])
        self.assertEqual((r['status'], d.executed), ('refused', []));self.assertEqual(r.get('reason') or r['steps'][0].get('reason'), 'pointer_not_deliverable_in_background')

    def test_a_plan_step_flag_must_be_true_or_absent(self):
        r, d = self.go(regions(*self.ONE), allow_foreground=None, steps=[{'do': 'press', 'control': 'Export', 'expect': None, 'allow_foreground': False}])
        self.assertEqual((r['status'], r['reason'], d.executed), ('refused', 'bad_request', []));self.assertIn('allow_foreground', r['message'])
