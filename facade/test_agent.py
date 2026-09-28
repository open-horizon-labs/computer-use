"""Option D (experimental server-side task agent). Each test names the tempting wrong patch it fails.
Fakes only: no Driver, model, desktop or network. Includes the REAL sanitized Chrome AX shapes."""
import copy
import json
import os
import unittest
from pathlib import Path

import call_budget as cb
from core import Facade, DriverCallFailed
from test_core import FakeDriver
from test_do import FlatDriver, Clock, booking_rows, order_rows, PROVIDERS

FIX = Path(__file__).resolve().parent / 'fixtures'


class ScriptPolicy:
    """Fake fast model: pick(ctx) -> control id | 'abstain' | 'done'."""
    def __init__(self, pick, confidence=0.9):
        self.pick, self.confidence, self.contexts, self.fail = pick, confidence, [], 0
    def choose(self, ctx):
        self.contexts.append(copy.deepcopy(ctx))
        if self.fail:
            self.fail -= 1
            raise TimeoutError('model endpoint down')
        return {'choice': self.pick(ctx), 'confidence': self.confidence, 'model': 'fake-fast'}


def by_record(text, label=None):
    def pick(ctx):
        hits = [c['id'] for c in ctx['candidates'] if text in c['record'] and (label is None or c['label'] == label)]
        return hits[0] if hits else 'abstain'
    return pick


CHROME_NAMES = {'Back', 'Reload', 'Home', 'View site information', 'Bookmark this tab', 'Extensions', 'Chrome'}


def chrome_nodes(base):
    """Synthetic browser chrome around the page, like the real tree: 30 menus holding 260 menu items, 11 menu bar items, 8 pop-up
    buttons and a toolbar (all outside the web area, all press-capable and enabled)."""
    out, i = [], base
    # the real toolbar buttons sit at LOW indices (e1..e13), before the page; menus come after it
    for k, name in enumerate(sorted(CHROME_NAMES) + ['View site information', 'Bookmark this tab', 'Extensions', 'Chrome'], start=1):
        out.append({'element_index': k, 'parent_index': 0, 'role': 'AXButton', 'enabled': True, 'actions': ['AXPress'], 'label': name})
    def add(role, parent, label=None):
        nonlocal i
        out.append({'element_index': i, 'parent_index': parent, 'role': role, 'enabled': True, 'actions': ['AXPress'], **({'label': label} if label else {})});i += 1;return i - 1
    bar = add('AXMenuBar', 0)
    for k in range(11):add('AXMenuBarItem', bar, 'Bar item %d' % k)
    n = 0
    for m in range(30):
        menu = add('AXMenu', 0, 'Menu %d' % m)
        for _ in range(9 if m < 20 else 8):add('AXMenuItem', menu, 'Menu item %d' % n);n += 1
    for k in range(8):add('AXPopUpButton', 0, 'Popup %d' % k)
    return out


def dup_page():
    """ax_dup shape: two identical Save buttons, one in a header, one inside a form group with fields (Chrome-flat, AXPress everywhere)."""
    rows = [(0, None, 'AXWindow', None, None), (15, 0, 'AXWebArea', 'Account', None), (16, 15, 'AXGroup', None, None),
            (17, 16, 'AXStaticText', 'Account settings', 'Account settings'), (18, 16, 'AXButton', 'Save', None),
            (19, 15, 'AXGroup', 'Shipping address', None), (20, 19, 'AXStaticText', 'Shipping address', 'Shipping address'),
            (21, 19, 'AXTextField', 'Street', '1 Main St'), (22, 19, 'AXTextField', 'City', 'Springfield'), (23, 19, 'AXButton', 'Save', None),
            (24, 0, 'AXTextField', None, '127.0.0.1:8934/account?run=fixture')]
    return [{'element_index': i, **({'parent_index': p} if p is not None else {}), 'role': r, 'enabled': True,
             **({'label': l} if l else {}), **({'value': v} if v else {}),
             **({'actions': ['AXPress']} if r in ('AXButton', 'AXStaticText', 'AXGroup') else {})} for i, p, r, l, v in rows]


