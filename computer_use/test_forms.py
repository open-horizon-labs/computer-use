"""A select and a checkbox of a web form through the existing type and press steps (forms.py).

Found live (A/B suite 2026-10-01): the agent typed text fields but could not choose a <select> option or tick "Email me a copy". The tree is the real captured
form (fixtures/real/form_select_checkbox.ax.json: the committed real form capture plus the two controls read from the live transcripts' look output, see its
source note). The Driver is faked at set_value / click with the answers the Driver documents (set_value on an AXPopUpButton presses the child option, no
native popup). Each test names the tempting wrong patch it fails. No desktop, browser, model or network.
"""
import copy
import unittest

import core
import plan as planmod
import test_live_shapes as lv
from core import DriverCallFailed, Facade, MUTATING_TOOLS
from test_core import FakeChooser

POPUP, ITEM, BOX = 27, 29, 30
NAME, SELECT, COPY = 'Full name', 'Department', 'Email me a copy of this request'
OPTIONS = ('Choose one', 'Sales', 'Support', 'Billing', 'Other')


class FormDriver(lv.LiveDriver):
    """Serves the captured form; `shown` and `checked` are the page's real state, changed by set_value / click the way the page would.
    set_mode: ok | ci | ignored (answers ok, nothing changes) | wrong (selects Other) | refuse | fail | lag (shows it from the 2nd observation on).
    press_mode: ok | ignored | lag."""
    def __init__(self):
        super().__init__('real/form_select_checkbox.ax.json')
        self.shown, self.checked = 'Choose one', False
        self.set_mode, self.press_mode = 'ok', 'ok'
        self.listed = False          # an open popup lists every option; a closed one only the selected option (the live transcript's first look)
        self.sets, self.clicks, self.pending = [], [], None
        self.twin_select = self.twin_box = self.disabled_select = self.disabled_box = False
        self.script = self.page
    def call(self, tool, args, timeout=20):
        self.on_tool and self.on_tool(tool)
        if tool == 'set_value':
            self.sets.append(copy.deepcopy(args))
            if self.set_mode == 'refuse':
                return core.interpret_answer('set_value', {'status': 'refused', 'refusal': {'code': 'popup_option_not_found'}})
            if self.set_mode == 'fail':
                raise DriverCallFailed('driver_call_failed: set_value exited 1', 'set_value', 'exit')
            if self.set_mode == 'ok':
                self.shown = args['value']
            elif self.set_mode == 'wrong':
                self.shown = 'Other'
            elif self.set_mode == 'ci':  # the Driver matches an option's title case-insensitively
                self.shown = next(o for o in OPTIONS if o.casefold() == args['value'].casefold())
            elif self.set_mode == 'lag':
                self.pending = (args['value'], 2)
            return {'status': 'ok', 'effect': 'confirmed'}
        if tool == 'click':
            self.clicks.append(copy.deepcopy(args))
            token = args['element_token']
            if token.endswith(':%d' % POPUP):  # live 2026-10-01: pressing the select opens it and lists its options under it, a read later
                self.pending = ('list', 2)
                return {'effect': 'unverifiable'}
            for n, label in enumerate(o for o in OPTIONS if o != self.shown):
                if self.listed and token.endswith(':%d' % (40 + n)):
                    self.shown, self.listed = label, False
                    return {'effect': 'unverifiable'}
            if args['element_token'].endswith(':%d' % BOX):
                if self.press_mode == 'ok':
                    self.checked = not self.checked
                elif self.press_mode == 'lag':
                    self.pending = ('box', 2)
            return {'effect': 'unverifiable'}
        return super().call(tool, args, timeout)
    def observe(self, *args):
        if self.pending and self.pending[1] <= 1:
            what, _ = self.pending;self.pending = None
            if what == 'box':self.checked = not self.checked
            elif what == 'list':self.listed = True
            else:self.shown = what
        elif self.pending:self.pending = (self.pending[0], self.pending[1] - 1)
        return super().observe(*args)
    def page(self, d, els):
        by = {e['element_index']: e for e in els}
        by[POPUP]['value'] = self.shown
        by[ITEM]['label'] = self.shown
        by[BOX]['value'] = '1' if self.checked else '0'
        if self.disabled_select:by[POPUP]['enabled'] = False
        if self.disabled_box:by[BOX]['enabled'] = False
        if self.listed:
            for n, label in enumerate(o for o in OPTIONS if o != self.shown):
                els.append({'element_index': 40 + n, 'parent_index': 28, 'role': 'AXMenuItem', 'label': label, 'actions': ['AXPress'], 'enabled': True, 'selected': False})
        if self.twin_select:
            els.append({**copy.deepcopy(by[POPUP]), 'element_index': 60, 'value': 'Choose one'})
        if self.twin_box:
            els.append({**copy.deepcopy(by[BOX]), 'element_index': 61})
        return els


