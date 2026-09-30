"""#39 (#5): press {menu: [...]} routes a refused application-menu item through the Driver's invoke_menu, verified, in the same window only.

Synthetic menu-bar shape (no live capture has an app menu bar; roles and nesting follow macOS AX: AXMenuBar > AXMenuBarItem > AXMenu > AXMenuItem)
served through the same fakes as the other shapes. The click goes through the REAL core.Driver.call answer parsing (subprocess patched), so the
Driver's own refusal shape (`effect: refused`, `element_outside_target_window`, #5) is what is tested. No desktop, Driver or network.
Each test names the tempting wrong patch it fails.
"""
import json
import unittest
from unittest import mock

import menu
import shapes as sh
from core import DriverCallFailed, Facade
from test_core import FakeChooser
import test_live_shapes as lv

REFUSED = {'effect': 'refused', 'refusal_code': 'element_outside_target_window'}


def menu_bar(disabled=(), extra_menu_bar_title_item=False):
    """Window > AXMenuBar with Profiles (Person 1, Person 2), File (Close, Delete everything) and Window (Close), plus a web area with a Book button."""
    els, web = sh.base()
    bar = sh.E(els, 0, 'AXMenuBar', actions=[])
    def title(label, items):
        t = sh.E(els, bar, 'AXMenuBarItem', label, actions=['AXPress'])
        m = sh.E(els, t, 'AXMenu', label, actions=[])
        return {name: sh.E(els, m, 'AXMenuItem', name, enabled=name not in disabled) for name in items}
    ids = {}
    ids['Profiles'] = title('Profiles', ['Person 1', 'Person 2'])
    ids['File'] = title('File', ['Close', 'Delete everything'])
    ids['Window'] = title('Window', ['Close'])
    sh.E(els, web, 'AXButton', 'Book')
    return els, ids


class MenuDriver(sh.ShapeDriver):
    """click answers `click_answer` through the real Driver.call parser; invoke_menu is recorded and answers `menu_answer` (or raises)."""
    def __init__(self, els):
        super().__init__(els)
        self.click_answer = REFUSED;self.menu_answer = {'effect': 'ok'};self.menu_fail = None;self.menu_calls = [];self.clicks = []
        self.real = __import__('core').Driver('cua-driver')
    def call(self, tool, args, timeout=20):
        if tool == 'click':
            self.clicks.append(dict(args))
            done = mock.Mock(stdout=json.dumps(self.click_answer))
            with mock.patch('core.subprocess.run', return_value=done):
                return self.real.call(tool, args, timeout)
        if tool == 'invoke_menu':
            self.menu_calls.append(dict(args))
            if self.menu_fail:raise self.menu_fail
            done = mock.Mock(stdout=json.dumps(self.menu_answer))
            with mock.patch('core.subprocess.run', return_value=done):
                return self.real.call(tool, args, timeout)
        return super().call(tool, args, timeout)


class Base(unittest.TestCase):
    def setUp(self, **kw):
        self.els, self.ids = menu_bar(**kw)
        self.driver = MenuDriver(self.els)
        def script(driver, els):
            if driver.menu_calls or (driver.clicks and driver.click_answer.get('effect') != 'refused'):
                sh.E(els, 1, 'AXStaticText', 'Switched to Person 1', 'Switched to Person 1')
        self.driver.script = script
        self.f = Facade(self.driver, generic_factory=FakeChooser, reader_factory=lambda: lv.LiveReader({}), visual_factory=lv.UnknownVision, sleep=lambda s: None)
    def plan(self, step, **kw):
        return self.f.do('Switch profile', title='Demo', expect=None, steps=[step], **kw)
    def press(self, path=('Profiles', 'Person 1'), **kw):
        return self.plan({'do': 'press', 'menu': list(path), 'expect': 'Switched to Person 1', **kw})