class FixtureDriver(FakeDriver):
    """Serves a REAL sanitized Chrome AX capture (format {elements:[{element_index,parent_index,role,...}]})."""
    def __init__(self, name, elements=None, chrome=False, extra_web=0):
        super().__init__()
        self.fixture = json.loads((FIX / name).read_text()) if name else {'window_title': 'Demo page', 'elements': elements}
        if elements is not None:self.fixture['elements'] = elements
        self.chrome, self.extra_web = chrome, extra_web
        self.on_tool = None;self.dialog = None;self.done_text = None;self.navigate = False;self.last = max(e['element_index'] for e in self.fixture['elements'])
    def call(self, tool, args, timeout=20):
        if self.on_tool:self.on_tool(tool)
        return super().call(tool, args, timeout)
    def observe(self, *args):
        self.version += 1
        sid = 's' + format(self.version, '08x')
        nodes = []
        for e in copy.deepcopy(self.fixture['elements']):
            if e.get('parent_index') is None:e.pop('parent_index', None)
            nodes.append(e)
        if self.chrome:nodes += chrome_nodes(max(e['element_index'] for e in nodes) + 100)
        if self.extra_web:
            top = max(e['element_index'] for e in nodes) + 1
            nodes.append({'element_index': top, 'parent_index': 0 if self.extra_web == 1 else next(n['element_index'] for n in nodes if n['role'] == 'AXWebArea'),
                          'role': 'AXWebArea', 'enabled': True, 'label': 'extra'})
        clicks = len(self.executed)
        web = next(n['element_index'] for n in nodes if n['role'] == 'AXWebArea')
        nxt = [self.last + 1]
        def add(role, parent, **kw):
            nodes.append({'element_index': nxt[0], 'parent_index': parent, 'role': role, 'enabled': True, **kw});nxt[0] += 1;return nxt[0] - 1
        if self.dialog and clicks == 1:
            sheet = add('AXSheet', web, label='Confirm')
            for role, kw in self.dialog:add(role, sheet, **kw)
        elif self.done_text and clicks >= (2 if self.dialog else 1):
            add('AXStaticText', web, label=self.done_text, value=self.done_text)
        if self.navigate and clicks >= 1:
            for n in nodes:
                if n['role'] == 'AXTextField':n['value'] = '127.0.0.1:8934/elsewhere'
        for n in nodes:n.update(element_token=sid + ':' + str(n['element_index']), enabled=True)
        return {'snapshot_id': sid, 'pid': 1, 'window_id': 2, 'window_title': self.fixture['window_title'], 'elements': nodes, '_image': b'pixels'}


class Base(unittest.TestCase):
    def make(self, driver):
        self.driver = driver;self.clock = Clock();self.naps = []
        def no_model():raise AssertionError('the agent must use its injected policy, never start a provider here')
        self.f = Facade(driver, generic_factory=no_model, sleep=self.naps.append, clock=self.clock)
        return self.f
    def run_agent(self, policy, goal, expect, **kw):
        kw.setdefault('title', 'Demo')
        return self.f.agent_run(goal, expect=expect, policy=policy, **kw)
    def flat(self, rows=None, **attrs):
        d = FlatDriver()
        if rows is not None:d.rows = rows
        for k, v in attrs.items():setattr(d, k, v)
        return self.make(d)


