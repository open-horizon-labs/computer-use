"""#56: noVNC in a browser tab. The page is one canvas plus noVNC markers; its drawn labels (Perception) are placed in the bound tab's viewport CSS px and
pressed through the Driver's browser_click, in the background, at the exact point. Fakes only: no noVNC page, browser or desktop was available, so nothing
here was measured live. Each test names the tempting wrong patch it fails."""
import unittest

import novnc
import shapes as sh
import test_dom as td
import test_live_shapes as lv
from core import Facade, Gap

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + (1600).to_bytes(4, 'big') + (1200).to_bytes(4, 'big')
OUTLINE = '- rootwebarea\n  - canvas'
URL = 'http://remote.example:6080/vnc.html?autoconnect=1'
REGIONS = [('Settings', 400, 400), ('Connect', 400, 600), ('Notes', 100, 100)]


def els():
    e, web = sh.base();e[0]['frame'] = sh.frame(0, 0, 800, 600);e[web]['frame'] = sh.frame(0, 80, 800, 520);sh.E(e, web, 'AXGroup', 'canvas', actions=[]);return e


class NoVncDriver(td.SemanticDriver):
    def __init__(self, clock=None, png=PNG, outline=OUTLINE, url=URL):
        super().__init__(clock)
        self.fix = {'window_title': 'Demo', 'elements': els()}
        self.png, self.perception_payload, self.capture_id = png, {'installed': True, 'healthy': True, 'active_version': '0.2.1'}, 'cap'
        self.base_snap = td.snap(outline, url=url);self.drawn = list(REGIONS);self.after = None
        self.window_bounds = {'x': 0, 'y': 0, 'w': 800, 'h': 600}
    def call(self, tool, args, timeout=20):
        if tool == 'get_browser_state' and 'target_id' in args and args.get('snapshot_format') == 'semantic_v2':
            self.browser_calls.append((tool, dict(args)));return dict(self.base_snap)
        if tool == 'parse_visual_regions':
            drawn = self.after if self.after and self.clicked() else self.drawn
            self.parse_result = {'regions': [{'id': 't%d' % i, 'kind': 'text', 'text': t, 'bounds': {'x': x, 'y': y, 'width': 100, 'height': 40}} for i, (t, x, y) in enumerate(drawn)]}
        return super().call(tool, args, timeout)
    def clicked(self):return [a for t, a in self.browser_calls if t == 'browser_click']
    def observe(self, *args):
        raw = super().observe(*args);raw['_image'] = self.png;raw['window_bounds'] = dict(self.window_bounds);return raw


def facade(driver):
    return Facade(driver, generic_factory=lambda: None, reader_factory=lambda: None, visual_factory=lambda: lv.UnknownVision(), sleep=lambda s: None)


class Detect(unittest.TestCase):
    def sem(self, outline=OUTLINE, url=URL):return {'ok': True, 'outline': outline, 'page': {'url': url}}
    def test_one_canvas_plus_a_marker_is_novnc_and_either_marker_does(self):
        self.assertTrue(novnc.detect(self.sem()))
        self.assertFalse(novnc.detect(self.sem(url='http://h/x')))
        self.assertTrue(novnc.detect(self.sem('- rootwebarea\n  - generic "noVNC_container"\n    - canvas', url='http://h/app')))
    def test_a_normal_page_with_a_canvas_is_not_novnc(self):
        # Wrong patch: any canvas, or any page on a vnc.html route, is novnc.
        page = '- rootwebarea\n  - heading "Sales"\n  - canvas\n  - button "Export"'
        self.assertFalse(novnc.detect(self.sem(page)));self.assertFalse(novnc.detect(self.sem(page, url='http://h/app')))
        self.assertFalse(novnc.detect(self.sem('- rootwebarea\n  - canvas\n  - canvas')))
        self.assertFalse(novnc.detect(self.sem('- rootwebarea\n  - canvas', url='http://h/charts')))
        self.assertFalse(novnc.detect(None));self.assertFalse(novnc.detect({'ok': False}))


class Look(unittest.TestCase):
    def test_look_records_the_surface_and_lists_the_drawn_labels(self):
        r = facade(NoVncDriver()).look('Demo')
        self.assertEqual(r['surface'], 'novnc');self.assertEqual([t['text'] for t in r['canvas']['text_regions']], ['Settings', 'Connect', 'Notes']);self.assertNotIn('refusal', r)
    def test_a_canvas_without_the_marker_uses_the_ordinary_canvas_route(self):
        r = facade(NoVncDriver(url='http://h/charts')).look('Demo')
        self.assertNotIn('surface', r);self.assertEqual(len(r['canvas']['text_regions']), 3)
    def test_look_refuses_without_a_provable_scale(self):
        # Wrong patch: assume 1:1 when the capture size is unknown.
        r = facade(NoVncDriver(png=b'pixels')).look('Demo')
        self.assertEqual(r['refusal']['reason'], 'viewport_mapping_unavailable');self.assertEqual(r['canvas']['text_regions'], [])
    def test_a_password_prompt_is_a_credentials_refusal_naming_the_user(self):
        d = NoVncDriver();d.drawn = [('Password:', 100, 100), ('Send Credentials', 100, 200)]
        r = facade(d).look('Demo')
        self.assertEqual(r['refusal']['reason'], 'credentials_required');self.assertIn('user', r['refusal']['hint']);self.assertEqual(r['canvas']['text_regions'], [])


