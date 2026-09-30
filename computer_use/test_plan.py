"""do plans (option B, CE-FACADE-005): LOOK, then PLAN ONCE, then a deterministic executor.

Each test names the tempting wrong patch it fails. Fakes and the REAL captured Chrome trees (computer_use/fixtures) plus the synthetic shapes of
computer_use/shapes.py: no Driver, model, desktop or network. The plan is validated whole before any Driver action; each step is the existing
single-step machinery on a fresh observation; the first step that is not done stops the plan.
"""
import importlib.util
import json
import re
import unittest

import shapes as sh
import test_live_shapes as lv
from core import Facade, DriverCallFailed
from test_core import FakeChooser
from test_do import Clock, NamedChooser

PRIMITIVES = re.compile(r'(?i)(?:\b(?:call|calls|called|use|using|run|invoke|then|via)\s+`?|__)(?:windows|observe|read|choose|act|verify|trace|finish)\b')
BOOKING_GOAL = 'Book the Follow-up slot with Dr. Morgan Reyes that starts at 1:45 PM'
ORDERS_GOAL = 'Cancel the Walnut desk lamp order that is still Processing'
BOOK_1_45 = [{'line': 'eq', 'value': 'Dr. Morgan Reyes'}, {'line': 'eq', 'value': 'Follow-up'}, {'line': 'contains', 'value': '1:45 PM'}]
CANCEL_1044 = [{'line': 'eq', 'value': 'Walnut desk lamp'}, {'line': 'eq', 'value': 'Processing'}]


def orders_dialog(text):
    """orders_flow with a different dialog text (a dialog that belongs to ANOTHER record)."""
    base = lv.orders_flow(None)
    def script(d, els):
        out = base(d, els)
        for e in out or []:
            if e['element_index'] == 16:e['label'] = e['value'] = text
        return out
    return script


def G(response, *path):
    """Safe traversal: a missing key or index is None, so a wrong behavior fails an ASSERTION on the value instead of raising KeyError."""
    for key in path:
        try:response = response[key]
        except (KeyError, IndexError, TypeError):return None
    return response


def S(response, *path):
    """G for text: '' when missing (assertIn on a missing hint is then an assertion failure, not a TypeError)."""
    value = G(response, *path)
    return value if isinstance(value, str) else ''


class PlanBase(unittest.TestCase):
    def build(self, driver, patterns=None, chooser=None, clock=None):
        self.driver = driver;self.reader = lv.LiveReader(patterns or {});self.chooser = chooser or FakeChooser();self.visual = lv.UnknownVision()
        self.naps, self.tools, self.seen = [], [], []
        driver.on_tool = self.tools.append
        kw = {} if clock is None else {'clock': clock}
        self.f = Facade(driver, generic_factory=lambda: self.chooser, reader_factory=lambda: self.reader, visual_factory=lambda: self.visual, sleep=self.naps.append, **kw)
        return self.f

    def booking(self, **kw):
        d = lv.LiveDriver('live_booking_ax.json');d.script = lv.booked();return self.build(d, lv.BOOKING_PATTERNS, **kw)

    def orders(self, script=None, **kw):
        d = lv.LiveDriver('live_orders_ax.json');d.script = script or lv.orders_flow(d);return self.build(d, lv.ORDER_PATTERNS, **kw)

    def shape(self, els, script=None, **kw):
        d = sh.ShapeDriver(els);d.script = script;return self.build(d, sh.PATTERNS, **kw)

    def look(self, **kw):
        return self.f.look('Demo', **kw)

    def plan(self, steps, goal=BOOKING_GOAL, **kw):
        kw.setdefault('title', 'Demo');kw.setdefault('expect', None)
        result = self.f.do(goal, steps=steps, **kw);self.seen.append(result);return result

    def lines_press(self, conds=BOOK_1_45, **kw):
        return {'do': 'press', 'where': {'lines': conds}, 'expect': 'Booked:', **kw}

    def clicked(self):
        return [e['element_token'].rsplit(':', 1)[1] for e in self.driver.executed]

    def tearDown(self):
        for r in getattr(self, 'seen', []):
            text = json.dumps(r)
            self.assertFalse(PRIMITIVES.search(text), (r.get('reason'), PRIMITIVES.findall(text)))
            self.assertLessEqual(len(text), 6144)