class RealShapes(Base):
    def test_booking_real_flat_axlist_picks_the_right_book_traced_done_one_click(self):
        # Wrong patches: treat the flat AXList's 12 identical Book controls as one (or click the first); drop the trace.
        d = FixtureDriver('live_booking_ax.json');d.done_text = 'Booked Morgan Lee, NP'
        self.make(d)
        policy = ScriptPolicy(by_record('Starts 2:00 PM'))
        r = self.run_agent(policy, 'Book the Follow-up slot that starts at 2:00 PM', 'Booked Morgan Lee')
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(len(d.executed), 1);self.assertEqual(len(r['steps']), 1)
        step = r['steps'][0]
        self.assertEqual((step['n'], step['action']['label'], step['model'], step['confidence'], step['scope_changed']), (1, 'Book', 'fake-fast', 0.9, True))
        offered = policy.contexts[0]['candidates'];self.assertEqual(len(offered), 12)
        chosen = next(c for c in offered if c['id'] == step['action']['id']);self.assertIn('Starts 2:00 PM', chosen['record'])
        self.assertEqual(r['cost']['model_calls'], 1);self.assertEqual(r['cost']['llm_visible_calls'], 'n/a')
        self.assertLess(len(json.dumps(r)), 3000)

    def test_orders_multistep_cancel_dialog_confirm_done(self):
        # Wrong patch: treat the row's Cancel as the whole task (or press the dialog's first control).
        d = FixtureDriver('live_orders_ax.json');d.done_text = 'Order #1042 cancelled'
        d.dialog = [('AXStaticText', {'value': 'Cancel order #1042?', 'label': 'Cancel order #1042?'}),
                    ('AXButton', {'label': 'Keep order', 'actions': ['AXPress']}), ('AXButton', {'label': 'Yes, cancel it', 'actions': ['AXPress']})]
        self.make(d)
        r = self.run_agent(ScriptPolicy(by_record('#1042', 'Cancel')), 'Cancel order #1042', 'cancelled', confirm='Yes, cancel it')
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual([s['action']['label'] for s in r['steps']], ['Cancel', 'Yes, cancel it'])
        self.assertEqual([s['model'] for s in r['steps']], ['fake-fast', 'confirm_exact'])
        self.assertEqual(len(d.executed), 2)

    def test_orders_without_confirm_escalates_and_never_clicks_again(self):
        # Wrong patch: press the dialog's only affirmative control by default.
        d = FixtureDriver('live_orders_ax.json');d.done_text = 'Order #1042 cancelled'
        d.dialog = [('AXStaticText', {'value': 'Cancel order #1042?'}), ('AXButton', {'label': 'Yes, cancel it', 'actions': ['AXPress']})]
        self.make(d)
        r = self.run_agent(ScriptPolicy(by_record('#1042', 'Cancel')), 'Cancel order #1042', 'cancelled')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'dialog_needs_confirm'))
        self.assertEqual(len(d.executed), 1);self.assertIn('Yes, cancel it', r['evidence']['dialog_controls'])
        self.assertIn('snapshot', r['escalation']['observation'])

    def test_navigation_mid_run_escalates(self):
        # Wrong patch: ignore the address field and keep clicking on the new page.
        d = FixtureDriver('live_booking_ax.json');d.navigate = True
        self.make(d)
        r = self.run_agent(ScriptPolicy(by_record('Starts 2:00 PM')), 'Book the slot that starts at 2:00 PM', 'Booked')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'navigation'));self.assertEqual(len(d.executed), 1)