class Routing(Base):
    def test_a_refused_menu_item_is_invoked_by_its_observed_path_in_the_same_window(self):
        r = self.press(allow_foreground=True)
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(len(self.driver.clicks), 1, 'the ordinary press of the observed item is tried first')
        self.assertEqual(self.driver.menu_calls, [{'session': self.f.session, 'pid': 1, 'window_id': 2, 'path': ['Profiles', 'Person 1']}])
        self.assertEqual(r['steps'][0]['selected']['route'], 'invoke_menu', 'never a silent reroute: the response names the route')
        self.assertEqual(r['steps'][0]['verification']['status'], 'satisfied')

    def test_the_refusal_is_preserved_without_allow_foreground_because_invoke_menu_fronts_the_window(self):
        # Wrong patch: reroute silently (invoke_menu temporarily activates the target window: the Driver's own doc), without the caller's permission to front it.
        r = self.press()
        self.assertEqual((r['status'], r['reason'], r['delivery']), ('refused', 'element_outside_target_window', 'none'), r)
        self.assertEqual(self.driver.menu_calls, [])
        self.assertIn('allow_foreground', r['steps'][0]['message'])
        self.assertIn('allow_foreground', r['hint'])
        self.assertNotIn('Person 1', json.dumps(r['steps'][0]['message']), 'menu labels are page text: never in a message')

    def test_the_path_is_built_from_the_observed_ancestors_not_the_callers_text(self):
        # Wrong patch: send the caller's path as typed (an unobserved segment would reach the Driver), or match labels by substring.
        for bad in (['Profiles', 'Person 3'], ['Nope', 'Person 1'], ['Profiles', 'Person'], ['Person 1', 'Profiles']):
            driver = self.driver
            r = self.press(path=bad, allow_foreground=True)
            self.assertEqual((r['status'], r['reason']), ('refused', 'menu_item_not_found'), bad)
        self.assertEqual((self.driver.clicks, self.driver.menu_calls), ([], []), 'nothing reached the Driver')

    def test_the_same_label_under_two_menus_is_told_apart_by_its_ancestors(self):
        r = self.plan({'do': 'press', 'menu': ['Window', 'Close'], 'expect': 'Switched to Person 1', 'allow_foreground': True})
        self.assertEqual(self.driver.menu_calls[0]['path'], ['Window', 'Close'])
        state = self.f.state(self.f.observe(1, 2)['snapshot'])
        self.assertEqual(menu.observed_path(state, self.ids['File']['Close']), ['File', 'Close'])
        self.assertEqual(menu.observed_path(state, self.ids['Window']['Close']), ['Window', 'Close'])
        self.assertEqual(menu.resolve(self.f, state, ['File', 'Close'])[0], self.ids['File']['Close'])

    def test_the_path_sent_is_the_raw_observed_label_not_the_callers_spelling(self):
        # Wrong patch: send the caller's (or a whitespace-normalised) text: the Driver matches each segment EXACTLY and would fail closed on a non-breaking space.
        els, ids = menu_bar()
        els[ids['Profiles']['Person 2']]['label'] = 'Person 2'
        self.driver = MenuDriver(els);self.f.driver = self.driver;self.driver.script = lambda d, e: None
        self.plan({'do': 'press', 'menu': ['Profiles', 'Person 2'], 'expect': None, 'allow_foreground': True})
        self.assertEqual(self.driver.menu_calls[0]['path'], ['Profiles', 'Person 2'])

    def test_a_menu_item_outside_the_menu_container_chain_has_no_path(self):
        # Wrong patch: walk any ancestors up to an AXMenuBar (a group between the bar and an item is not a menu level).
        els, ids = menu_bar()
        group = sh.E(els, next(i for i, n in enumerate(els) if n['role'] == 'AXMenuBar'), 'AXGroup', 'Odd group', actions=[])
        odd = sh.E(els, group, 'AXMenuItem', 'Odd item')
        self.driver = MenuDriver(els);self.f.driver = self.driver
        state = self.f.state(self.f.observe(1, 2)['snapshot'])
        self.assertIsNone(menu.observed_path(state, odd))
        with self.assertRaises(Exception):
            menu.resolve(self.f, state, ['Odd group', 'Odd item'])

    def test_the_runtime_guard_refuses_a_destructive_segment_even_when_called_without_the_plan_validation(self):
        from core import Gap
        with self.assertRaises(Gap) as caught:
            menu.press(self.f, 1, 2, ['File', 'Delete everything'], 'Open the File menu item')
        self.assertTrue(str(caught.exception).startswith('destructive_control'))
        self.assertEqual((self.driver.clicks, self.driver.menu_calls), ([], []))

    def test_a_node_that_is_not_under_the_menu_bar_has_no_path(self):
        state = self.f.state(self.f.observe(1, 2)['snapshot'])
        book = next(i for i, n in state['nodes'].items() if n.get('label') == 'Book')
        self.assertIsNone(menu.observed_path(state, book))

    def test_an_ordinary_press_that_the_driver_accepts_is_never_routed_through_invoke_menu(self):
        self.driver.click_answer = {'effect': 'unverifiable'}
        r = self.press(allow_foreground=True)
        self.assertEqual(r['status'], 'done', r)
        self.assertEqual(self.driver.menu_calls, [])
        self.assertEqual(r['steps'][0]['selected']['route'], 'press')
        token = self.driver.clicks[0]['element_token']
        self.assertTrue(token.endswith(':%d' % self.ids['Profiles']['Person 1']), 'the click bound exactly the observed menu item')

    def test_only_a_menu_item_is_rerouted_a_refused_page_control_stays_refused(self):
        # Wrong patch: reroute ANY element_outside_target_window refusal (a page button, a popup button) through invoke_menu.
        r = self.plan({'do': 'press', 'control': 'Book', 'expect': None, 'allow_foreground': True})
        self.assertEqual((r['status'], r['reason']), ('refused', 'element_outside_target_window'), r)
        self.assertEqual(self.driver.menu_calls, [])
        self.assertEqual(len(self.driver.clicks), 1)

    def test_any_other_refusal_of_a_menu_item_is_not_rerouted(self):
        # Wrong patch: fall back to invoke_menu on every failure of the ordinary press.
        for answer in ({'effect': 'refused', 'refusal_code': 'element_not_actionable'}, {'status': 'refused', 'refusal': {'code': 'window_not_found'}}):
            self.setUp();self.driver.click_answer = answer
            r = self.press(allow_foreground=True)
            self.assertEqual(r['status'], 'refused', r)
            self.assertNotEqual(r['reason'], 'menu_item_not_found')
            self.assertEqual(self.driver.menu_calls, [], answer)

    def test_a_driver_failure_of_the_ordinary_press_is_not_rerouted_either(self):
        def boom(tool, args, timeout=20, _call=self.driver.call):
            if tool == 'click':raise DriverCallFailed('driver_call_failed: click timed out', 'click', 'timeout')
            return _call(tool, args, timeout)
        self.driver.call = boom
        r = self.press(allow_foreground=True)
        self.assertEqual((r['status'], r['delivery']), ('failed', 'uncertain'), r)
        self.assertEqual(self.driver.menu_calls, [])

    def test_a_disabled_item_stops_before_any_driver_action(self):
        self.setUp(disabled=('Person 1',))
        r = self.press(allow_foreground=True)
        self.assertEqual((r['status'], r['reason']), ('refused', 'menu_item_disabled'))
        self.assertEqual((self.driver.clicks, self.driver.menu_calls), ([], []))

    def test_a_menu_bar_title_is_not_a_menu_item(self):
        r = self.plan({'do': 'press', 'menu': ['File', 'Profiles'], 'expect': None})
        self.assertEqual(r['reason'], 'menu_item_not_found')
        r = self.plan({'do': 'press', 'menu': ['Profiles', 'Person 1', 'Person 2'], 'expect': None})
        self.assertEqual(r['reason'], 'menu_item_not_found')

    def test_a_page_without_a_menu_bar_has_nothing_to_resolve(self):
        els, web = sh.base();sh.E(els, web, 'AXButton', 'Book')
        self.f.driver = MenuDriver(els)
        r = self.press(allow_foreground=True)
        self.assertEqual(r['reason'], 'menu_item_not_found')

    def test_the_invoke_menu_refusal_is_reported_and_not_retried(self):
        self.driver.menu_answer = {'status': 'refused', 'refusal': {'code': 'menu_item_disabled'}}
        r = self.press(allow_foreground=True)
        self.assertEqual((r['status'], r['reason'], r['delivery']), ('refused', 'menu_item_disabled', 'none'), r)
        self.assertEqual(len(self.driver.menu_calls), 1)

    def test_an_invoke_menu_failure_is_uncertain_delivery_and_never_retried(self):
        self.driver.menu_fail = DriverCallFailed('driver_call_failed: invoke_menu timed out', 'invoke_menu', 'timeout')
        r = self.press(allow_foreground=True)
        self.assertEqual((r['status'], r['reason'], r['delivery']), ('failed', 'driver_call_failed', 'uncertain'), r)
        self.assertEqual(len(self.driver.menu_calls), 1)
        self.assertEqual(r.get('retryable'), False)

    def test_an_effect_refused_invoke_menu_answer_is_a_refusal_not_delivered(self):
        self.driver.menu_answer = {'effect': 'refused', 'refusal_code': 'menu_item_ambiguous'}
        r = self.press(allow_foreground=True)
        self.assertEqual((r['status'], r['reason'], r['delivery']), ('refused', 'menu_item_ambiguous', 'none'), r)

    def test_verification_is_like_any_press_delivery_without_the_expect_is_not_done(self):
        self.driver.script = None  # the page never shows the expected text
        r = self.press(allow_foreground=True)
        self.assertEqual((r['status'], r['reason']), ('stopped', 'delivery_unverified'), r)
        self.assertEqual(r['delivery'], 'delivered')
        self.assertEqual(len(self.driver.menu_calls), 1, 'never invoked twice')
        last = self.plan({'do': 'press', 'menu': ['Profiles', 'Person 2'], 'expect': None, 'allow_foreground': True})
        self.assertEqual(last['status'], 'delivered_unverified', last)

    def test_the_route_never_names_another_window(self):
        # Wrong patch: take pid/window_id from the caller, or from a fresh window list instead of the observation of THIS window.
        self.press(allow_foreground=True)
        call = self.driver.menu_calls[0]
        self.assertEqual((call['pid'], call['window_id']), (1, 2))
        self.assertEqual(set(call), {'session', 'pid', 'window_id', 'path'})