class Validation(PlanBase):
    """The whole plan is validated BEFORE any Driver action: no tool call, no observation, no click."""
    def setUp(self):self.booking()

    def refused(self, steps, reason, **kw):
        r = self.plan(steps, **kw)
        self.assertEqual((G(r, 'status'), G(r, 'reason'), G(r, 'delivery'), (G(r, 'steps') or [])), ('refused', reason, 'none', []), r.get('message'))
        self.assertEqual((self.tools, self.driver.version, self.driver.executed, self.reader.requests), ([], 0, [], []))
        self.assertTrue(G(r, 'follow_up_needed'));return r

    def test_more_than_ten_steps_is_refused(self):
        self.refused([{'do': 'verify', 'expect': 'Booked:'}] * 11, 'bad_request')

    def test_empty_and_malformed_plans_are_refused(self):
        for steps in ([], 'press', [1], [{}], [{'do': 'press'}]):
            self.refused(steps, 'bad_request')

    def test_an_unknown_do_is_refused(self):
        # Wrong patch: ignore an unknown step kind (it could be a click the validator never saw).
        r = self.refused([{'do': 'drag', 'control': 'Book', 'expect': 'Booked:'}], 'bad_request');self.assertIn('press, type, confirm, verify', S(r, 'message'))

    def test_unknown_keys_are_refused(self):
        self.refused([{'do': 'press', 'control': 'Book', 'expect': 'Booked:', 'coordinates': [1, 2]}], 'bad_request')

    def test_null_expect_on_a_non_final_step_is_refused_before_any_click(self):
        # Wrong patch: allow expect=null anywhere (a step whose outcome nobody checked, then more clicks on top of it).
        for first in ({'do': 'press', 'control': 'Book', 'expect': None}, {'do': 'press', 'control': 'Book'}, {'do': 'type', 'control': 'Name', 'text': 'a'}):
            r = self.refused([first, {'do': 'verify', 'expect': 'Booked:'}], 'expect_required');self.assertIn('step 1', S(r, 'message'))

    def test_a_verify_step_needs_expect_even_as_the_last_step(self):
        self.refused([{'do': 'verify'}], 'expect_required')
        self.refused([{'do': 'press', 'control': 'Book', 'expect': 'Booked:'}, {'do': 'verify', 'expect': None}], 'expect_required')

    def test_type_needs_control_and_text_and_press_needs_a_target(self):
        self.refused([{'do': 'type', 'control': 'Name', 'expect': 'x'}, {'do': 'verify', 'expect': 'x'}], 'bad_request')
        self.refused([{'do': 'type', 'text': 'Ada', 'expect': 'x'}, {'do': 'verify', 'expect': 'x'}], 'bad_request')
        self.refused([{'do': 'press', 'expect': 'x'}], 'bad_request')

    def test_confirm_is_only_an_explicit_step_after_a_press_with_an_exact_label(self):
        # Wrong patch: a `confirm` field on the press step that clicks whatever dialog appears (the dialog's identity is never checked).
        r = self.refused([{'do': 'confirm', 'confirm': 'Yes', 'dialog_text': ['x'], 'dialog_controls': ['Yes'], 'expect': 'x'}], 'bad_request');self.assertIn('follow a press', S(r, 'message'))
        self.refused([{'do': 'verify', 'expect': 'x'}, {'do': 'confirm', 'confirm': 'Yes', 'dialog_text': ['x'], 'dialog_controls': ['Yes'], 'expect': 'x'}], 'bad_request')
        self.refused([{'do': 'press', 'control': 'Book', 'expect': 'x', 'confirm': 'Yes'}], 'bad_request')
        self.refused([{'do': 'press', 'control': 'Book', 'expect': 'x'}, {'do': 'confirm', 'expect': 'x'}], 'bad_request')
        self.refused([{'do': 'press', 'control': 'Book', 'expect': 'x'}, {'do': 'confirm', 'confirm': '  ', 'expect': 'x'}], 'bad_request')

    def test_where_takes_lines_or_fields_never_both_and_never_neither(self):
        fields = {'p': {'description': 'Provider'}}
        for where in ({}, {'lines': BOOK_1_45, 'fields': fields}, {'lines': BOOK_1_45, 'predicates': []}, {'lines': []}, {'nope': 1}):
            self.refused([{'do': 'press', 'where': where, 'expect': 'x'}], 'bad_request')

    def test_line_conditions_are_checked(self):
        for cond in ({'line': 'like', 'value': 'x'}, {'line': 'eq', 'value': ''}, {'line': 'eq', 'value': 'x' * 61}, {'line': 'eq'}, {'value': 'x'}, {'line': 'eq', 'value': 'x', 'extra': 1}):
            self.refused([{'do': 'press', 'where': {'lines': [cond]}, 'expect': 'x'}], 'bad_request')
        self.refused([{'do': 'press', 'where': {'lines': [{'line': 'contains', 'value': str(i)} for i in range(7)]}, 'expect': 'x'}], 'bad_request')

    def test_where_lines_without_a_look_id_is_refused_before_any_click_and_points_at_look(self):
        # Wrong patch: allow a filter over lines with no look (the live failure: a filter written blind; here the LLM could not even have seen the strings).
        r = self.refused([self.lines_press()], 'look_required')
        self.assertIn('look', S(r, 'hint'));self.assertIn('look_id', S(r, 'hint'));self.assertIn('filter written without seeing the page', S(r, 'message'))

    def test_an_invented_look_id_is_refused(self):
        # Wrong patch: accept any string as a look_id (the LLM could then filter blind and merely say it had looked).
        r = self.refused([self.lines_press()], 'unknown_look_id', look_id='lk_0123456789')
        self.assertIn('look', S(r, 'hint'))

    def test_a_look_id_alone_does_not_make_a_plan_and_a_plan_cannot_mix_single_step_arguments(self):
        r = self.f.do(BOOKING_GOAL, title='Demo', expect=None, look_id='lk_1');self.assertEqual((G(r, 'status'), G(r, 'reason')), ('refused', 'bad_request'))
        for extra in ({'records': {'fields': lv.BOOKING_FIELDS}}, {'control': 'Book'}, {'text': 'x'}, {'accept_unknown': ['e1']}, {'confirm': 'Yes'}, {'treat_as_match': ['e1']}, {'near': 'Toolbar'}, {'operation': 'verify'}):
            self.refused([{'do': 'verify', 'expect': 'Booked:'}], 'bad_request', **extra)
        self.refused([{'do': 'verify', 'expect': 'Booked:'}], 'bad_request', expect='Booked:')

    def test_title_or_pid_and_a_positive_budget_are_required(self):
        self.refused([{'do': 'verify', 'expect': 'x'}], 'bad_request', title=None)
        self.refused([{'do': 'verify', 'expect': 'x'}], 'bad_request', pid=1, window_id=2)
        self.refused([{'do': 'verify', 'expect': 'x'}], 'bad_request', budget_s=0)

    def test_an_answer_leak_in_the_goal_or_a_step_goal_is_refused_before_any_call(self):
        self.refused([{'do': 'verify', 'expect': 'x'}], 'refused', goal='Book e44')
        self.refused([{'do': 'verify', 'expect': 'x', 'goal': 'the correct one is Dr. B'}], 'refused')
        self.refused([{'do': 'verify', 'expect': 'x', 'goal': 'press e12'}], 'refused')

    def test_a_destructive_literal_control_is_refused_unless_the_plan_goal_says_so(self):
        # Wrong patch: no destructive guard on plans (option D's guard, applied here). Goal text never unlocks it: only the step's allow_destructive does.
        for label in ('Delete account', 'Remove item', 'Erase all', 'Discard draft', 'Reset password', 'Sign out'):
            r = self.refused([{'do': 'press', 'control': label, 'expect': 'x'}], 'destructive_control', goal='Update my profile photo');self.assertIn('allow_destructive', S(r, 'message'))
        self.refused([{'do': 'press', 'control': 'Book'}, {'do': 'press', 'control': 'Book'}], 'expect_required')  # ordering: the missing expect is reported, not masked
        r = self.plan([{'do': 'press', 'control': 'Delete account', 'expect': 'Deleted'}], goal='Delete my account')
        self.assertEqual(G(r, 'reason'), 'destructive_control')  # the goal says delete: still refused
        r = self.plan([{'do': 'press', 'control': 'Delete account', 'allow_destructive': 'Delete account', 'expect': 'Deleted'}], goal='Delete my account')
        self.assertNotEqual(G(r, 'reason'), 'destructive_control')  # declared on the step: validation passes (the run then finds no such control)

    def test_a_destructive_confirm_label_is_refused_unless_the_step_declares_it(self):
        self.refused([{'do': 'press', 'control': 'Book', 'expect': 'x'}, {'do': 'confirm', 'confirm': 'Yes, delete everything', 'dialog_text': ['Delete everything?'], 'dialog_controls': ['Yes, delete everything'], 'expect': 'x'}], 'destructive_control', goal='Update my profile')

    def test_a_bad_abort_if_is_refused(self):
        for abort in ('', '  ', 'x' * 201, 5):
            self.refused([{'do': 'verify', 'expect': 'x'}], 'bad_request', abort_if=abort)