class ChromeHeavy(Base):
    """The real tree is ~390 nodes, mostly browser chrome. Candidates come from the page only, through the same helpers cua_do uses."""
    def labels(self, policy):return [c['label'] for c in policy.contexts[0]['candidates']]

    def test_booking_in_a_chrome_heavy_tree_offers_only_the_page_books_and_picks_one(self):
        # Wrong patch: define candidates as every press-capable control in the window (the live 'Back'-only failure).
        d = FixtureDriver('live_booking_ax.json', chrome=True);d.done_text = 'Booked Morgan Lee, NP';self.make(d)
        policy = ScriptPolicy(by_record('Starts 2:00 PM'))
        r = self.run_agent(policy, 'Book the Follow-up slot that starts at 2:00 PM', 'Booked Morgan Lee')
        self.assertEqual(r['status'], 'done', r);self.assertEqual(self.labels(policy), ['Book'] * 12)
        self.assertEqual(len(d.executed), 1);self.assertFalse(set(self.labels(policy)) & CHROME_NAMES)

    def test_ax_dup_picks_the_forms_save_when_the_goal_says_the_shipping_form(self):
        # Wrong patch: offer only chrome, or pick the first Save.
        d = FixtureDriver(None, elements=dup_page(), chrome=True);d.done_text = 'Address saved';self.make(d)
        policy = ScriptPolicy(by_record('Shipping address', 'Save'))
        r = self.run_agent(policy, 'Save the shipping address form', 'Address saved')
        self.assertEqual(r['status'], 'done', r);self.assertEqual(self.labels(policy), ['Save', 'Save'])
        self.assertEqual(len(d.executed), 1);self.assertEqual(r['steps'][0]['action']['id'], 'e23')
        offered = policy.contexts[0]['candidates'];self.assertIn('Shipping address', offered[1]['record']);self.assertNotIn('Shipping address', offered[0]['record'])
        self.assertEqual(policy.contexts[0]['goal'], 'Save the shipping address form')

    def test_orders_multistep_with_confirm_in_a_chrome_heavy_tree(self):
        # Wrong patch: the chrome menu items or the toolbar leak into the dialog or candidate scope.
        d = FixtureDriver('live_orders_ax.json', chrome=True);d.done_text = 'Order #1042 cancelled'
        d.dialog = [('AXStaticText', {'value': 'Cancel order #1042?'}), ('AXButton', {'label': 'Yes, cancel it', 'actions': ['AXPress']})]
        self.make(d)
        policy = ScriptPolicy(by_record('#1042', 'Cancel'))
        r = self.run_agent(policy, 'Cancel order #1042', 'cancelled', confirm='Yes, cancel it')
        self.assertEqual(r['status'], 'done', r);self.assertEqual(len(d.executed), 2)
        self.assertFalse(set(self.labels(policy)) & CHROME_NAMES);self.assertTrue(all(l.startswith('Menu') is False for l in self.labels(policy)))

    def test_more_than_18_page_controls_escalates_with_the_page_count_not_the_window_count(self):
        # Wrong patch: count or truncate the window's controls, or offer >18 to the model.
        rows = [(15, 0, 'AXWebArea')] + [(16 + k, 15, 'AXButton') for k in range(20)]
        els = [{'element_index': 0, 'role': 'AXWindow', 'enabled': True}] + [{'element_index': i, 'parent_index': p, 'role': r, 'enabled': True, 'label': 'Book' if r == 'AXButton' else 'Page', 'actions': ['AXPress']} for i, p, r in rows]
        self.make(FixtureDriver(None, elements=els, chrome=True));policy = ScriptPolicy(lambda ctx: ctx['candidates'][0]['id'])
        r = self.run_agent(policy, 'Book a slot', 'Booked')
        self.assertEqual((r['status'], r['reason'], r['evidence']['candidate_count']), ('escalated', 'too_many_candidates', 20));self.assertEqual(policy.contexts, [])

    def test_chrome_only_window_says_no_page_candidates_with_counts(self):
        # Wrong patch: offer the toolbar's 'Back' to the model and report 'no safe choice among 1 candidates'.
        els = [{'element_index': 0, 'role': 'AXWindow', 'enabled': True}, {'element_index': 15, 'parent_index': 0, 'role': 'AXWebArea', 'enabled': True, 'label': 'Empty'}]
        d = FixtureDriver(None, elements=els, chrome=True);self.make(d);policy = ScriptPolicy(lambda ctx: self.fail('no model call without page candidates'))
        r = self.run_agent(policy, 'Save the form', 'Saved')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'no_page_candidates'))
        self.assertEqual((r['evidence']['page_controls'], r['evidence']['non_page_controls']), (0, r['evidence']['non_page_controls']))
        self.assertGreater(r['evidence']['non_page_controls'], 250);self.assertEqual(d.executed, [])

    def test_several_top_level_web_areas_escalate_but_an_iframe_belongs_to_its_page(self):
        # Wrong patch: silently pick the first web area; or treat an iframe's web area as a second page.
        d = FixtureDriver(None, elements=dup_page(), chrome=True, extra_web=1);self.make(d);policy = ScriptPolicy(by_record('Shipping', 'Save'))
        r = self.run_agent(policy, 'Save the shipping address form', 'Address saved')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'web_area_ambiguous'));self.assertEqual((d.executed, policy.contexts), ([], []))
        d = FixtureDriver(None, elements=dup_page(), chrome=True, extra_web=2);d.done_text = 'Address saved';self.make(d)
        self.assertEqual(self.run_agent(ScriptPolicy(by_record('Shipping', 'Save')), 'Save the shipping address form', 'Address saved')['status'], 'done')

    def test_a_singleton_needs_the_policy_unless_the_goal_quotes_its_exact_label(self):
        # Wrong patch: treat one candidate as an abstention, or as authorized without the model.
        els = [{'element_index': 0, 'role': 'AXWindow', 'enabled': True}, {'element_index': 15, 'parent_index': 0, 'role': 'AXWebArea', 'enabled': True},
               {'element_index': 16, 'parent_index': 15, 'role': 'AXStaticText', 'enabled': True, 'label': 'Ship it', 'value': 'Ship it'},
               {'element_index': 17, 'parent_index': 15, 'role': 'AXButton', 'enabled': True, 'label': 'Submit order', 'actions': ['AXPress']}]
        d = FixtureDriver(None, elements=els, chrome=True);d.done_text = 'Order placed';self.make(d)
        policy = ScriptPolicy(lambda ctx: ctx['candidates'][0]['id'])
        self.assertEqual(self.run_agent(policy, 'Submit the order', 'Order placed')['status'], 'done')
        self.assertEqual((len(policy.contexts), len(policy.contexts[0]['candidates'])), (1, 1))  # policy decided the singleton
        d = FixtureDriver(None, elements=els, chrome=True);d.done_text = 'Order placed';self.make(d)
        never = ScriptPolicy(lambda ctx: self.fail('exact quoted label needs no model'))
        r = self.run_agent(never, 'Press "Submit order"', 'Order placed')
        self.assertEqual((r['status'], r['steps'][0]['model'], r['cost']['model_calls']), ('done', 'exact', 0))
        d = FixtureDriver(None, elements=els, chrome=True);self.make(d)
        r = self.run_agent(ScriptPolicy(lambda ctx: 'abstain'), 'Submit the order', 'Order placed')
        self.assertEqual((r['reason'], d.executed), ('policy_abstained', []))

    def test_candidate_record_context_is_bounded(self):
        # Wrong patch: dump a whole page section into the model's context.
        els = dup_page();els[3]['value'] = els[3]['label'] = 'Long text ' * 100
        self.make(FixtureDriver(None, elements=els, chrome=True));policy = ScriptPolicy(lambda ctx: 'abstain')
        self.run_agent(policy, 'Save the account settings', 'Saved')
        self.assertTrue(all(len(c['record']) <= 240 and len(c['description']) <= 300 for c in policy.contexts[0]['candidates']))

    def test_a_dialog_static_text_with_the_confirm_label_is_not_a_control(self):
        # Wrong patch: any press-capable node in the dialog counts as its button.
        d = FixtureDriver('live_orders_ax.json', chrome=True);d.done_text = 'Order #1042 cancelled'
        d.dialog = [('AXStaticText', {'value': 'Cancel order #1042?'}), ('AXStaticText', {'label': 'Yes, cancel it', 'value': 'Yes, cancel it', 'actions': ['AXPress']})]
        self.make(d)
        r = self.run_agent(ScriptPolicy(by_record('#1042', 'Cancel')), 'Cancel order #1042', 'cancelled', confirm='Yes, cancel it')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'confirm_control_not_found'));self.assertEqual(len(d.executed), 1)