class Destructive(Base):
    def test_a_destructive_last_segment_needs_its_exact_allow_destructive(self):
        r = self.plan({'do': 'press', 'menu': ['File', 'Delete everything'], 'expect': None, 'allow_foreground': True})
        self.assertEqual((r['status'], r['reason']), ('refused', 'destructive_control'))
        self.assertEqual((self.driver.clicks, self.driver.menu_calls), ([], []))
        r = self.plan({'do': 'press', 'menu': ['File', 'Delete everything'], 'expect': None, 'allow_foreground': True, 'allow_destructive': 'Delete everything'})
        self.assertEqual(r['status'], 'delivered_unverified', r)
        self.assertEqual(self.driver.menu_calls[0]['path'], ['File', 'Delete everything'])

    def test_a_destructive_menu_title_is_never_unlocked_by_allow_destructive(self):
        r = self.plan({'do': 'press', 'menu': ['Delete everything', 'Close'], 'expect': None, 'allow_destructive': 'Close'})
        self.assertEqual(r['reason'], 'destructive_control')
        r = self.plan({'do': 'press', 'menu': ['Delete everything', 'Close'], 'expect': None, 'allow_destructive': 'Delete everything'})
        self.assertEqual(r['reason'], 'destructive_control', 'only the LAST segment can be allowed')

    def test_goal_text_does_not_authorize_it(self):
        r = self.f.do('Delete everything from the File menu', title='Demo', expect=None, steps=[{'do': 'press', 'menu': ['File', 'Delete everything'], 'expect': None, 'allow_foreground': True}])
        self.assertEqual(r['reason'], 'destructive_control')