class BookingPlans(PlanBase):
    """The REAL captured booking page (12 identical Book buttons): look, then plan."""
    def setUp(self):self.booking()

    def test_look_then_lines_plan_books_the_right_slot_with_no_reader_and_no_chooser(self):
        look = self.look()
        r = self.plan([self.lines_press()], look_id=look['look_id'])
        self.assertEqual((G(r, 'status'), G(r, 'delivery'), G(r, 'follow_up_needed'), [s['status'] for s in (G(r, 'steps') or [])]), ('done', 'delivered', False, ['done']))
        self.assertEqual((self.reader.requests, self.chooser.requests, self.clicked()), ([], [], ['44']))
        self.assertEqual(G(r, 'steps', 0, 'verification'), {'status': 'satisfied', 'route': 'ax_expect_contains'})
        self.assertIn('Dr. Morgan Reyes', G(r, 'steps', 0, 'selected', 'description'))
        self.assertNotRegex(json.dumps(r), r'"e\d+"')  # no element ids in a plan response

    def test_the_half_hour_slot_is_found_by_the_string_the_look_showed(self):
        # The live failure: the blind filter said duration contains "30" and booked a decoy. The LLM that SAW "half-hour" filters on it.
        look = self.look()
        conds = [{'line': 'eq', 'value': 'Dr. Morgan Reyes'}, {'line': 'eq', 'value': 'half-hour'}]
        r = self.plan([self.lines_press(conds)], look_id=look['look_id'], goal='Book the Morgan Reyes half-hour slot')
        self.assertEqual((G(r, 'status'), self.clicked(), self.reader.requests), ('done', ['70'], []))  # the Telehealth slot's Book, never a "30 min" decoy

    def test_a_plan_of_one_step_is_the_single_step_call(self):
        # A single-step call is a one-step plan: the same record, the same click, the same verification.
        look = self.look()
        one = self.plan([{'do': 'press', 'where': {'fields': lv.BOOKING_FIELDS, 'predicates': lv.BOOKING_ONE}, 'expect': 'Booked:'}])
        self.assertEqual((G(one, 'status'), self.clicked()), ('done', ['44']))
        self.booking()
        single = self.f.do(BOOKING_GOAL, title='Demo', expect='Booked:', records={'fields': lv.BOOKING_FIELDS, 'predicates': lv.BOOKING_ONE})
        self.assertEqual((G(single, 'status'), self.clicked()), ('done', ['44']))

    def test_a_filter_matching_no_displayed_record_defers_and_clicks_nothing(self):
        look = self.look()
        r = self.plan([self.lines_press([{'line': 'eq', 'value': 'Dr. Nobody'}])], look_id=look['look_id'])
        self.assertEqual((G(r, 'status'), G(r, 'failed_step'), G(r, 'reason'), G(r, 'delivery'), self.driver.executed), ('stopped', 1, 'no_matching_record', 'none', []))
        self.assertEqual(G(r, 'steps', 0, 'evidence', 'match_count'), 0)

    def test_several_matches_defer_with_their_lines_and_the_chooser_is_never_asked(self):
        # Wrong patch: hand several matches to the chooser (a model on the common path) or click the first.
        look = self.look()
        r = self.plan([self.lines_press([{'line': 'eq', 'value': 'Dr. Morgan Reyes'}, {'line': 'eq', 'value': 'Follow-up'}])], look_id=look['look_id'])
        self.assertEqual((G(r, 'status'), G(r, 'reason'), self.driver.executed, self.chooser.requests, self.visual.calls), ('stopped', 'where_matches_several', [], [], 0))
        ev = G(r, 'steps', 0, 'evidence');self.assertEqual(ev['match_count'], 4);self.assertEqual(len(ev['matches']), 4)
        self.assertIn('Add a condition', S(r, 'hint'))

    def test_neq_and_not_contains_are_conjunctive_with_the_rest(self):
        look = self.look()
        r = self.plan([self.lines_press(BOOK_1_45 + [{'line': 'not_contains', 'value': '1:45'}])], look_id=look['look_id'])
        self.assertEqual((G(r, 'reason'), self.driver.executed), ('no_matching_record', []))  # the 1:45 record is excluded by its own contradiction
        r = self.plan([self.lines_press(BOOK_1_45[:2] + [{'line': 'not_contains', 'value': 'PM'}])], look_id=look['look_id'])
        self.assertEqual((G(r, 'status'), self.clicked()), ('done', ['75']))  # the only AM Follow-up slot of Dr. Morgan Reyes
        self.booking();look = self.look()
        conds = [{'line': 'eq', 'value': 'Dr. Morgan Reyes'}, {'line': 'neq', 'value': 'Consultation'}, {'line': 'neq', 'value': 'Telehealth'}, {'line': 'contains', 'value': '11:00 AM'}]
        r = self.plan([self.lines_press(conds)], look_id=look['look_id'])
        self.assertEqual((G(r, 'status'), self.clicked()), ('done', ['75']))

    def test_matching_is_case_and_whitespace_insensitive_like_the_displayed_strings(self):
        look = self.look()
        conds = [{'line': 'eq', 'value': '  dr.  morgan reyes '}, {'line': 'eq', 'value': 'FOLLOW-UP'}, {'line': 'contains', 'value': 'starts 1:45 pm'}]
        self.assertEqual(self.plan([self.lines_press(conds)], look_id=look['look_id'])['status'], 'done')

    def test_a_record_the_look_did_not_show_is_never_a_candidate(self):
        # Wrong patch: match over every record on the page although the LLM only saw a focused subset (a filter over strings it never saw).
        look = self.look(focus='1:45')
        self.assertEqual([r['r'] for r in look['records']], ['r5'])
        r = self.plan([self.lines_press([{'line': 'contains', 'value': '3:15 PM'}])], look_id=look['look_id'])
        self.assertEqual((G(r, 'reason'), self.driver.executed), ('no_matching_record', []))
        self.assertEqual(G(r, 'steps', 0, 'evidence', 'outside_look'), 11)
        ok = self.plan([self.lines_press([{'line': 'contains', 'value': '1:45 PM'}])], look_id=look['look_id'])
        self.assertEqual((G(ok, 'status'), self.clicked()), ('done', ['44']))

    def test_page_changed_since_look_defers_and_clicks_nothing(self):
        # Wrong patch: run the filter over the CURRENT lines whatever the look said (the LLM planned against strings that are no longer there).
        look = self.look()
        def moved(d, els):
            for e in els:
                if e['element_index'] == 43:e['label'] = e['value'] = 'Starts 1:15 PM'  # the 1:45 slot moves
        self.driver.script = moved
        r = self.plan([self.lines_press()], look_id=look['look_id'])
        self.assertEqual((G(r, 'status'), G(r, 'failed_step'), G(r, 'reason'), G(r, 'delivery'), self.driver.executed), ('stopped', 1, 'page_changed_since_look', 'none', []))
        self.assertEqual(G(r, 'steps', 0, 'found'), {'records': 12, 'record_kind': 'flat-list'})
        self.assertIn('look', S(r, 'hint'));self.assertNotIn('lk_', json.dumps(r))  # never a fresh id the LLM has not seen the lines of
        self.assertEqual(self.reader.requests, [])

    def test_a_look_of_another_window_does_not_authorize_a_filter_here(self):
        look = self.look()
        self.f.looks[(1, 99, look['look_id'])] = self.f.looks.pop((1, 2, look['look_id']))  # as if that look had been of another window
        r = self.plan([self.lines_press()], look_id=look['look_id'])
        self.assertEqual((G(r, 'status'), G(r, 'delivery'), self.driver.executed), ('refused', 'none', []))
        self.assertEqual(G(r, 'steps', 0, 'reason'), 'look_window_mismatch')

    def test_a_look_that_was_focused_or_capped_still_proves_only_what_it_showed(self):
        look = self.look(max_records=5)
        self.assertEqual(len(look['records']), 5)
        r = self.plan([self.lines_press([{'line': 'contains', 'value': '1:45 PM'}])], look_id=look['look_id'])
        self.assertEqual((G(r, 'status'), self.clicked()), ('done', ['44']))  # r5 is among the first five
        r = self.plan([self.lines_press([{'line': 'contains', 'value': '3:15 PM'}])], look_id=look['look_id'])
        self.assertEqual(G(r, 'reason'), 'no_matching_record')  # r7 is beyond the cap the look reported

    def test_blind_fields_predicates_still_defer_and_treat_as_match_finishes(self):
        # Preserved (S4.2 s4): the incomparable value is unknown, never excluded, and nothing is clicked until the caller judges it.
        blind = {'fields': lv.BOOKING_FIELDS, 'predicates': [{'field': 'provider', 'op': 'contains', 'value': 'Morgan Reyes'}, {'field': 'duration', 'op': 'contains', 'value': '30'}]}
        first = self.plan([{'do': 'press', 'where': blind, 'expect': 'Booked:'}], goal='Book the Morgan Reyes half-hour slot')
        self.assertEqual((G(first, 'status'), G(first, 'reason'), self.driver.executed), ('stopped', 'unknown_competitors_unacknowledged', []))
        step = G(first, 'steps', 0)
        self.assertTrue(step['unknown_ids']);self.assertIn('half-hour', json.dumps(step['evidence']));self.assertIn('treat_as_match', S(first, 'hint'))

        class ByDescription(FakeChooser):
            def __call__(self, step_, request):
                self.requests.append(request);pick = next((a for a in request['actions'] if 'Telehealth' in a['description']), request['actions'][0])
                return {'choice': pick['id'], 'route': 'julia-1', 'action_authorized': True}
        self.booking(chooser=ByDescription())
        second = self.plan([{'do': 'press', 'where': blind, 'treat_as_match': step['unknown_ids'], 'expect': 'Booked:'}], goal='Book the Morgan Reyes half-hour slot')
        self.assertEqual((G(second, 'status'), self.clicked(), len(self.chooser.requests)), ('done', ['70'], 1))  # the controller judged "half-hour" = 30 minutes; the chooser picks among eligible only

    def test_a_final_step_without_expect_ends_delivered_unverified_never_done(self):
        look = self.look()
        r = self.plan([{'do': 'press', 'where': {'lines': BOOK_1_45}}], look_id=look['look_id'])
        self.assertEqual((G(r, 'status'), G(r, 'follow_up_needed'), G(r, 'delivery'), self.clicked()), ('delivered_unverified', True, 'delivered', ['44']))
        self.assertIn('Do not click again', S(r, 'hint'))

    def test_an_expect_that_never_appears_is_never_done_and_the_click_is_not_repeated(self):
        look = self.look()
        r = self.plan([self.lines_press(expect='Payment received'), {'do': 'verify', 'expect': 'Booked:'}], look_id=look['look_id'])
        self.assertEqual((G(r, 'status'), G(r, 'failed_step'), G(r, 'reason'), G(r, 'delivery'), self.clicked(), len((G(r, 'steps') or []))), ('stopped', 1, 'delivery_unverified', 'delivered', ['44'], 1))
        self.assertIn('do not click again', S(r, 'hint').lower())

    def test_a_verify_only_plan_reports_observed_and_never_clicks(self):
        self.plan([self.lines_press()], look_id=self.look()['look_id'])
        clicks = len(self.driver.executed)
        r = self.plan([{'do': 'verify', 'expect': 'Booked:'}])
        self.assertEqual((G(r, 'status'), G(r, 'follow_up_needed'), len(self.driver.executed)), ('observed', False, clicks))
        r = self.plan([{'do': 'verify', 'expect': 'Refund issued'}])
        self.assertEqual((G(r, 'status'), G(r, 'reason')), ('stopped', 'not_verified'))

    def test_control_labels_never_prove_a_verify_step(self):
        r = self.plan([{'do': 'verify', 'expect': 'Book'}]);self.assertEqual(G(r, 'status'), 'stopped')