class Dialogs(Base):
    DIALOG = [('AXStaticText', {'value': 'Cancel Order 1042?'}), ('AXButton', {'label': 'Yes, cancel', 'actions': ['AXPress']}), ('AXButton', {'label': 'Keep', 'actions': ['AXPress']})]

    def orders(self, dialog=None, **more):
        return self.flat(order_rows(), modal=dialog or self.DIALOG, confirm_text='Order cancelled', **more)

    def test_confirm_needs_an_identity_match_with_the_clicked_record(self):
        # Wrong patch: confirm any dialog once the label matches.
        self.orders([('AXStaticText', {'value': 'Cancel Order 1043?'}), ('AXButton', {'label': 'Yes, cancel', 'actions': ['AXPress']})])
        r = self.run_agent(ScriptPolicy(by_record('Order 1042')), 'Cancel order 1042', 'Order cancelled', confirm='Yes, cancel')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'confirm_identity_mismatch'));self.assertEqual(len(self.driver.executed), 1)

    def test_confirm_label_must_be_one_enabled_dialog_control(self):
        # Wrong patch: fuzzy-match the confirm label or fall back to the first control.
        self.orders()
        r = self.run_agent(ScriptPolicy(by_record('Order 1042')), 'Cancel order 1042', 'Order cancelled', confirm='Yes')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'confirm_control_not_found'));self.assertEqual(len(self.driver.executed), 1)

    def test_destructive_dialog_control_is_never_pressed_unless_the_goal_says_so(self):
        # Wrong patch: the caller's confirm label alone authorizes a destructive press.
        dialog = [('AXStaticText', {'value': 'Order 1042 will be affected'}), ('AXButton', {'label': 'Delete account', 'actions': ['AXPress']})]
        self.orders(dialog)
        r = self.run_agent(ScriptPolicy(by_record('Order 1042')), 'Cancel order 1042', 'Order cancelled', confirm='Delete account')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'destructive_control'));self.assertEqual(len(self.driver.executed), 1)
        self.orders(dialog)
        ok = self.run_agent(ScriptPolicy(by_record('Order 1042')), 'Cancel order 1042 and delete account', 'Order cancelled', confirm='Delete account')
        self.assertEqual(ok['status'], 'done', ok);self.assertEqual(len(self.driver.executed), 2)

    def test_a_destructive_policy_pick_is_never_clicked(self):
        # Wrong patch: only guard the dialog, not ordinary steps.
        self.flat(booking_rows(label='Delete'))
        r = self.run_agent(ScriptPolicy(lambda ctx: ctx['candidates'][0]['id']), 'Manage the Consultation slot', 'Booked')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'destructive_control'));self.assertEqual(self.driver.executed, [])


