"""Cua Perception route: probe, capture-bound parsing, layout fallback grouping,
fuzzy OCR verification, and the regions chooser/act path. OCR text must never
feed cua_read/NuExtract or exact verification (docs/FACADE.md evidence table:
"60 min"->"600 min", "Starts 1:30 PM"->"Starts 130 PM", "Follow-up"->"Follwupe").
"""
import copy
import json
import os
import unittest

from core import Facade, Gap
from test_core import FakeChooser, FakeReader, FakeVision, FakeDriver


FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'perception_booking.json')


def load_fixture():
    with open(FIXTURE) as handle:
        return json.load(handle)


def fake_png(width, height):
    # Just enough for Facade._png_size: signature + 8 filler bytes + w + h.
    return b'\x89PNG\r\n\x1a\n' + b'\x00' * 8 + width.to_bytes(4, 'big') + height.to_bytes(4, 'big')


def flat_two_book_window(sid='sp0000001'):
    """Two 'Book' buttons with no unique labelled ancestor (flat/ambiguous AX,
    same shape sibling_record already declines to guess on): AXGroup wrapper
    with no distinguishing text, so record_context/sibling_record return
    nothing and perception layout is the only available fallback.
    """
    nodes = [
        {'element_index': 0, 'role': 'AXWindow', 'label': 'Clinic', 'frame': {'x': 0, 'y': 0, 'w': 400, 'h': 600}},
        {'element_index': 1, 'parent_index': 0, 'role': 'AXGroup', 'frame': {'x': 0, 'y': 0, 'w': 400, 'h': 600}},
        {'element_index': 2, 'parent_index': 1, 'role': 'AXButton', 'label': 'Book', 'actions': ['AXPress'],
         'frame': {'x': 230, 'y': 200, 'w': 60, 'h': 30}},
        {'element_index': 3, 'parent_index': 1, 'role': 'AXButton', 'label': 'Book', 'actions': ['AXPress'],
         'frame': {'x': 230, 'y': 400, 'w': 60, 'h': 30}},
    ]
    for n in nodes:
        n.update(element_token=sid + ':' + str(n['element_index']), enabled=True)
    return {'snapshot_id': sid, 'pid': 1, 'window_id': 2, 'window_title': 'Clinic', 'elements': nodes,
            '_image': fake_png(400, 600), 'window_bounds': {'w': 400, 'h': 600}, 'capture_id': 'cap_' + sid}


BOOK_REGIONS = {'schema': 'cua.visual_regions_v1', 'regions': [
    {'id': 'text-1', 'kind': 'text', 'text': 'Provider A', 'bounds': {'x': 220, 'y': 180, 'width': 100, 'height': 20}},
    {'id': 'text-2', 'kind': 'text', 'text': '60 min', 'bounds': {'x': 220, 'y': 185, 'width': 60, 'height': 20}},
    {'id': 'text-3', 'kind': 'text', 'text': 'Provider B', 'bounds': {'x': 220, 'y': 380, 'width': 100, 'height': 20}},
    {'id': 'text-4', 'kind': 'text', 'text': '30 min', 'bounds': {'x': 220, 'y': 385, 'width': 60, 'height': 20}},
]}