class OrdersPlans(PlanBase):
    """The REAL captured orders table (rows with Track and Cancel; the confirm dialog is page content, no AXSheet)."""
    def setUp(self):self.orders()

    DIALOG = ['Cancel order #1044 (Walnut desk lamp)?']  # what the captured orders flow shows; a confirm step must declare the dialog's complete text

    def cancel(self, identity=('#1044',), confirm='Yes, cancel order', press_expect='Cancel order #1044', dialog=None, **kw):
        press = {'do': 'press', 'where': {'lines': CANCEL_1044}, 'control': 'Cancel', 'expect': press_expect, **({'identity': list(identity)} if identity else {})}
        steps = [press, {'do': 'confirm', 'confirm': confirm, 'expect': 'Order #1044 cancelled', 'dialog_text': dialog or self.DIALOG, 'dialog_controls': ['Yes, cancel order', 'Keep order']}]
        return self.plan(steps, goal=ORDERS_GOAL, look_id=self.look()['look_id'], **kw)

    def test_press_then_an_explicit_confirm_step_cancels_the_right_order_with_no_reader_call(self):
        r = self.cancel()
        self.assertEqual((G(r, 'status'), [s['status'] for s in (G(r, 'steps') or [])], G(r, 'delivery')), ('done', ['done', 'done'], 'delivered'))
        self.assertEqual(self.clicked(), ['67', '17'])  # #1044's Cancel, then the dialog's own button; never Track, never another row
        self.assertEqual((self.reader.requests, self.chooser.requests), ([], []))

    def test_a_dialog_that_shows_only_part_of_the_identity_is_never_pressed(self):
        # Wrong patch: press the confirm label because the dialog appeared (the dialog's identity is the safety property).
        # Default identity = the values the plan required (Walnut desk lamp, Processing); the dialog does not show "Processing".
        r = self.cancel(identity=None)
        self.assertEqual((G(r, 'status'), G(r, 'failed_step'), G(r, 'reason'), self.clicked()), ('stopped', 2, 'confirm_identity_partial', ['67']))
        step = G(r, 'steps', 1);self.assertEqual((step['dialog']['identity'], step['identity_shown'], step['identity_not_shown']), ('partial', 1, 1))
        self.assertIn('Cancel order #1044 (Walnut desk lamp)?', step['dialog']['lines']);self.assertEqual(step['dialog']['controls'], ['Yes, cancel order', 'Keep order'])
        self.assertIn('already done', S(r, 'hint'));self.assertIn('press', S(r, 'hint'))

    def test_a_dialog_that_belongs_to_another_record_is_never_pressed(self):
        self.orders(script=orders_dialog('Cancel order #1041 (Walnut desk lamp)?'))
        r = self.cancel(press_expect='Cancel order', dialog=['Cancel order #1041 (Walnut desk lamp)?'])  # the press's own expect is generic enough to accept this dialog; the identity check must not
        self.assertEqual((G(r, 'status'), G(r, 'reason'), self.clicked(), G(r, 'steps', 1, 'dialog', 'identity')), ('stopped', 'confirm_identity_unknown', ['67'], 'unknown'))

    def test_the_confirm_label_is_matched_exactly_not_as_a_prefix(self):
        # Wrong patch: reuse press's whole-word-prefix control matching for the confirm label.
        r = self.cancel(confirm='Yes')  # "Yes" is not one of the declared dialog_controls: refused before any click (and exact-match at run time as before)
        self.assertEqual((G(r, 'status'), G(r, 'reason'), self.clicked()), ('refused', 'bad_request', []))

    def test_a_confirm_label_that_only_exists_outside_the_dialog_is_never_pressed(self):
        self.shape(sh.cards(), sh.dialog_then_toast(['Yes', 'No']))
        look = self.look()
        steps = [{'do': 'press', 'where': {'lines': [{'line': 'eq', 'value': 'Dr. B'}]}, 'control': 'Book', 'expect': 'Confirm Dr. B'},
                 {'do': 'confirm', 'confirm': 'Book', 'dialog_text': ['Confirm Dr. B'], 'dialog_controls': ['Yes', 'No', 'Book'], 'expect': 'Booked: Dr. B'}]
        r = self.plan(steps, look_id=look['look_id'])
        self.assertEqual((G(r, 'status'), G(r, 'steps', 1, 'reason'), len(self.driver.executed)), ('stopped', 'confirm_dialog_unexpected_text', 1))  # Book is not in the dialog: the declared controls differ from the dialog's, nothing pressed
        good = self.shape(sh.cards(), sh.dialog_then_toast(['Yes', 'No']));look = self.look()
        steps[1] = {'do': 'confirm', 'confirm': 'Yes', 'dialog_text': ['Confirm Dr. B'], 'dialog_controls': ['Yes', 'No'], 'expect': 'Booked: Dr. B'}
        r = self.plan(steps, look_id=look['look_id'])
        self.assertEqual((G(r, 'status'), len(self.driver.executed)), ('done', 2))

    def test_a_press_whose_expect_misses_the_dialog_stops_with_the_click_delivered_and_no_primitive_hint(self):
        r = self.cancel(press_expect='Are you sure')
        self.assertEqual((G(r, 'status'), G(r, 'failed_step'), G(r, 'reason'), G(r, 'delivery'), self.clicked()), ('stopped', 1, 'confirm_dialog_present', 'delivered', ['67']))
        self.assertEqual(G(r, 'steps', 0, 'dialog', 'controls'), ['Yes, cancel order', 'Keep order'])
        self.assertIn('do not repeat', S(r, 'hint').lower());self.assertIn('press', S(r, 'hint'))
        second = self.plan([{'do': 'press', 'control': 'Yes, cancel order', 'expect': 'Order #1044 cancelled'}], goal=ORDERS_GOAL)
        self.assertEqual((G(second, 'status'), self.clicked()), ('done', ['67', '17']))  # the dialog's own control, never the row's Cancel again

    def test_confirm_after_a_fields_press_uses_the_selected_records_identity_without_a_reader_call_for_the_dialog(self):
        fields = {'order': {'description': 'Order number'}, 'item': {'description': 'Item'}, 'status': {'description': 'Status'}}
        where = {'fields': fields, 'predicates': [{'field': 'order', 'value': '#1044'}]}
        r = self.plan([{'do': 'press', 'where': where, 'control': 'Cancel', 'identity': ['order'], 'expect': 'Cancel order #1044'},
                       {'do': 'confirm', 'confirm': 'Yes, cancel order', 'dialog_text': ['Cancel order #1044 (Walnut desk lamp)?'], 'dialog_controls': ['Yes, cancel order', 'Keep order'], 'expect': 'Order #1044 cancelled'}], goal=ORDERS_GOAL)
        self.assertEqual((G(r, 'status'), self.clicked()), ('done', ['67', '17']))
        self.assertEqual(len(self.reader.requests), 1)  # the press's read only; the dialog is checked by displayed strings

    def test_a_missing_control_choice_defers_with_the_repeated_labels(self):
        look = self.look()
        r = self.plan([{'do': 'press', 'where': {'lines': CANCEL_1044}, 'expect': 'x'}], goal=ORDERS_GOAL, look_id=look['look_id'])
        self.assertEqual((G(r, 'reason'), self.driver.executed), ('control_needed', []))
        self.assertEqual({c['label'] for c in G(r, 'steps', 0, 'found', 'repeated_controls')}, {'Track', 'Cancel'});self.assertIn('control', S(r, 'hint'))

    def test_the_dialog_that_appeared_is_not_confirmable_without_a_previous_press(self):
        r = self.plan([{'do': 'confirm', 'confirm': 'Yes, cancel order', 'expect': 'x'}], goal=ORDERS_GOAL)
        self.assertEqual(G(r, 'reason'), 'bad_request')