class StopConditions(Base):
    def test_no_progress_twice_escalates(self):
        # Wrong patch: keep clicking a control whose click changes nothing until max_steps.
        self.flat()
        r = self.run_agent(ScriptPolicy(by_record('1:45 PM')), 'Book the 1:45 PM slot', 'Booked')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'no_progress'))
        self.assertEqual(len(self.driver.executed), 2);self.assertEqual([s['scope_changed'] for s in r['steps']], [False, False])

    def test_abstain_escalates_without_a_click(self):
        # Wrong patch: fall back to the first candidate when the policy abstains.
        self.flat();r = self.run_agent(ScriptPolicy(lambda ctx: 'abstain'), 'Book the 1:45 PM slot', 'Booked')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'policy_abstained'));self.assertEqual(self.driver.executed, [])

    def test_low_confidence_escalates_without_a_click(self):
        # Wrong patch: act on any authorized choice regardless of confidence.
        self.flat();r = self.run_agent(ScriptPolicy(by_record('1:45 PM'), confidence=0.2), 'Book the 1:45 PM slot', 'Booked')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'low_confidence'));self.assertEqual(self.driver.executed, [])

    def test_a_pick_outside_the_offered_candidates_escalates(self):
        # Wrong patch: bind whatever id the model names.
        self.flat();r = self.run_agent(ScriptPolicy(lambda ctx: 'e1'), 'Book the 1:45 PM slot', 'Booked')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'policy_invalid_choice'));self.assertEqual(self.driver.executed, [])

    def test_too_many_candidates_escalates_with_a_count_and_never_truncates(self):
        # Wrong patch: truncate or rank the first 18 and let the model choose.
        rows = [((('Provider %d' % i), 'Follow-up', '30 min', 'Starts 1:00 PM'), 'Book') for i in range(20)]
        self.flat(rows);policy = ScriptPolicy(lambda ctx: ctx['candidates'][0]['id'])
        r = self.run_agent(policy, 'Book a Follow-up slot', 'Booked')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'too_many_candidates'))
        self.assertEqual(r['evidence']['candidate_count'], 20);self.assertEqual(policy.contexts, []);self.assertEqual(self.driver.executed, [])

    def test_expect_already_on_the_page_escalates_before_any_click(self):
        # Wrong patch: click hoping the pre-existing text becomes proof.
        self.flat(layout={'header': 'Booked Provider E'});r = self.run_agent(ScriptPolicy(by_record('1:45 PM')), 'Book the 1:45 PM slot', 'Booked Provider E')
        self.assertEqual(r['reason'], 'expect_present_before_action');self.assertEqual(self.driver.executed, [])

    def test_a_quoted_exact_label_uses_no_model(self):
        # Wrong patch: always call the model, even for a unique named control.
        self.flat([(('Order 1042',), 'Cancel order')], confirm_text='Booked')
        policy = ScriptPolicy(lambda ctx: self.fail('model must not be called'))
        r = self.run_agent(policy, 'Press "Cancel order"', 'Booked')
        self.assertEqual(r['status'], 'done', r);self.assertEqual((r['steps'][0]['model'], r['cost']['model_calls']), ('exact', 0))