class Mapping(unittest.TestCase):
    def test_capture_px_map_through_scale_and_viewport_origin(self):
        # Wrong patch: use capture px as CSS px (that would be 450, 420), or forget the viewport origin (225, 210).
        f = facade(NoVncDriver());f.look('Demo');state = next(iter(f.snapshots.values()))
        view = novnc.mapping(f, state)
        self.assertEqual((view['sx'], view['sy'], view['y']), (2.0, 2.0, 80))
        self.assertEqual(novnc.css_point(view, {'x': 400, 'y': 400, 'width': 100, 'height': 40}), (225.0, 130.0))
    def test_a_point_outside_the_viewport_is_refused(self):
        f = facade(NoVncDriver());f.look('Demo');view = novnc.mapping(f, next(iter(f.snapshots.values())))
        with self.assertRaises(Gap) as why:novnc.css_point(view, {'x': 10, 'y': 10, 'width': 20, 'height': 20})  # above the viewport (the tab strip)
        self.assertIn('viewport_mapping_unavailable', str(why.exception))


class Press(unittest.TestCase):
    def run_do(self, driver, **kw):
        f = facade(driver);return f, f.do('Press "Settings"', title='Demo', expect='Connected', **kw)
    def test_press_goes_through_browser_click_at_the_mapped_point_in_the_background(self):
        # Wrong patches: capture px as CSS px, a pixel click that fronts the window, the capture-bound click, typing.
        d = NoVncDriver();d.after = REGIONS + [('Connected', 400, 800)]
        f, r = self.run_do(d)
        self.assertEqual((r['status'], r['verified']), ('done', True), r)
        clicks = d.clicked();self.assertEqual(len(clicks), 1)
        self.assertEqual((clicks[0]['x'], clicks[0]['y']), (225.0, 130.0));self.assertTrue(clicks[0]['target_id'].startswith('bt-'))
        self.assertEqual(d.executed, [], 'no pixel click, so no window was fronted')
        self.assertEqual(d.foreground_keys, [])
        self.assertNotIn('delivery_mode', clicks[0]);self.assertNotIn('capture_id', clicks[0])
        self.assertFalse([c for c in d.browser_calls if c[0] == 'browser_type'])
    def test_the_press_is_verified_on_a_fresh_capture_never_assumed(self):
        d = NoVncDriver()  # the screen does not change
        f, r = self.run_do(d)
        self.assertNotEqual(r['status'], 'done');self.assertFalse(r.get('verified'))
        self.assertGreaterEqual(len(d.parse_calls), 2)
    def test_an_unknown_label_clicks_nothing(self):
        d = NoVncDriver();f = facade(d)
        r = f.do('Press "Nowhere"', title='Demo', expect='x')
        self.assertEqual(d.clicked(), []);self.assertNotEqual(r['status'], 'done')
    def test_a_label_that_moved_before_the_click_is_not_clicked(self):
        d = NoVncDriver();f = facade(d)
        real = d.observe;seen = {'n': 0}
        def moving(*a):
            seen['n'] += 1;raw = real(*a)
            if seen['n'] >= 2:d.drawn = [('Settings', 400, 900)] + REGIONS[1:]
            return raw
        d.observe = moving
        f.do('Press "Settings"', title='Demo', expect='Connected')
        # The stale point is never clicked; the recovery pass re-resolves the label on a fresh capture and clicks where it is NOW (900px -> 380 CSS px).
        self.assertEqual([(c['x'], c['y']) for c in d.clicked()], [(225.0, 380.0)])
    def test_a_password_prompt_is_never_typed_into_or_pressed(self):
        # Wrong patch: type the configured password, or press the dialog's button.
        d = NoVncDriver();d.drawn = [('Password:', 100, 100), ('Send Credentials', 100, 200)]
        r = facade(d).do('Press "Send Credentials"', title='Demo', expect='Connected')
        self.assertEqual((r['status'], r['reason']), ('deferred', 'credentials_required'))
        self.assertEqual(d.clicked(), []);self.assertEqual(d.executed, [])
        r = facade(d).do('Type the password', title='Demo', operation='type_text', text='hunter2')
        self.assertEqual(r['reason'], 'credentials_required');self.assertFalse([c for c in d.browser_calls if c[0] == 'browser_type']);self.assertEqual(d.executed, [])
    def test_typing_into_the_canvas_is_refused_not_faked(self):
        d = NoVncDriver();r = facade(d).do('Type hello', title='Demo', operation='type_text', text='hello')
        self.assertEqual(r['reason'], 'novnc_typing_unavailable');self.assertEqual(d.executed, [])
    def test_no_scale_means_no_click(self):
        d = NoVncDriver(png=b'pixels');r = facade(d).do('Press "Settings"', title='Demo', expect='Connected')
        self.assertEqual(r['reason'], 'viewport_mapping_unavailable');self.assertEqual(d.clicked(), [])
    def test_an_ordinary_canvas_still_needs_allow_foreground(self):
        d = NoVncDriver(url='http://h/charts');facade(d).do('Press "Settings"', title='Demo', expect='Connected')
        self.assertEqual(d.clicked(), []);self.assertEqual(d.executed, [])


if __name__ == '__main__':unittest.main()