class Base(lv.LiveBase):
    def setUp(self):
        self.driver = FormDriver();self.chooser = FakeChooser();self.visual = lv.UnknownVision();self.reader = lv.LiveReader({});self.naps = []
        self.f = Facade(self.driver, generic_factory=lambda: self.chooser, reader_factory=lambda: self.reader, visual_factory=lambda: self.visual, sleep=self.naps.append)
    def plan(self, steps, **kw):
        return self.f.do('Fill in the intake form', title='Demo', expect=None, steps=steps, **kw)
    def pick(self, option='Billing', **kw):
        return {'do': 'type', 'control': SELECT, 'text': option, 'expect': option, **kw}
    def tick(self, expect='checked', **kw):
        return {'do': 'press', 'control': COPY, 'expect': expect, **kw}
    def shown(self):
        return self.f.look('Demo')


class FieldValue(Base):
    def state(self):
        return self.f.state(self.f.observe(1,2)['snapshot'])

    def test_real_field_exact_value_only_and_uniqueness(self):
        before=self.state()
        target=next(n for n in before['nodes'].values() if n.get('role')=='AXTextField' and n.get('label')==NAME)
        text='Invoice 4471 was charged twice in September.'
        def page(d,els):
            self.driver.page(d,els)
            next(e for e in els if e.get('role')=='AXTextField' and e.get('label')==NAME)['value']=text
        self.driver.script=page
        after=self.state()
        check=self.f._expect_check(after,before,'value',target,text)
        self.assertEqual((check['status'],check['scope']),('satisfied','field_only'))
        self.assertEqual(self.f._expect_check(after,before,text,target,text)['reason'],'expect_echoes_typed_text')
        for bad in (text.lower(),text+' ',text[:30]):
            self.assertEqual(self.f._expect_check(after,before,'value',target,bad)['status'],'unknown')
        def duplicate(d,els):
            page(d,els)
            twin=copy.deepcopy(next(e for e in els if e.get('role')=='AXTextField' and e.get('label')==NAME))
            twin['element_index']=999
            els.append(twin)
        self.driver.script=duplicate
        self.assertEqual(self.f._expect_check(self.state(),before,'value',target,text)['reason'],'field_value_target_unresolved')

    def test_changed_document_with_same_label_and_value_cannot_prove_original_field(self):
        before=self.state()
        target=next(n for n in before['nodes'].values() if n.get('role')=='AXTextField' and n.get('label')==NAME)
        target['identifier']='original-field'
        for change in ('url','web_area','identifier','window'):
            after=copy.deepcopy(before)
            field=next(n for n in after['nodes'].values() if n.get('role')=='AXTextField' and n.get('label')==NAME)
            field['value']='new text'
            field['identifier']='original-field'
            if change=='url':
                address=next(n for n in after['nodes'].values() if n.get('value')=='127.0.0.1:8934/form?run=fixture')
                address['value']='example.com/different-form'
            elif change=='web_area':next(n for n in after['nodes'].values() if n.get('role')=='AXWebArea')['label']='Different form'
            elif change=='identifier':field['identifier']='replacement-field'
            else:after['window_id']=999
            with self.subTest(change=change):self.assertEqual(self.f._expect_check(after,before,'value',target,'new text')['status'],'unknown')

    def test_acknowledgment_missing_value_wrong_field_and_clipping_cannot_prove_value(self):
        before=self.state()
        target=next(n for n in before['nodes'].values() if n.get('role')=='AXTextField' and n.get('label')==NAME)
        self.assertEqual(self.f._expect_check(before,before,'value',target,'new text')['status'],'unknown')
        for change in ('missing','clipped','disabled','other_label'):
            after=copy.deepcopy(before)
            field=next(n for n in after['nodes'].values() if n.get('role')=='AXTextField' and n.get('label')==NAME)
            field['value']='new text'
            if change=='missing':field.pop('value')
            elif change=='clipped':field['value_truncated']=True
            elif change=='disabled':field['enabled']=False
            else:field['label']='Other field'
            with self.subTest(change=change):self.assertEqual(self.f._expect_check(after,before,'value',target,'new text')['status'],'unknown')

    def test_plan_does_not_trust_delivery_ack_or_replay_a_drop(self):
        result=self.plan([{'do':'type','control':NAME,'text':'new text','expect':'value'}])
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(result['steps'][0]['verification']['reason'],'field_value_not_observed')
        self.assertEqual(len(self.driver.executed),1)