class Recovery(Base):
    def test_stale_ui_replans_once_never_reusing_the_refused_selection(self):
        # Wrong patch: retry act with the refused selection, or re-plan without a fresh observation.
        self.flat(shift_at=lambda v: v == 2, confirm_text='Booked Provider E')
        policy = ScriptPolicy(by_record('1:45 PM'))
        r = self.run_agent(policy, 'Book the 1:45 PM slot', 'Booked')
        self.assertEqual(r['status'], 'done', r);self.assertEqual(len(policy.contexts), 2);self.assertEqual(len(self.driver.executed), 1)
        self.assertEqual(self.driver.executed[0]['element_token'].split(':')[0], 's00000004')  # bound to the fresh observation
        self.assertEqual(len(self.f.selections), 2);self.assertTrue(all(s['used'] for s in self.f.selections.values()))  # refused one is spent, never reused

    def test_a_second_stale_refusal_escalates(self):
        # Wrong patch: loop re-planning until the page settles.
        self.flat(shift_at=lambda v: v in (2, 4))
        r = self.run_agent(ScriptPolicy(by_record('1:45 PM')), 'Book the 1:45 PM slot', 'Booked')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'ui_changed_repeatedly'));self.assertEqual(self.driver.executed, [])

    def test_click_failing_after_delivery_is_failed_not_retryable_with_no_selection(self):
        # Wrong patch: retry the click or hand the selection back after a delivery may have happened.
        self.flat(confirm_text='Booked')
        def boom(tool):
            if tool == 'click':raise DriverCallFailed('click died')
        self.driver.on_tool = boom
        r = self.run_agent(ScriptPolicy(by_record('1:45 PM')), 'Book the 1:45 PM slot', 'Booked')
        self.assertEqual((r['status'], r['reason']), ('failed', 'driver_call_failed'))
        self.assertIs(r['retryable'], False);self.assertEqual(r['delivery'], 'uncertain');self.assertNotIn('selection', json.dumps(r))
        self.assertEqual([s for s in self.f.selections.values() if not s['used']], [])

    def test_policy_transport_failure_retries_once_then_escalates_without_a_click(self):
        # Wrong patch: fall back to a guess (or retry forever) when the model endpoint is down.
        self.flat();policy = ScriptPolicy(by_record('1:45 PM'));policy.fail = 2
        r = self.run_agent(policy, 'Book the 1:45 PM slot', 'Booked')
        self.assertEqual((r['status'], r['reason']), ('escalated', 'policy_unavailable'))
        self.assertEqual((r['cost']['model_calls'], self.driver.executed), (2, []));self.assertEqual(len(self.naps), 1)
        self.flat(confirm_text='Booked');flaky = ScriptPolicy(by_record('1:45 PM'));flaky.fail = 1
        self.assertEqual(self.run_agent(flaky, 'Book the 1:45 PM slot', 'Booked')['status'], 'done')