class WizardPlans(PlanBase):
    """A 3-step wizard-shaped synthetic page: three deterministic steps in one do."""
    def setUp(self):self.shape(sh.wizard_els(1), sh.wizard_script)

    def steps(self, last='Finish'):
        return [{'do': 'press', 'control': 'Next', 'expect': 'Step 2 of 3'}, {'do': 'press', 'control': 'Next', 'expect': 'Step 3 of 3'}, {'do': 'press', 'control': last, 'expect': 'Setup complete.'}]

    def test_three_steps_run_in_one_call_each_on_a_fresh_observation_with_a_new_selection(self):
        # Wrong patch: bind every step's selection once on the first observation and replay it (a stale token or the wrong control on the next screen).
        r = self.plan(self.steps(), goal='Complete the setup wizard')
        self.assertEqual((G(r, 'status'), [s['status'] for s in (G(r, 'steps') or [])]), ('done', ['done'] * 3))
        self.assertEqual(len(self.driver.executed), 3)
        tokens = [e['element_token'].split(':')[0] for e in self.driver.executed]
        self.assertEqual(len(set(tokens)), 3)  # three different observations, each click bound to its own
        self.assertEqual(tokens, sorted(tokens))
        selects = [e for e in self.f.events if e['operation'] == 'choose']
        self.assertEqual(len({e['snapshot'] for e in selects}), 3)
        observes = [e['snapshot'] for e in self.f.events if e['operation'] == 'observe']
        self.assertGreaterEqual(len(observes), 9)  # per step: observe, the act revalidation, verify
        used = [s for s in self.f.selections.values()];self.assertEqual((len(used), all(s['used'] for s in used)), (3, True))
        self.assertEqual((self.reader.requests, self.chooser.requests), ([], []))
        self.assertLessEqual(len(json.dumps(r)), 2500)

    def test_the_plan_stops_at_the_first_step_that_is_not_done_and_never_runs_the_rest(self):
        # Wrong patch: keep executing the remaining steps after a failed one (clicks on a screen the plan no longer describes).
        steps = self.steps();steps[1]['expect'] = 'Step 9 of 3'
        r = self.plan(steps, goal='Complete the setup wizard')
        self.assertEqual((G(r, 'status'), G(r, 'failed_step'), G(r, 'reason'), len((G(r, 'steps') or [])), len(self.driver.executed)), ('stopped', 2, 'delivery_unverified', 2, 2))
        self.assertEqual([s['status'] for s in (G(r, 'steps') or [])], ['done', 'stopped']);self.assertIn('already done', S(r, 'hint'))

    def test_a_missing_control_stops_before_any_click_of_that_step_and_lists_what_is_pressable(self):
        r = self.plan(self.steps('Submit'), goal='Complete the setup wizard')
        self.assertEqual((G(r, 'status'), G(r, 'failed_step'), G(r, 'reason'), len(self.driver.executed)), ('stopped', 3, 'control_not_found', 2))
        self.assertEqual(sorted(G(r, 'steps', 2, 'found', 'controls')), ['Back', 'Cancel', 'Finish'])
        self.assertEqual(G(r, 'steps', 2, 'status'), 'stopped')

    def test_abort_if_stops_the_plan_after_the_step_that_shows_it(self):
        def script(d, els):
            wiz = sh.wizard_els(1 + len(d.executed))
            if len(d.executed) >= 1:sh.E(wiz, 1, 'AXStaticText', 'Error: session expired', 'Error: session expired')
            return wiz
        self.shape(sh.wizard_els(1), script)
        r = self.plan(self.steps(), goal='Complete the setup wizard', abort_if='session expired')
        self.assertEqual((G(r, 'status'), G(r, 'failed_step'), G(r, 'reason'), len(self.driver.executed), len((G(r, 'steps') or []))), ('aborted', 1, 'abort_if_matched', 1, 1))
        self.assertTrue(G(r, 'follow_up_needed'));self.assertNotIn('expired', S(r, 'hint'))

    def test_abort_if_never_matches_a_button_label(self):
        r = self.plan(self.steps(), goal='Complete the setup wizard', abort_if='Cancel')  # every screen has a Cancel BUTTON
        self.assertEqual(G(r, 'status'), 'done')

    def test_a_stale_page_mid_plan_stops_at_that_step_after_one_bounded_rerun(self):
        # Step 1 lands; from then on an in-scope text changes on EVERY observation, so step 2's selection is stale twice.
        def churn(d, els):
            wiz = sh.wizard_els(1 + min(len(d.executed), 1))
            if d.executed:sh.E(wiz, 1, 'AXStaticText', 'tick %d' % d.version, 'tick %d' % d.version)
            return wiz
        self.shape(sh.wizard_els(1), churn)
        r = self.plan(self.steps(), goal='Complete the setup wizard')
        self.assertEqual((G(r, 'status'), G(r, 'failed_step'), G(r, 'reason'), len(self.driver.executed)), ('stopped', 2, 'ui_changed_repeatedly', 1))
        self.assertEqual([s['status'] for s in (G(r, 'steps') or [])], ['done', 'stopped']);self.assertEqual(G(r, 'steps', 1).get('selected'), None)

    def test_a_step_recovers_from_one_stale_refusal_inside_the_step_with_a_new_selection(self):
        # S4.2 s7: THAT step re-runs on a fresh observation with a NEW selection; the plan continues.
        after = []
        def script(d, els):
            wiz = sh.wizard_els(1 + len(d.executed))
            if len(d.executed) == 1:
                after.append(1)
                if len(after) == 2:sh.E(wiz, 1, 'AXStaticText', 'tick', 'tick')  # ONE observation of step 2 differs (its selection is stale once); later ones agree
            return wiz
        self.shape(sh.wizard_els(1), script)
        r = self.plan(self.steps(), goal='Complete the setup wizard')
        self.assertEqual((G(r, 'status'), len(self.driver.executed)), ('done', 3))
        stale = [e for e in self.f.events if e['operation'] == 'do' and e['passes'] > 1]
        self.assertTrue(stale, 'the recovery should have run a second pass inside a step')
        self.assertEqual(len(self.driver.executed), 3)  # never a repeated click

    def test_a_click_is_never_retried_and_a_driver_failure_on_it_ends_failed_with_uncertain_delivery(self):
        # Wrong patch: retry the whole step (or plan) after a failure that may already have delivered the click.
        def fail_on_click(tool):
            self.tools.append(tool)
            if tool == 'click':raise DriverCallFailed('driver_call_failed: click exited 1; the action may have been delivered, so verify before retrying /Users/x/secret')
        self.driver.on_tool = fail_on_click
        r = self.plan(self.steps(), goal='Complete the setup wizard')
        self.assertEqual((G(r, 'status'), G(r, 'failed_step'), G(r, 'delivery'), G(r, 'retryable'), self.tools.count('click')), ('failed', 1, 'uncertain', False, 1))
        self.assertNotIn('secret', json.dumps(r));self.assertNotIn('exited', json.dumps(r))
        self.assertIn('verify', S(r, 'hint'))

    def test_a_transient_failure_before_the_click_is_retried_once_inside_its_step(self):
        real, after = self.driver.observe, []
        def once(*a):
            if len(self.driver.executed) == 1:
                after.append(1)
                if len(after) == 2:raise DriverCallFailed('driver_call_failed: get_window_state exited 1')  # step 1's verify observed first; this is step 2's own observation
            return real(*a)
        self.driver.observe = once
        r = self.plan(self.steps(), goal='Complete the setup wizard')
        self.assertEqual((G(r, 'status'), len(self.driver.executed), self.naps), ('done', 3, [self.f.RETRY_BACKOFF_S]))

    def test_the_plan_wall_budget_stops_before_the_next_step_and_never_clicks_past_it(self):
        # Wrong patch: a per-step budget only (ten slow steps could run for ten times the plan's budget).
        clock = Clock();self.shape(sh.wizard_els(1), sh.wizard_script, clock=clock)
        real, after = self.driver.observe, []
        def slow_observe(*a):
            if len(self.driver.executed) == 1 and not after:after.append(1);clock.advance(31)  # step 1's verification takes the plan past 3x its budget
            return real(*a)
        self.driver.observe = slow_observe
        r = self.plan(self.steps(), goal='Complete the setup wizard', budget_s=10)
        self.assertEqual((G(r, 'status'), G(r, 'failed_step'), G(r, 'reason'), len(self.driver.executed), len((G(r, 'steps') or []))), ('stopped', 2, 'budget_exceeded', 1, 2))
        self.assertEqual(G(r, 'steps', 0, 'status'), 'done');self.assertIn('verify', S(r, 'hint'))

    def test_a_slow_click_exhausts_the_budget_and_nothing_further_is_clicked(self):
        clock = Clock();self.shape(sh.wizard_els(1), sh.wizard_script, clock=clock)
        real = self.driver.call
        def slow(tool, args, timeout=20):
            if tool == 'click':clock.advance(40)
            return real(tool, args, timeout)
        self.driver.call = slow
        r = self.plan(self.steps(), goal='Complete the setup wizard', budget_s=10)
        self.assertEqual((G(r, 'failed_step'), G(r, 'reason'), len(self.driver.executed), G(r, 'delivery')), (1, 'budget_exceeded', 1, 'delivered'))

    def test_a_ten_step_plan_and_its_stop_stay_small(self):
        r = self.plan([{'do': 'verify', 'expect': 'Step 1 of 3: Plan'}] * 9 + [{'do': 'press', 'control': 'Next', 'expect': 'Step 2 of 3'}], goal='Complete the setup wizard')
        self.assertEqual((G(r, 'status'), len((G(r, 'steps') or []))), ('done', 10))
        self.assertLess(len(json.dumps(r)), 3500)

    def test_the_summary_is_a_small_observation_not_a_dump(self):
        r = self.plan(self.steps(), goal='Complete the setup wizard')
        self.assertEqual(G(r, 'summary'), {'title': 'Demo', 'text': ['Setup complete.'], 'controls': []})