class PerceptionRouteTests(unittest.TestCase):
    def setUp(self):
        self.driver = FakeDriver()
        self.driver.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'}
        self.generic = FakeChooser(); self.reader = FakeReader(); self.visual = FakeVision()
        self.f = Facade(self.driver, generic_factory=lambda: self.generic,
                        reader_factory=lambda: self.reader, visual_factory=lambda: self.visual)

    # --- startup probe --------------------------------------------------
    def test_perception_status_probed_and_recorded(self):
        self.f.windows()
        self.assertEqual(self.f.perception_state, 'healthy')
        self.assertEqual(self.f.perception_version, '0.2.1')
        self.assertEqual(self.f.close()['perception_state'], 'healthy')

    def test_perception_not_installed_reports_gap_naming_installer(self):
        # Tempting wrong patch: silently skipping perception (returning empty
        # regions) instead of surfacing an actionable Gap for the caller.
        self.driver.perception_payload = {'installed': False}
        self.driver.capture_id = 'cap_x'
        obs = self.f.observe(1, 2)['snapshot']
        with self.assertRaisesRegex(Gap, 'install_perception.py'):
            self.f.regions(obs)

    # --- capture binding / expiry ---------------------------------------
    def test_regions_requires_live_capture_id(self):
        # Tempting wrong patch: parsing an old cached image with no capture_id
        # at all (e.g. the offline fixture's local_input path, which the real
        # extension marks action_eligible: false) instead of refusing.
        self.driver.capture_id = None
        obs = self.f.observe(1, 2)['snapshot']
        with self.assertRaisesRegex(Gap, 'capture_unavailable'):
            self.f.regions(obs)

    def test_regions_expired_capture_refused_never_silently_reparsed(self):
        # Tempting wrong patch: re-issuing parse_visual_regions against a capture
        # that has outlived the Driver's registry TTL for an old selection.
        self.driver.capture_id = 'cap_1'
        obs = self.f.observe(1, 2)['snapshot']
        self.f.clock = lambda: self.f.snapshots[obs]['created'] + 61
        with self.assertRaisesRegex(Gap, 'capture_expired'):
            self.f.regions(obs)
        self.assertEqual(self.driver.parse_calls, [])

    def test_regions_cached_per_capture_not_reparsed(self):
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = BOOK_REGIONS
        obs = self.f.observe(1, 2)['snapshot']
        self.f.regions(obs); self.f.regions(obs)
        self.assertEqual(len(self.driver.parse_calls), 1)

    def test_regions_never_reused_across_snapshots(self):
        # Tempting wrong patch: keying the cache by capture_id alone so a new
        # observation of the same window incorrectly reuses stale regions.
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = BOOK_REGIONS
        first = self.f.observe(1, 2)['snapshot']
        self.f.regions(first)
        self.driver.capture_id = 'cap_2'
        second = self.f.observe(1, 2)['snapshot']
        self.f.regions(second)
        self.assertEqual(len(self.driver.parse_calls), 2)

    # --- record grouping (description/corroboration only) ----------------
    def test_perception_layout_fallback_groups_by_vertical_band(self):
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = BOOK_REGIONS
        self.driver.observe = lambda *a: flat_two_book_window()
        state = self.f.state(self.f.observe(1, 2)['snapshot'])
        described = {a['id']: a for a in self.f.actions(state, ['e2', 'e3'], 'click', None)}
        self.assertIn('Provider A', described['e2']['description'])
        self.assertNotIn('Provider B', described['e2']['description'])
        self.assertEqual(described['e2']['record_basis'], 'perception_layout')
        self.assertIn('Provider B', described['e3']['description'])
        self.assertNotIn('Provider A', described['e3']['description'])

    def test_unique_control_never_triggers_a_perception_parse(self):
        # Live CE 2026-09-28: the confirm dialog's unique "Yes, cancel order" button
        # triggered a live parse that failed and killed cua_choose. Tempting wrong
        # patch: keep parsing first and only then check whether the control repeats.
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = BOOK_REGIONS
        self.driver.observe = lambda *a: flat_two_book_window()
        state = self.f.state(self.f.observe(1, 2)['snapshot'])
        unique = {'element_index': 40, 'parent_index': 0, 'role': 'AXButton', 'label': 'Yes, cancel order',
                  'actions': ['AXPress'], 'enabled': True, 'element_token': state['raw']['snapshot_id'] + ':40',
                  'frame': {'x': 10, 'y': 10, 'w': 50, 'h': 20}}
        state['nodes'][40] = unique
        described = self.f.actions(state, ['e40'], 'click', None)
        self.assertEqual(described[0]['description'], 'Yes, cancel order')
        self.assertEqual(self.driver.parse_calls, [])

    def test_perception_parse_failure_degrades_instead_of_crashing_choose(self):
        # Tempting wrong patch: catching only Gap, so a Driver exit status 1
        # (CalledProcessError) escapes the fallback and fails the whole choose.
        import subprocess
        self.driver.capture_id = 'cap_1'
        self.driver.observe = lambda *a: flat_two_book_window()
        real_call = self.driver.call
        def failing(tool, args, timeout=20):
            if tool == 'parse_visual_regions':
                raise subprocess.CalledProcessError(1, ['cua-driver'], stderr='capture unavailable')
            return real_call(tool, args, timeout)
        self.driver.call = failing
        state = self.f.state(self.f.observe(1, 2)['snapshot'])
        described = {a['id']: a for a in self.f.actions(state, ['e2', 'e3'], 'click', None)}
        self.assertNotIn('record:', described['e2']['description'])
        self.assertNotIn('record_basis', described['e2'])

    def test_failed_parse_is_cached_per_capture_not_retried_per_candidate(self):
        # Review P2: a failing parse re-ran for every repeated control (12 controls
        # x a 20 s timeout). Tempting wrong patch: cache only successes.
        import subprocess
        self.driver.capture_id = 'cap_1'
        self.driver.observe = lambda *a: flat_two_book_window()
        real_call = self.driver.call; calls = []
        def failing(tool, args, timeout=20):
            if tool == 'parse_visual_regions':
                calls.append(args); raise subprocess.CalledProcessError(1, ['cua-driver'], stderr='boom')
            return real_call(tool, args, timeout)
        self.driver.call = failing
        state = self.f.state(self.f.observe(1, 2)['snapshot'])
        self.f.actions(state, ['e2', 'e3'], 'click', None)
        self.assertEqual(len(calls), 1)

    def test_explicit_regions_parse_failure_is_a_clean_gap(self):
        import subprocess
        self.driver.capture_id = 'cap_1'
        real_call = self.driver.call
        def failing(tool, args, timeout=20):
            if tool == 'parse_visual_regions':
                raise subprocess.CalledProcessError(1, ['cua-driver'], stderr='extension crashed')
            return real_call(tool, args, timeout)
        self.driver.call = failing
        obs = self.f.observe(1, 2)['snapshot']
        with self.assertRaisesRegex(Gap, 'perception_parse_failed') as caught:
            self.f.regions(obs)
        # Tempting wrong patch: put stderr in the agent-visible message (paths, capture ids).
        self.assertNotIn('extension crashed', str(caught.exception))

    def test_parse_carries_the_facade_session(self):
        # Live CE 2026-09-28: parse_visual_regions answered capture_not_found for every
        # facade capture because the call omitted `session` (captures are session-scoped).
        # Tempting wrong patch: only bind capture_id, which passes every offline fake.
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = BOOK_REGIONS
        obs = self.f.observe(1, 2)['snapshot']
        self.f.regions(obs)
        self.assertEqual(self.driver.parse_calls[0]['session'], self.f.session)

    def test_perception_fallback_never_overrides_valid_ax_grouping(self):
        # Tempting wrong patch: always consulting perception layout, which could
        # silently replace a correct AX-derived record with mis-OCR'd text.
        self.driver.booking = True; self.driver.capture_id = 'cap_1'; self.driver.parse_result = BOOK_REGIONS
        obs = self.f.observe(1, 2)['snapshot']
        state = self.f.state(obs)
        self.f.actions(state, ['e6'], 'click', None)
        self.assertEqual(self.driver.parse_calls, [])

    def test_perception_layout_not_mixed_when_coordinate_space_unprovable(self):
        # Tempting wrong patch: assuming AX frame points equal screenshot pixels
        # (e.g. under Retina 2x) without checking, silently mixing spaces.
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = BOOK_REGIONS
        self.driver.observe = lambda *a: {**flat_two_book_window(), 'window_bounds': {'w': 999, 'h': 999}}
        state = self.f.state(self.f.observe(1, 2)['snapshot'])
        described = {a['id']: a for a in self.f.actions(state, ['e2', 'e3'], 'click', None)}
        self.assertNotIn('record:', described['e2']['description'])
        self.assertNotIn('record_basis', described['e2'])
        self.assertEqual(self.driver.parse_calls, [])

    # --- verify(): fuzzy OCR presence, never on digits, never on fuzzy-only --
    def test_verify_fuzzy_ocr_never_satisfies_on_quote_with_digits(self):
        # Tempting wrong patch: satisfying because "600 min" appears verbatim in
        # exactly one OCR region -- but that is itself OCR's corruption of the
        # real "60 min" (see docs/FACADE.md evidence table), so a digit-bearing
        # OCR match must never authorize a postcondition by itself; it may only
        # ever surface as unknown/ocr_candidate evidence alongside vision.
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = load_fixture()
        self.driver.observe = lambda *a: {**window_stub(), 'capture_id': 'cap_1'}
        self.visual.inspect = lambda *a, **k: {'state': 'unknown', 'evidence': 'not visible'}
        result = self.f.verify(1, 2, 'The page now shows "600 min"')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['route'], 'systemone_vision')
        self.assertEqual(result.get('perception_hint', {}).get('status'), 'unknown')
        self.assertEqual(result.get('perception_hint', {}).get('evidence'), 'ocr_candidate')

    def test_verify_fuzzy_ocr_partial_match_stays_unknown_not_satisfied(self):
        # Tempting wrong patch: treating a substring hit ("Morgan Reyes" inside
        # "Dr. Morgan Reyes") as presence confirmation.
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = load_fixture()
        self.driver.observe = lambda *a: {**window_stub(), 'capture_id': 'cap_1'}
        self.visual.inspect = lambda *a, **k: {'state': 'unknown', 'evidence': 'not visible'}
        result = self.f.verify(1, 2, 'The page now shows "Morgan Reyes"')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result.get('perception_hint', {}).get('evidence'), 'ocr_candidate')

    def test_verify_fuzzy_ocr_short_unique_digitfree_quote_can_satisfy(self):
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = load_fixture()
        self.driver.observe = lambda *a: {**window_stub(), 'capture_id': 'cap_1'}
        result = self.f.verify(1, 2, 'The page now shows "Dr. Alan Morgan"')
        self.assertEqual(result['status'], 'satisfied')
        self.assertEqual(result['route'], 'perception_ocr_fuzzy')

    def test_verify_repeated_text_across_regions_stays_unknown(self):
        # "Follow-up" appears more than once in the fixture; a repeated OCR hit
        # cannot establish which record changed, same rule as the AX check.
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = load_fixture()
        self.driver.observe = lambda *a: {**window_stub(), 'capture_id': 'cap_1'}
        self.visual.inspect = lambda *a, **k: {'state': 'unknown', 'evidence': 'not visible'}
        result = self.f.verify(1, 2, 'The page now shows "Follow-up"')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result.get('perception_hint', {}).get('evidence'), 'ocr_candidate')

    # --- cua_choose(mode='regions') and cua_act -------------------------
    def test_choose_regions_uncorroborated_defers_no_handle(self):
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = BOOK_REGIONS
        obs = self.f.observe(1, 2)['snapshot']
        result = self.f.choose(obs, 'Pick the appointment slot', mode='regions')
        self.assertEqual(result['status'], 'defer')
        self.assertEqual(result['reason'], 'visual_uncorroborated')
        self.assertNotIn('selection', result)

    def test_choose_regions_corroborated_by_quoted_text_authorizes(self):
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = BOOK_REGIONS
        obs = self.f.observe(1, 2)['snapshot']
        result = self.f.choose(obs, 'Pick the "Provider A" slot', mode='regions')
        self.assertEqual(result['status'], 'selected')
        self.assertIn('selection', result)

    def test_choose_regions_narrowed_scope_cannot_self_corroborate(self):
        # Review P1 again, in regions mode. Tempting wrong patch: checking quote
        # uniqueness among the caller's narrowed regions, which the caller controls.
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = BOOK_REGIONS
        obs = self.f.observe(1, 2)['snapshot']
        result = self.f.choose(obs, 'Pick the "Provider A" slot', mode='regions', candidate_ids=['text-1', 'text-2'])
        self.assertEqual(result['reason'], 'visual_uncorroborated')
        self.assertNotIn('selection', result)

    def test_choose_regions_requires_live_capture(self):
        self.driver.capture_id = None
        obs = self.f.observe(1, 2)['snapshot']
        with self.assertRaisesRegex(Gap, 'capture_unavailable'):
            self.f.choose(obs, 'Pick the "Provider A" slot', mode='regions')

    def test_choose_regions_rejects_answer_leaking_goal(self):
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = BOOK_REGIONS
        obs = self.f.observe(1, 2)['snapshot']
        with self.assertRaises(Gap):
            self.f.choose(obs, 'the correct one is the first', mode='regions')

    def test_act_region_selection_uses_original_capture_not_rebound(self):
        # Tempting wrong patch: rebinding to the freshly reobserved capture_id
        # the way AX element_tokens are rebound -- a capture-bound click must be
        # admitted against the SAME capture it was chosen from, never a newer one.
        self.driver.capture_id = 'cap_orig'; self.driver.parse_result = BOOK_REGIONS
        obs = self.f.observe(1, 2)['snapshot']
        selection = self.f.choose(obs, 'Pick the "Provider A" slot', mode='regions')['selection']
        self.driver.capture_id = 'cap_new'
        self.f.act(selection)
        self.assertEqual(self.driver.executed[0]['capture_id'], 'cap_orig')

    def test_act_region_selection_refuses_after_ttl(self):
        self.driver.capture_id = 'cap_1'; self.driver.parse_result = BOOK_REGIONS
        obs = self.f.observe(1, 2)['snapshot']
        selection = self.f.choose(obs, 'Pick the "Provider A" slot', mode='regions')['selection']
        self.f.clock = lambda: self.f.snapshots[obs]['created'] + 61
        with self.assertRaisesRegex(Gap, 'capture_expired'):
            self.f.act(selection)


def window_stub(sid='swin0001'):
    nodes = [{'element_index': 0, 'role': 'AXWindow', 'label': 'Clinic'}]
    for n in nodes:
        n.update(element_token=sid + ':' + str(n['element_index']), enabled=True)
    return {'snapshot_id': sid, 'pid': 1, 'window_id': 2, 'window_title': 'Clinic', 'elements': nodes, '_image': b'pixels'}


if __name__ == '__main__':
    unittest.main()