class Budget(Base):
    def test_hard_cap_stops_before_the_click(self):
        # Wrong patch: check the budget only between steps, after the model call.
        self.flat(confirm_text='Booked')
        def slow(ctx):self.clock.advance(31);return by_record('1:45 PM')(ctx)
        r = self.run_agent(ScriptPolicy(slow), 'Book the 1:45 PM slot', 'Booked', budget_s=10)
        self.assertEqual((r['status'], r['reason']), ('escalated', 'time_budget'));self.assertEqual(self.driver.executed, [])

    def test_click_time_counts_toward_the_hard_cap_and_no_second_click_follows(self):
        # Wrong patch: exclude click time from every cap.
        self.flat()
        self.driver.on_tool = lambda tool: self.clock.advance(40) if tool == 'click' else None
        r = self.run_agent(ScriptPolicy(by_record('1:45 PM')), 'Book the 1:45 PM slot', 'Booked', budget_s=10)
        self.assertEqual((r['status'], r['reason']), ('escalated', 'time_budget'));self.assertEqual(len(self.driver.executed), 1)

    def test_max_steps_stops_further_clicks(self):
        # Wrong patch: ignore max_steps when progress keeps appearing.
        self.flat(rows_at=lambda v: booking_rows(PROVIDERS[:(v + 1) // 2 + 2]), confirm_text=None)
        r = self.run_agent(ScriptPolicy(lambda ctx: ctx['candidates'][0]['id']), 'Book a Follow-up slot', 'Booked', max_steps=2)
        self.assertEqual((r['status'], r['reason']), ('escalated', 'step_budget'));self.assertEqual(len(self.driver.executed), 2)


class Safety(Base):
    def test_answer_leak_in_the_goal_is_refused_before_any_click(self):
        # Wrong patch: skip the answer-leak guard because the policy is trusted.
        self.flat();r = self.run_agent(ScriptPolicy(by_record('1:45 PM')), 'Click e25', 'Booked')
        self.assertEqual(r['status'], 'failed');self.assertEqual(self.driver.executed, [])

    def test_text_is_not_supported_in_the_prototype(self):
        self.flat();r = self.run_agent(ScriptPolicy(by_record('1:45 PM')), 'Type it', 'Booked', text='x')
        self.assertEqual((r['status'], r['reason']), ('failed', 'bad_request'));self.assertEqual(self.driver.executed, [])


class Surface(unittest.TestCase):
    def test_tool_is_absent_from_the_default_surface(self):
        # Wrong patch: register cua_agent unconditionally.
        import asyncio, server
        self.assertNotEqual(os.environ.get('CUA_TASK_EXPERIMENTAL_AGENT'), '1')
        self.assertNotIn('cua_agent', [t.name for t in asyncio.run(server.mcp.list_tools())])
        self.assertEqual(cb.surface_violations(cb.SERVER.read_text()), [])
        self.assertEqual(cb.budget_violations(), [])

    def test_tool_appears_only_with_the_flag_and_is_documented_experimental(self):
        import asyncio, experimental
        from mcp.server.fastmcp import FastMCP
        self.assertFalse(experimental.enabled())
        os.environ['CUA_TASK_EXPERIMENTAL_AGENT'] = '1'
        try:self.assertTrue(experimental.enabled())
        finally:del os.environ['CUA_TASK_EXPERIMENTAL_AGENT']
        m = FastMCP('t');experimental.register(m, lambda: None)
        tools = asyncio.run(m.list_tools())
        self.assertEqual([t.name for t in tools], ['cua_agent']);self.assertTrue(tools[0].description.startswith('Experimental'))
        self.assertEqual(cb.experimental_violations(cb.EXPERIMENTAL.read_text()), [])

    def test_lint_fails_on_an_unguarded_import_or_a_missing_experimental_marker(self):
        # Wrong patches: import the experimental tools unconditionally; document them like default tools.
        src = cb.SERVER.read_text()
        unguarded = src.replace("if os.environ.get('CUA_TASK_EXPERIMENTAL_AGENT')=='1':\n    from experimental import register\n    register(mcp,lambda:facade)", "from experimental import register\nif True:\n    register(mcp,lambda:facade)")
        self.assertNotEqual(unguarded, src);self.assertTrue(cb.experimental_guard_violations(unguarded))
        marked = cb.EXPERIMENTAL.read_text().replace('"""Experimental (option D', '"""Default path (option D')
        self.assertTrue(cb.experimental_violations(marked))


if __name__ == '__main__':unittest.main()