class Validation(Base):
    def refused(self, step):
        r = self.plan(step)
        self.assertEqual(r['status'], 'refused', r)
        self.assertEqual((self.driver.clicks, self.driver.menu_calls, self.driver.observe_args), ([], [], []), 'refused before any Driver action')
        return r

    def test_menu_needs_two_to_eight_labels(self):
        self.refused({'do': 'press', 'menu': ['Profiles'], 'expect': None})
        self.refused({'do': 'press', 'menu': [], 'expect': None})
        self.refused({'do': 'press', 'menu': ['a'] * 9, 'expect': None})
        self.refused({'do': 'press', 'menu': ['Profiles', ''], 'expect': None})
        self.refused({'do': 'press', 'menu': 'Profiles > Person 1', 'expect': None})

    def test_menu_is_not_combined_with_other_selectors(self):
        self.refused({'do': 'press', 'menu': ['Profiles', 'Person 1'], 'control': 'Book', 'expect': None})
        self.refused({'do': 'press', 'menu': ['Profiles', 'Person 1'], 'where': {'lines': [{'line': 'eq', 'value': 'x'}]}, 'expect': None})

    def test_only_press_takes_menu(self):
        self.refused({'do': 'verify', 'menu': ['Profiles', 'Person 1'], 'expect': 'x'})
        self.refused({'do': 'type', 'control': 'a', 'text': 'b', 'menu': ['Profiles', 'Person 1'], 'expect': None})

    def test_a_press_step_still_needs_a_target(self):
        self.refused({'do': 'press', 'expect': None})

    def test_a_non_final_menu_step_needs_expect(self):
        r = self.f.do('x', title='Demo', expect=None, steps=[{'do': 'press', 'menu': ['Profiles', 'Person 1'], 'expect': None}, {'do': 'verify', 'expect': 'y'}])
        self.assertEqual(r['reason'], 'expect_required')


if __name__ == '__main__':
    unittest.main()