class FormPlans(PlanBase):
    def form(self):
        els, web = sh.base();sh.E(els, web, 'AXTextField', 'Name', '', actions=['AXFocus']);sh.E(els, web, 'AXButton', 'Save')
        def script(d, els_):
            typed = [e for e in d.executed if 'text' in e]
            if typed:
                for e in els_:
                    if e.get('label') == 'Name':e['value'] = typed[-1]['text']
                sh.E(els_, 1, 'AXStaticText', 'Welcome, %s' % typed[-1]['text'], 'Welcome, %s' % typed[-1]['text'])
        self.shape(els, script)

    def test_a_type_step_needs_an_expect_that_is_not_the_typed_text(self):
        # Honest limit kept from the single-step rule: the text you typed proves nothing, so a type step's expect must be another visible consequence.
        self.form()
        echo = self.plan([{'do': 'type', 'control': 'Name', 'text': 'Ada', 'expect': 'Ada'}], goal='Fill the name')
        self.assertEqual((G(echo, 'status'), G(echo, 'reason'), G(echo, 'delivery')), ('stopped', 'delivery_unverified', 'delivered'))
        self.form()
        ok = self.plan([{'do': 'type', 'control': 'Name', 'text': 'Ada', 'expect': 'Welcome'}, {'do': 'press', 'control': 'Save', 'expect': None}], goal='Fill the name and save')
        self.assertEqual((G(ok, 'status'), [s['status'] for s in (G(ok, 'steps') or [])]), ('delivered_unverified', ['done', 'delivered_unverified']))
        self.assertEqual([e for e in self.driver.executed if 'text' in e][0]['text'], 'Ada')