class Select(Base):
    def test_the_option_is_chosen_by_its_exact_label_without_opening_the_popup_and_proved_by_the_displayed_value(self):
        # Wrong patch: press the select (opens the native popup: its options exist twice in the tree, exact_target_not_unique) and press the option.
        r = self.plan([self.pick()])
        self.assertEqual((r.get('status'), r.get('delivery')), ('done', 'delivered'), r)
        self.assertEqual(len(self.driver.sets), 1)
        sent = self.driver.sets[0]
        self.assertEqual((sent['value'], sent['pid'], sent['window_id']), ('Billing', 1, 2))
        self.assertTrue(sent['element_token'].endswith(':%d' % POPUP), 'the popup button itself, not an option')
        self.assertEqual(self.driver.clicks, [], 'the native popup is never opened')
        entry = r['steps'][0]
        self.assertEqual((entry['verification'], entry['shown']), ({'status': 'satisfied', 'route': 'ax_select_value'}, 'Billing'))
        self.assertEqual(self.driver.shown, 'Billing')

    def test_set_value_is_a_mutating_tool_so_a_failed_call_never_reads_as_not_delivered(self):
        self.assertIn('set_value', MUTATING_TOOLS)

    def test_the_proof_is_a_fresh_read_not_the_drivers_answer(self):
        # Wrong patch: call the step done because the Driver answered ok. It answered ok and the select still shows the old value.
        self.driver.set_mode = 'ignored'
        r = self.plan([self.pick()])
        self.assertEqual((r.get('status'), r.get('reason'), r.get('failed_step')), ('stopped', 'select_value_unchanged', 1), r)
        self.assertEqual(r['steps'][0].get('shown'), 'Choose one')
        self.assertEqual(r.get('delivery'), 'delivered')
        self.assertEqual(self.naps, list(core.OBSERVE_RETRY_DELAYS), 'bounded re-reads, then the verdict')
        self.assertEqual(len(self.driver.sets), 1, 'never repeated')

    def test_a_different_displayed_value_is_never_done(self):
        # Wrong patch: accept any changed value, or a case-insensitive match (the Driver itself matches case-insensitively).
        self.driver.set_mode = 'wrong'
        r = self.plan([self.pick()])
        self.assertEqual((r.get('status'), r.get('reason')), ('stopped', 'select_value_differs'), r)
        self.assertEqual(r['steps'][0].get('shown'), 'Other')
        self.driver.shown, self.driver.set_mode = 'Choose one', 'ci'
        r = self.plan([self.pick('billing')])
        self.assertEqual((r.get('reason'), r['steps'][0].get('shown')), ('select_value_differs', 'Billing'))

    def test_a_value_that_shows_up_on_the_second_read_is_done_after_one_bounded_wait(self):
        self.driver.set_mode = 'lag'
        r = self.plan([self.pick()])
        self.assertEqual(r.get('status'), 'done', r)
        self.assertEqual(self.naps, [core.OBSERVE_RETRY_DELAYS[0]])

    def test_an_option_already_shown_is_not_set_again(self):
        self.driver.shown = 'Billing'
        r = self.plan([self.pick()])
        self.assertEqual((r.get('status'), r.get('delivery'), r['steps'][0].get('route')), ('done', 'none', 'already_selected'), r)
        self.assertEqual(self.driver.sets, [])

    def test_an_option_the_open_list_does_not_offer_is_refused_before_anything_is_sent(self):
        # Wrong patch: send the text and let the Driver guess the nearest option.
        self.driver.listed = True
        r = self.plan([self.pick('Billin')])
        self.assertEqual((r.get('status'), r.get('reason')), ('refused', 'select_option_not_offered'), r)
        self.assertEqual(self.driver.sets, [])
        self.assertIn('Sales', r['steps'][0]['message'])
        self.assertEqual(r['steps'][0]['options'], ['Choose one', 'Sales', 'Support', 'Billing', 'Other'])
        self.assertEqual(r.get('delivery'), 'none')

    def test_a_listed_option_is_chosen(self):
        self.driver.listed = True
        r = self.plan([self.pick('Support')])
        self.assertEqual((r.get('status'), self.driver.shown), ('done', 'Support'), r)

    def test_a_driver_refusal_is_typed_and_nothing_else_is_tried(self):
        self.driver.set_mode = 'refuse'
        r = self.plan([self.pick()])
        self.assertEqual((r.get('status'), r.get('reason'), r.get('delivery')), ('refused', 'select_refused', 'none'), r)
        self.assertIn('popup_option_not_found', r['steps'][0]['message'])
        self.assertEqual((len(self.driver.sets), self.driver.clicks), (1, []), 'no fallback click on a popup')

    def test_a_failed_set_on_an_unchanged_select_opens_it_and_presses_the_option_under_it(self):
        # Live 2026-10-01: set_value exits 1 on a closed Chrome select. Wrong patches: retry the set; press an option outside the select.
        self.driver.set_mode = 'fail'
        r = self.plan([self.pick()])
        self.assertEqual((r.get('status'), r.get('delivery')), ('done', 'delivered'), r)
        self.assertEqual(len(self.driver.sets), 1, 'the set is never retried')
        self.assertEqual([c['element_token'].split(':')[1] for c in self.driver.clicks][0], str(POPUP))
        self.assertEqual(self.driver.shown, 'Billing')

    def test_a_failed_set_that_landed_is_not_pressed_again(self):
        self.driver.set_mode = 'fail'
        real = self.driver.call
        def landed(tool, args, timeout=20):
            if tool == 'set_value':
                self.driver.sets.append(args); self.driver.shown = args['value']
                raise DriverCallFailed('driver_call_failed: set_value exited 1', 'set_value', 'exit')
            return real(tool, args, timeout)
        self.driver.call = landed
        r = self.plan([self.pick()])
        self.assertEqual(r.get('status'), 'done', r)
        self.assertEqual(self.driver.clicks, [], 'nothing pressed after a set that landed')

    def test_a_failed_set_that_changed_something_else_is_uncertain_and_not_retried(self):
        self.driver.set_mode = 'fail'
        real = self.driver.call
        def odd(tool, args, timeout=20):
            if tool == 'set_value':
                self.driver.sets.append(args); self.driver.shown = 'Other'
                raise DriverCallFailed('driver_call_failed: set_value exited 1', 'set_value', 'exit')
            return real(tool, args, timeout)
        self.driver.call = odd
        r = self.plan([self.pick()])
        self.assertEqual((r.get('status'), r.get('reason'), r.get('delivery')), ('failed', 'select_not_applied', 'uncertain'), r)
        self.assertEqual((len(self.driver.sets), self.driver.clicks), (1, []))

    def test_two_selects_with_the_label_are_refused_not_guessed(self):
        self.driver.twin_select = True
        r = self.plan([self.pick()])
        self.assertEqual((r.get('status'), r.get('reason')), ('refused', 'select_ambiguous'), r)
        self.assertEqual(self.driver.sets, [])

    def test_a_disabled_select_is_refused(self):
        self.driver.disabled_select = True
        r = self.plan([self.pick()])
        self.assertEqual((r.get('status'), r.get('reason')), ('refused', 'select_disabled'), r)
        self.assertEqual(self.driver.sets, [])

    def test_an_empty_option_text_is_refused(self):
        r = self.plan([self.pick('  ', expect=None)])
        self.assertEqual((r.get('status'), r.get('reason')), ('refused', 'select_option_not_offered'), r)
        self.assertEqual(self.driver.sets, [])

    def test_a_text_field_is_still_typed_into_by_the_ordinary_path(self):
        # Wrong patch: route every type step to the select path. 'Full name' is no select: the old type path runs, set_value is never called.
        r = self.plan([{'do': 'type', 'control': NAME, 'text': 'Dana Whitfield', 'expect': None}])
        self.assertEqual(self.driver.sets, [])
        self.assertEqual([c['text'] for c in self.driver.executed], ['Dana Whitfield'])
        self.assertNotIn(r.get('status'), ('refused',))

    def test_input_values_are_not_silently_cut_at_thirty_characters(self):
        # Wrong patch: display a partial field value without saying it was clipped;
        # a caller may mistake successful entry for missing text and type again.
        import look as lk
        def value(text):
            def page(d, els):
                self.driver.page(d, els)
                next(e for e in els if e.get('label') == NAME and e.get('role') == 'AXTextField')['value'] = text
            self.driver.script = page
            return next(i for i in self.shown()['inputs'] if i['label'] == NAME)
        text = 'A field value longer than thirty characters.'
        self.assertEqual(value(text), {'label': NAME, 'value': text})
        clipped = value('x' * (lk.LINE_MAX_CHARS + 10))
        self.assertTrue(clipped['value_truncated'])
        self.assertTrue(clipped['value'].endswith('…'))
        self.assertGreaterEqual(self.shown()['truncated']['lines'], 1)
        self.assertEqual(self.driver.executed, [])

    def test_typed_echo_refusal_keeps_its_cause_in_the_plan(self):
        # Wrong patch: collapse every failed postcondition to generic unverified,
        # causing the caller to repeat an impossible presence-based check.
        r = self.plan([{'do': 'type', 'control': NAME, 'text': 'Dana Whitfield', 'expect': 'Dana Whitfield'}])
        self.assertEqual(r['status'], 'stopped')
        self.assertEqual(r['steps'][0]['verification']['reason'], 'expect_echoes_typed_text')
        self.assertEqual(len(self.driver.executed), 1)

    def test_the_form_steps_run_in_one_plan_and_stop_at_the_first_that_is_not_done(self):
        r = self.plan([self.pick(), self.tick()])
        self.assertEqual((r.get('status'), [s['status'] for s in r['steps']]), ('done', ['done', 'done']), r)
        self.driver.shown, self.driver.checked, self.driver.set_mode = 'Choose one', False, 'ignored'
        r = self.plan([self.pick(), self.tick()])
        self.assertEqual((r.get('status'), r.get('failed_step'), len(r['steps'])), ('stopped', 1, 1), r)

    def test_the_look_after_shows_what_the_select_displays(self):
        # The fixture is the page of the live transcript: the select is a control, its selected option a toggle, the box unchecked.
        look = self.shown()
        self.assertIn(SELECT, look['controls'])
        self.assertIn({'label': 'Choose one', 'state': 'selected'}, look['toggles'])
        self.assertIn({'label': COPY, 'state': 'unchecked'}, look['toggles'])
        self.assertEqual(look['selects'], [{'label': SELECT, 'value': 'Choose one', 'options': ['Choose one']}])
        self.assertTrue(any('type step' in note for note in look['notes']))
        self.assertEqual(self.driver.sets, [])
        self.assertEqual(self.driver.clicks, [])