class DestructiveAtResolve(PlanBase):
    """The literal label passed validation; what it RESOLVES to is checked again."""
    def test_a_whole_word_prefix_that_resolves_to_a_destructive_control_is_never_pressed(self):
        # Wrong patch: guard only the literal `control` string ("Cancel" is harmless; the control it prefix-matches deletes the account).
        els, web = sh.base();sh.E(els, web, 'AXStaticText', 'Subscription', 'Subscription');sh.E(els, web, 'AXButton', 'Cancel and delete account');sh.E(els, web, 'AXButton', 'Keep')
        self.shape(els, sh.toast('Cancelled', buttons=()))
        r = self.plan([{'do': 'press', 'control': 'Cancel', 'control_match': 'prefix', 'expect': 'Cancelled'}], goal='Cancel my subscription')
        self.assertEqual((G(r, 'status'), G(r, 'reason'), G(r, 'delivery'), self.driver.executed), ('stopped', 'destructive_control', 'none', []))
        self.assertIn('allow_destructive', S(r, 'hint'))

    def test_the_resolved_control_is_not_pressed_and_leaves_no_selection_behind(self):
        els, web = sh.base();sh.E(els, web, 'AXButton', 'Cancel and delete account')
        self.shape(els, sh.toast('Cancelled', buttons=()))
        self.plan([{'do': 'press', 'control': 'Cancel', 'control_match': 'prefix', 'expect': 'Cancelled'}], goal='Cancel my subscription')
        self.assertEqual([s for s in self.f.selections.values() if not s['used']], [])

    def test_a_record_whose_only_control_is_destructive_is_not_pressed_without_the_declaration(self):
        els, web = sh.base();ul = sh.E(els, web, 'AXList')
        for n in 'AB':
            li = sh.E(els, ul, 'AXGroup');sh.E(els, li, 'AXStaticText', 'Draft ' + n, 'Draft ' + n);sh.E(els, li, 'AXButton', 'Delete draft')
        self.shape(els, sh.toast('Done', buttons=()));look = self.look()
        steps = [{'do': 'press', 'where': {'lines': [{'line': 'eq', 'value': 'Draft B'}]}, 'control': 'Delete draft', 'expect': 'Done'}]
        self.assertEqual(self.plan(steps, goal='Archive draft B', look_id=look['look_id'])['reason'], 'destructive_control')  # refused at validation: the literal label
        steps = [{'do': 'press', 'where': {'lines': [{'line': 'eq', 'value': 'Draft B'}]}, 'expect': 'Done'}]  # no literal: only the resolved control can be checked
        r = self.plan(steps, goal='Archive draft B', look_id=look['look_id'])
        self.assertEqual((G(r, 'status'), G(r, 'reason'), G(r, 'delivery'), self.driver.executed), ('stopped', 'destructive_control', 'none', []))
        no = self.plan(steps, goal='Delete draft B', look_id=look['look_id'])
        self.assertEqual((G(no, 'reason'), self.driver.executed), ('destructive_control', []))  # the goal saying delete is not a declaration
        ok = self.plan([{**steps[0], 'allow_destructive': 'Delete draft'}], goal='Delete draft B', look_id=look['look_id'])
        self.assertEqual((G(ok, 'status'), len(self.driver.executed)), ('done', 1))  # the step declared the exact label


class InvoicePlans(PlanBase):
    """The 100-row page shaped like the suite's `invoices` task, near-duplicates included."""
    def setUp(self):self.shape(sh.invoices(), sh.approved_status)

    def test_focus_then_lines_approves_the_one_invoice_with_no_reader_and_no_chooser(self):
        look = self.look(focus='Northwind')
        conds = [{'line': 'eq', 'value': 'Northwind Traders'}, {'line': 'eq', 'value': '$1,240.00'}]
        r = self.plan([{'do': 'press', 'where': {'lines': conds}, 'expect': 'Approved INV-063'}], look_id=look['look_id'], goal='Approve the invoice from Northwind Traders for $1,240.00')
        self.assertEqual((G(r, 'status'), self.reader.requests, self.chooser.requests), ('done', [], []))
        self.assertEqual(len(self.driver.executed), 1)
        # The page states which invoice the clicked button belonged to, and the step's expect named INV-063: satisfied, so the right row was pressed.
        self.assertEqual(G(r, 'steps', 0, 'verification', 'status'), 'satisfied')

    def test_a_vendor_only_filter_matches_the_near_duplicates_and_clicks_nothing(self):
        look = self.look(focus='Northwind')
        r = self.plan([{'do': 'press', 'where': {'lines': [{'line': 'contains', 'value': 'Northwind'}]}, 'expect': 'Approved INV-063'}], look_id=look['look_id'], goal='Approve the Northwind invoice')
        self.assertEqual((G(r, 'reason'), G(r, 'steps', 0, 'evidence', 'match_count'), self.driver.executed), ('where_matches_several', 6, []))
        self.assertEqual(len(G(r, 'steps', 0, 'evidence', 'matches')), 5)  # bounded

    def test_the_target_beyond_the_default_cap_is_not_selectable_without_a_focused_look(self):
        look = self.look()
        r = self.plan([{'do': 'press', 'where': {'lines': [{'line': 'eq', 'value': 'INV-063'}]}, 'expect': 'Approved INV-063'}], look_id=look['look_id'], goal='Approve invoice INV-063')
        self.assertEqual((G(r, 'reason'), self.driver.executed, G(r, 'steps', 0, 'evidence', 'outside_look')), ('no_matching_record', [], 60))
        self.assertEqual(look['truncated']['records'], 60)  # and the look said so


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'needs mcp')
class ServerSurface(PlanBase):
    def setUp(self):
        import server
        self.server = server;self.saved = server.facade
        self.booking();server.facade = self.f

    def tearDown(self):
        self.server.facade = self.saved
        super().tearDown()

    def call(self, name, **kw):
        import asyncio
        from call_budget import result_text
        return json.loads(result_text(asyncio.run(self.server.mcp.call_tool(name, kw))))

    def test_the_default_surface_is_exactly_do_then_look_and_the_primitives_are_absent(self):
        # Wrong patch: leave the primitives (or a third tool) visible beside the look.
        import asyncio
        tools = asyncio.run(self.server.mcp.list_tools())
        self.assertEqual([t.name for t in tools], ['do', 'look'])
        look = tools[1]
        self.assertTrue(look.description.startswith('Look at the page before you plan.'))
        self.assertIn('Call `look` first when the page has lists or you do not know the strings it displays; then `do`.', look.description)
        self.assertTrue(tools[0].description.startswith('Default path. Call `look` first when the page has lists or you do not know the strings; then `do`.'))
        for name in ('max_records', 'max_bytes', 'focus', 'fields', 'title', 'pid', 'window_id'):self.assertIn(name, look.inputSchema['properties'])
        self.assertEqual(look.inputSchema.get('required', []), [])
        self.assertTrue(look.annotations.readOnlyHint)
        for name in ('steps', 'look_id', 'abort_if'):self.assertIn(name, tools[0].inputSchema['properties'])
        self.assertIn('expect', tools[0].inputSchema['required'])
        self.assertIn('look', self.server.mcp.instructions);self.assertFalse(PRIMITIVES.search(self.server.mcp.instructions))
        self.assertLess(self.server.mcp.instructions.index('`look`'), self.server.mcp.instructions.index('`do`'))

    def test_look_then_do_over_the_real_tools(self):
        look = self.call('look', title='Demo')
        self.assertEqual((look['status'], look['record_kind']), ('ok', 'flat-list'))
        r = self.call('do', goal=BOOKING_GOAL, expect=None, title='Demo', look_id=look['look_id'], steps=[{'do': 'press', 'where': {'lines': BOOK_1_45}, 'expect': 'Booked:'}])
        self.assertEqual((G(r, 'status'), self.clicked(), self.reader.requests), ('done', ['44'], []))

    def test_an_unknown_do_over_the_tool_is_a_structured_refusal_not_a_schema_error(self):
        r = self.call('do', goal='x', expect=None, title='Demo', steps=[{'do': 'drag', 'control': 'Book', 'expect': 'x'}])
        self.assertEqual((G(r, 'status'), G(r, 'reason')), ('refused', 'bad_request'))

    def test_the_single_step_form_is_unchanged_over_the_tool(self):
        r = self.call('do', goal=BOOKING_GOAL, expect='Booked:', title='Demo', records={'fields': lv.BOOKING_FIELDS, 'predicates': lv.BOOKING_ONE})
        self.assertEqual((G(r, 'status'), r['judgment'], self.clicked(), len(self.reader.requests)), ('done', 'filter', ['44'], 1))
        self.assertNotIn('steps', r)


if __name__ == '__main__':unittest.main()