class Checkbox(Base):
    def test_a_press_is_done_only_when_the_checked_state_flipped_to_the_wanted_state(self):
        r = self.plan([self.tick()])
        self.assertEqual((r.get('status'), r.get('delivery')), ('done', 'delivered'), r)
        self.assertEqual(len(self.driver.clicks), 1)
        self.assertTrue(self.driver.clicks[0]['element_token'].endswith(':%d' % BOX))
        entry = r['steps'][0]
        self.assertEqual((entry['state'], entry['verification']), ('checked', {'status': 'satisfied', 'route': 'ax_toggle_state'}))
        self.assertTrue(self.driver.checked)

    def test_the_label_still_on_the_page_is_not_proof_the_state_is(self):
        # Wrong patch: verify by label presence (the box's label is on the page before and after, whatever the press did).
        self.driver.press_mode = 'ignored'
        r = self.plan([self.tick()])
        self.assertEqual((r.get('status'), r.get('reason'), r.get('delivery')), ('stopped', 'checkbox_not_flipped', 'delivered'), r)
        self.assertEqual(r['steps'][0].get('state'), 'unchecked')
        self.assertEqual(len(self.driver.clicks), 1, 'never pressed again')
        self.assertEqual(self.naps, list(core.OBSERVE_RETRY_DELAYS))

    def test_a_box_already_in_the_wanted_state_is_not_pressed_because_a_press_would_undo_it(self):
        # Wrong patch: press whenever asked. The box is already ticked; one more press unticks it.
        self.driver.checked = True
        r = self.plan([self.tick()])
        self.assertEqual((r.get('status'), r.get('delivery'), r['steps'][0].get('route')), ('done', 'none', 'already_in_state'), r)
        self.assertEqual(self.driver.clicks, [])
        self.assertTrue(self.driver.checked)

    def test_unchecking_is_asked_for_by_name(self):
        self.driver.checked = True
        r = self.plan([self.tick('unchecked')])
        self.assertEqual((r.get('status'), r['steps'][0].get('state'), self.driver.checked), ('done', 'unchecked', False), r)

    def test_a_state_that_shows_on_the_second_read_is_done_after_one_bounded_wait(self):
        self.driver.press_mode = 'lag'
        r = self.plan([self.tick()])
        self.assertEqual(r.get('status'), 'done', r)
        self.assertEqual(self.naps, [core.OBSERVE_RETRY_DELAYS[0]])

    def test_a_blind_flip_needs_a_look_that_saw_the_state(self):
        # No expect: the press flips whatever it finds, so it is only allowed against a look that saw that state, unchanged since.
        r = self.plan([{'do': 'press', 'control': COPY}])
        self.assertEqual((r.get('status'), r.get('reason'), self.driver.clicks), ('refused', 'toggle_state_unseen', []), r)
        look = self.shown()
        r = self.plan([{'do': 'press', 'control': COPY}], look_id=look['look_id'])
        self.assertEqual((r.get('status'), r['steps'][0].get('state'), self.driver.checked), ('done', 'checked', True), r)

    def test_a_blind_flip_after_the_box_changed_since_the_look_is_refused(self):
        look = self.shown();self.driver.checked = True
        r = self.plan([{'do': 'press', 'control': COPY}], look_id=look['look_id'])
        self.assertEqual((r.get('status'), r.get('reason'), self.driver.clicks), ('refused', 'toggle_state_unseen', []), r)

    def test_two_boxes_with_the_label_are_refused_not_guessed(self):
        self.driver.twin_box = True
        r = self.plan([self.tick()])
        self.assertEqual((r.get('status'), r.get('reason'), self.driver.clicks), ('refused', 'checkbox_ambiguous', []), r)

    def test_a_disabled_box_is_refused(self):
        self.driver.disabled_box = True
        r = self.plan([self.tick()])
        self.assertEqual((r.get('status'), r.get('reason'), self.driver.clicks), ('refused', 'checkbox_disabled', []), r)

    def test_a_press_on_a_plain_button_is_not_a_form_step(self):
        # Wrong patch: route every press to the checkbox path. 'Submit application' is no checkbox: the ordinary press runs.
        r = self.plan([{'do': 'press', 'control': 'Submit application', 'expect': None}])
        self.assertEqual(len(self.driver.clicks), 1)
        self.assertTrue(self.driver.clicks[0]['element_token'].endswith(':23'))
        self.assertNotIn('route', r['steps'][0])

    def test_a_checkbox_press_with_page_text_as_its_expect_keeps_the_ordinary_proof(self):
        # The step is not rerouted when expect is page text: that text stays its proof (see test_plan_review2.ControlState).
        self.assertFalse(planmod.form_candidate('press', {'control': COPY, 'expect': 'Request sent', 'where_kind': None}))
        self.assertTrue(planmod.form_candidate('press', {'control': COPY, 'expect': 'Checked', 'where_kind': None}))
        self.assertTrue(planmod.form_candidate('press', {'control': COPY, 'where_kind': None}))
        self.assertFalse(planmod.form_candidate('press', {'control': COPY, 'where_kind': 'lines'}))


class Hints(unittest.TestCase):
    def test_every_form_refusal_has_a_hint_of_at_most_240_characters_even_after_nine_done_steps(self):
        reasons = [k for k in planmod.HINTS if k.startswith(('select_', 'checkbox_'))]
        self.assertGreaterEqual(len(reasons), 13)
        for reason in reasons:
            text = planmod.hint_for(reason, 10, True)
            self.assertLessEqual(len(text), 240, (reason, len(text)))
            self.assertNotRegex(text, r'set_value|AXPress|element_token')


if __name__ == '__main__':
    unittest.main()
