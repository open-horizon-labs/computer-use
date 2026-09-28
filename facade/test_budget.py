"""Architectural guardrails: the default path is cua_look then cua_do, two tools and a measured number of LLM-visible calls (CALL_BUDGET.json, CE-FACADE-003/005).

The facade once drifted into eight tools the driving LLM mediated hop by hop (9 calls for a clean booking, native
about 5) and nothing noticed. These tests drive the REAL server tool functions through a counting harness and lint
the tool surface and the skill. Each names the tempting wrong patch it fails; the mutation tests prove the guards bite.
"""
import copy
import json
import unittest

import call_budget as cb

try:
    import server  # noqa: F401
    HAVE_SERVER = True
except ImportError:
    HAVE_SERVER = False  # facade requirements (mcp) not installed; CI and .venv-facade always have them

BUDGET = cb.load_budget()
SERVER_SOURCE = cb.SERVER.read_text()


class Provenance(unittest.TestCase):
    def test_every_number_names_an_existing_ce_that_records_the_same_number(self):
        # Wrong patch: edit a number in CALL_BUDGET.json without a CE.
        self.assertEqual(cb.budget_violations(), [])

    def test_editing_a_number_silently_is_caught(self):
        edited = copy.deepcopy(BUDGET);edited['scenarios']['booking_list']['max_llm_visible_calls']['value'] = 3
        self.assertTrue(any('booking_list.max_llm_visible_calls' in v for v in cb.budget_violations(edited)))

    def test_a_number_without_a_ce_id_is_caught(self):
        edited = copy.deepcopy(BUDGET);edited['max_tool_count']['changed_by'] = 'CE-NOPE'
        self.assertTrue(any('names no CE' in v for v in cb.budget_violations(edited)))


class ToolSurface(unittest.TestCase):
    def test_surface_is_clean(self):
        self.assertEqual(cb.surface_violations(SERVER_SOURCE), [])

    def test_cua_do_then_cua_look_first_and_every_other_tool_is_opt_in_and_advanced(self):
        tools = cb.tool_surface(SERVER_SOURCE)
        self.assertEqual([t[0] for t in tools[:2]], ['cua_do', 'cua_look']);self.assertEqual(BUDGET['default_path_tools']['value'], ['cua_do', 'cua_look'])
        self.assertEqual(BUDGET['default_path_tools']['changed_by'], 'CE-FACADE-005')
        self.assertFalse(tools[0][2] or tools[1][2]);self.assertFalse(tools[1][1].startswith('Advanced'))
        self.assertTrue(all(doc.startswith('Advanced') and nested for _, doc, nested in tools[2:]))
        self.assertLessEqual(len(tools), BUDGET['max_tool_count']['value'])

    def test_a_third_default_tool_or_a_look_hidden_behind_advanced_fails(self):
        # Wrong patch: nest cua_look inside register_advanced (the default path would lose its sight), or add a third visible tool.
        hidden = SERVER_SOURCE.replace('@mcp.tool(annotations=READ)\ndef cua_look(', 'def cua_look_gone(', 1)
        self.assertTrue(cb.surface_violations(hidden))
        third = SERVER_SOURCE.replace('def register_advanced():', '@mcp.tool(annotations=READ)\ndef cua_extra() -> dict:\n    """Peek."""\n    return {}\n\ndef register_advanced():', 1)
        self.assertTrue(any('registered by default' in v for v in cb.surface_violations(third)), cb.surface_violations(third))
        swapped = SERVER_SOURCE
        i, j = swapped.index('@mcp.tool(annotations=ACT)\ndef cua_do'), swapped.index('@mcp.tool(annotations=READ)\ndef cua_look')
        look_first = swapped[:i] + swapped[j:swapped.index('def register_advanced')] + swapped[i:j] + swapped[swapped.index('def register_advanced'):]
        self.assertTrue(any('registered first' in v for v in cb.surface_violations(look_first)), cb.surface_violations(look_first))

    def test_a_new_unmarked_tool_fails(self):
        # Wrong patch: add a mandatory read/choose/verify tool to the default path.
        added = SERVER_SOURCE.replace('    @mcp.tool(annotations=READ)\n    def cua_trace', '    @mcp.tool(annotations=READ)\n    def cua_confirm() -> dict:\n        """Confirm the last action."""\n        return {}\n\n    @mcp.tool(annotations=READ)\n    def cua_trace')
        self.assertNotEqual(added, SERVER_SOURCE)
        found = cb.surface_violations(added)
        self.assertTrue(any('cua_confirm' in v and 'Advanced' in v for v in found), found)

    def test_a_top_level_tool_is_visible_by_default_and_fails(self):
        # Wrong patch: a mandatory extra tool beside cua_do (the live run: eight visible tools made the LLM mediate every hop).
        top = SERVER_SOURCE.replace('def register_advanced():', '@mcp.tool(annotations=READ)\ndef cua_verify_now() -> dict:\n    """Advanced: check the window."""\n    return {}\n\ndef register_advanced():', 1)
        self.assertTrue(any('registered by default' in v for v in cb.surface_violations(top)), cb.surface_violations(top))

    def test_primitives_registered_by_default_fail(self):
        # Wrong patch: drop the CUA_TASK_ADVANCED guard so all eight primitives are visible again.
        for unguarded in (SERVER_SOURCE.replace('if ADVANCED:register_advanced()', 'register_advanced()'),
                          SERVER_SOURCE.replace("ADVANCED=os.environ.get('CUA_TASK_ADVANCED')=='1'", 'ADVANCED=True')):
            self.assertNotEqual(unguarded, SERVER_SOURCE)
            self.assertTrue(any('CUA_TASK_ADVANCED' in v for v in cb.surface_violations(unguarded)))

    def test_registering_another_tool_before_cua_do_fails(self):
        moved = SERVER_SOURCE.replace('@mcp.tool(annotations=ACT)\ndef cua_do', '@mcp.tool(annotations=READ)\ndef cua_pre() -> dict:\n    """Advanced: x."""\n    return {}\n\n@mcp.tool(annotations=ACT)\ndef cua_do', 1)
        self.assertTrue(any('registered first' in v for v in cb.surface_violations(moved)))

    def test_too_many_tools_fails(self):
        extra = ''.join('\n    @mcp.tool(annotations=READ)\n    def cua_extra%d() -> dict:\n        """Advanced: x."""\n        return {}\n' % i for i in range(3))
        grown = SERVER_SOURCE.replace('\nif ADVANCED:register_advanced()', extra + '\nif ADVANCED:register_advanced()')
        self.assertTrue(any('max_tool_count' in v for v in cb.surface_violations(grown)))

    def test_advanced_marker_on_the_default_tool_fails(self):
        marked = SERVER_SOURCE.replace('"""Default path.', '"""Advanced: Default path.')
        self.assertTrue(any('marked Advanced' in v for v in cb.surface_violations(marked)))

    @unittest.skipUnless(HAVE_SERVER, 'needs mcp')
    def test_default_surface_is_exactly_cua_do_and_advanced_mode_adds_the_documented_primitives(self):
        import asyncio
        default = [t.name for t in asyncio.run(server.mcp.list_tools())]
        self.assertEqual(default, ['cua_do', 'cua_look'])
        advanced = cb.advanced_tool_names()
        self.assertEqual(advanced, [name for name, _, _ in cb.tool_surface(SERVER_SOURCE)])
        self.assertEqual(advanced[:2], ['cua_do', 'cua_look']);self.assertEqual(len(advanced), 10)
        docs = dict((n, d) for n, d, _ in cb.tool_surface(SERVER_SOURCE))
        self.assertTrue(all(docs[n].startswith('Advanced') for n in advanced[2:]))

    @unittest.skipUnless(HAVE_SERVER, 'needs mcp')
    def test_the_mcp_instructions_describe_only_look_then_do(self):
        # Wrong patch: instructions that still walk the LLM through cua_windows -> cua_observe -> cua_read, or that never mention the look.
        instructions = server.mcp.instructions
        self.assertIn('cua_do', instructions);self.assertIn('cua_look', instructions);self.assertLess(instructions.index('cua_look'), instructions.index('cua_do'))
        self.assertFalse(__import__('re').search(r'cua_(?:windows|observe|read|choose|act|verify|trace|finish)', instructions), instructions)


class SkillLint(unittest.TestCase):
    TEXT = cb.SKILL.read_text()

    def test_default_workflow_names_cua_look_then_cua_do_and_nothing_else(self):
        self.assertEqual(cb.skill_violations(self.TEXT), [])
        section = cb.default_workflow_section(self.TEXT)
        names = __import__('re').findall(r'cua_[a-z_]+', section)
        self.assertEqual(names[0], 'cua_look');self.assertEqual(set(names), {'cua_look', 'cua_do'})

    def test_reintroducing_the_chain_in_prose_fails(self):
        # Wrong patch: instruct observe -> read -> choose -> act -> verify as the normal path.
        chain = self.TEXT.replace('## Advanced primitives', 'Then call `cua_observe`, `cua_read`, `cua_choose`, `cua_act` and `cua_verify` in turn.\n\n## Advanced primitives', 1)
        self.assertTrue(any('chain' in v or 'names' in v for v in cb.skill_violations(chain)))

    def test_leading_with_a_primitive_fails(self):
        led = self.TEXT.replace('Call `cua_look` first when', 'Call `cua_windows`, then `cua_do`, and `cua_look` when', 1)
        self.assertTrue(any('first' in v or 'other than' in v for v in cb.skill_violations(led)))
        do_first = self.TEXT.replace('## Default workflow\n\nCall `cua_look` first', '## Default workflow\n\nCall `cua_do`, or call `cua_look` first', 1)
        self.assertTrue(any('cua_look first' in v for v in cb.skill_violations(do_first)))

    def test_missing_section_fails(self):
        self.assertTrue(cb.skill_violations(self.TEXT.replace('## Default workflow', '## Something else')))


class Measure(unittest.TestCase):
    def test_measure_of_a_failing_run_is_reported(self):
        good = {'calls': 1, 'reader': 1, 'chooser': 0, 'max_bytes': 900, 'status': 'done', 'tools': ['cua_do']}
        plan = {'calls': 2, 'reader': 0, 'chooser': 0, 'max_bytes': 900, 'status': 'done', 'tools': ['cua_look', 'cua_do']}
        self.assertEqual(cb.over_budget(plan, BUDGET['scenarios']['plan_booking_look_do']), [])
        self.assertTrue(cb.over_budget({**plan, 'calls': 3}, BUDGET['scenarios']['plan_booking_look_do']))  # a look that needs a second look
        self.assertTrue(cb.over_budget({**plan, 'reader': 1}, BUDGET['scenarios']['plan_booking_look_do']))  # NuExtract in the default look
        limits = BUDGET['scenarios']['booking_list']
        self.assertEqual(cb.over_budget(good, limits), [])
        self.assertTrue(cb.over_budget({**good, 'calls': 9}, limits))  # the measured pre-cua_do behavior
        self.assertTrue(cb.over_budget({**good, 'reader': 2}, limits))  # a second reader call
        self.assertTrue(cb.over_budget({**good, 'chooser': 1}, limits))  # the chooser for a grounded singleton

    def test_table_flags_oversized_responses_and_primitive_use(self):
        base = {n: {'calls': 1, 'reader': 0, 'chooser': 0, 'max_bytes': 100, 'status': BUDGET['scenarios'][n].get('final_status', 'done'), 'tools': ['cua_do']} for n in BUDGET['scenarios']}
        rows, problems = cb.table(BUDGET, base)
        self.assertTrue(all(r[3] == 'PASS' for r in rows), problems)
        for name, patch in (('booking_list', {'max_bytes': 99999}), ('booking_list', {'tools': ['cua_do', 'cua_read']}), ('booking_list', {'status': 'deferred'})):
            broken = {**base, name: {**base[name], **patch}}
            self.assertTrue(cb.table(BUDGET, broken)[1], patch)


@unittest.skipUnless(HAVE_SERVER, 'needs mcp: run with .venv-facade or after pip install -r facade/requirements.txt')
class DefaultPathBudget(unittest.TestCase):
    """The real server tools, fake fixtures. Wrong patches: a mandatory read/choose/verify hop on the default path,
    the chooser for a grounded singleton, a second reader call per cycle, a response that dumps the observation."""
    @classmethod
    def setUpClass(cls):
        cls.measured = cb.measure_scenarios()

    def scenario(self, name):
        m = self.measured[name];limits = BUDGET['scenarios'][name]
        self.assertEqual(m['status'], limits.get('final_status', 'done'), m)
        self.assertEqual(cb.over_budget(m, limits), [], m)
        self.assertLessEqual(set(m['tools']), set(BUDGET['default_path_tools']['value']))
        self.assertLessEqual(m['max_bytes'], BUDGET['max_response_bytes']['value'])
        return m

    def test_booking_list_is_one_call_one_read_no_chooser(self):
        m = self.scenario('booking_list');self.assertEqual((m['calls'], m['reader'], m['chooser']), (1, 1, 0))

    def test_orders_confirm_stays_within_two_calls(self):
        m = self.scenario('orders_confirm');self.assertLessEqual(m['reader'], 2);self.assertEqual(m['chooser'], 0)  # confirm is by exact label, never the chooser

    def test_real_orders_with_the_dialog_follow_up_costs_at_most_two_calls(self):
        m = self.scenario('confirm_deferral');self.assertLessEqual(m['calls'], 2);self.assertEqual(m['chooser'], 0)

    def test_canvas_regions_stays_within_two_calls(self):
        m = self.scenario('canvas_regions');self.assertEqual(m['reader'], 0)

    def test_large_page_response_is_bounded(self):
        m = self.scenario('large_page_400');self.assertLess(m['max_bytes'], BUDGET['max_response_bytes']['value'])

    def test_the_real_booking_page_is_one_call_one_read_no_chooser(self):
        # Wrong patch: discovery by repeated press-capable node (live: records_ambiguous on both real pages, then 8 calls).
        m = self.scenario('booking_list');self.assertEqual((m['calls'], m['reader'], m['chooser']), (1, 1, 0))

    @unittest.skipUnless(HAVE_SERVER, 'needs mcp')
    def test_the_same_measurement_holds_with_the_primitives_registered(self):
        # Advanced mode must not change the default path: cua_do alone still does the work in the same number of calls.
        ran = cb.advanced_run("import json, call_budget as cb; print(json.dumps(cb.measure_scenarios()))")
        for name, m in self.measured.items():
            self.assertEqual((ran[name]['calls'], ran[name]['tools'], ran[name]['reader'], ran[name]['chooser']), (m['calls'], m['tools'], m['reader'], m['chooser']), name)

    def test_recovery_and_deferral_paths_are_measured_not_assumed(self):
        # Wrong patch: a harness that makes one call per scenario by construction. These paths must be measured through real invocations.
        for name, calls in (('stale_recovery', 1), ('driver_failure_recovered', 1), ('unknown_then_accept', 3), ('confirm_deferral', 2), ('ambiguity_deferral', 2)):
            self.scenario(name);self.assertEqual(self.measured[name]['calls'], calls, name)
        self.assertEqual(self.measured['stale_recovery']['reader'], 2)  # one read per pass, not a hidden re-read loop

    def test_a_cua_do_that_secretly_needs_a_second_call_fails_the_stale_recovery_budget(self):
        # P2-5 mutation: a recovery that hands the work back to the LLM on a stale pass must blow the 1-call budget.
        from unittest import mock
        from core import Facade
        real = Facade.do
        def needs_second(self, *a, **k):
            r = real(self, *a, **k)
            return {**r, 'status': 'deferred', 'reason': 'records_ambiguous', 'found': {'controls': ['Book']}} if r['status'] == 'done' and r.get('trace_summary', {}).get('passes', 0) > 1 else r
        with mock.patch.object(Facade, 'do', needs_second):
            m = cb.measure_scenarios()['stale_recovery']
        self.assertGreaterEqual(m['calls'], 2)
        self.assertTrue(any('calls %d' % m['calls'] in v for v in cb.over_budget(m, BUDGET['scenarios']['stale_recovery'])), m)

    def test_the_shape_corpus_is_budgeted_from_an_llm_that_learns_only_from_deferrals(self):
        # Wrong patch: budgets tuned to fixtures whose first call always succeeds. Orders with nothing known up front costs three calls:
        # control_needed, the dialog deferral, then a second cua_do quoting a dialog label.
        m = self.measured
        self.assertEqual((m['orders_cold']['calls'], m['orders_confirm']['calls']), (3, 1))
        for name, calls in (('per_record_labels', 1), ('single_record', 1), ('toast_after_click', 1), ('five_button_dialog', 2), ('toolbar_records_ambiguous', 2), ('disabled_record', 1), ('canvas_dead_end', 1)):
            self.assertEqual(m[name]['calls'], calls, name);self.assertIn(name, BUDGET['scenarios'])
        self.assertEqual((BUDGET['scenarios']['disabled_record']['final_status'], BUDGET['scenarios']['canvas_dead_end']['final_status']), ('deferred', 'deferred'))
        self.assertEqual(BUDGET['live_task_budgets']['orders']['max_llm_visible_calls']['value'], m['orders_cold']['calls'])
        self.assertIn('unrelated', BUDGET['purpose']);self.assertIn('fixture-derived', BUDGET['purpose'])

    def test_the_two_live_findings_are_budgeted_from_goal_and_expect_alone(self):
        # Live n=1 findings. Wrong patch: a budget that assumed the first call succeeds (blind predicates silently clicked the wrong slot in ONE call;
        # the canvas dead-ended). The blind first call must DEFER, so the right answer costs two calls; the canvas costs two.
        m = self.measured
        self.assertEqual((m['booking_blind_predicates']['calls'], m['booking_blind_predicates']['chooser']), (2, 1))
        self.assertEqual((m['canvas_regions']['calls'], m['canvas_regions']['reader'], m['canvas_regions']['chooser']), (2, 0, 0))
        self.assertLessEqual(BUDGET['scenarios']['booking_blind_predicates']['max_llm_visible_calls']['value'], 2)
        self.assertLessEqual(BUDGET['scenarios']['canvas_regions']['max_llm_visible_calls']['value'], 2)
        self.assertIn('n=1', BUDGET['scenarios']['canvas_regions']['description']);self.assertIn('n=1', BUDGET['scenarios']['booking_blind_predicates']['description'])

    def test_look_then_plan_is_two_calls_with_no_reader_and_no_chooser_on_the_real_trees(self):
        # Option B (CE-FACADE-005). Wrong patch: a look that runs NuExtract by default, a filter that needs the chooser, or a plan that needs a second do.
        m = self.measured
        for name in ('plan_booking_look_do', 'plan_booking_half_hour_look_do', 'plan_orders_look_do'):
            self.scenario(name);self.assertEqual((m[name]['calls'], m[name]['reader'], m[name]['chooser'], m[name]['tools']), (2, 0, 0, ['cua_look', 'cua_do']), name)

    def test_the_other_plan_shapes_are_two_calls_measured(self):
        m = self.measured
        for name in ('plan_wizard_3_steps', 'plan_invoices_100_focus', 'plan_canvas_look_do'):
            self.scenario(name);self.assertEqual((m[name]['calls'], m[name]['reader'], m[name]['chooser']), (2, 0, 0), name)
        self.scenario('plan_invoices_100_fields');self.assertEqual((m['plan_invoices_100_fields']['calls'], m['plan_invoices_100_fields']['reader']), (2, 1))

    def test_the_costs_of_skipping_the_look_or_guessing_wrong_are_measured_not_hidden(self):
        # A blind lines plan is refused (one wasted call); a wrong dialog guess or wrong last label costs one more call; a blind fields filter still defers.
        m = self.measured
        self.assertEqual([self.scenario(n) and m[n]['calls'] for n in ('plan_booking_no_look', 'plan_orders_identity_default', 'plan_orders_wrong_dialog_guess', 'plan_wizard_wrong_final_label')], [3, 3, 3, 3])
        self.assertEqual(m['plan_booking_no_look']['tools'], ['cua_do', 'cua_look', 'cua_do'])
        self.assertEqual((m['plan_booking_blind_fields']['calls'], m['plan_booking_blind_fields']['reader'], m['plan_booking_blind_fields']['chooser']), (2, 3, 1))

    def test_a_stale_page_mid_plan_stops_at_that_step_and_is_budgeted_as_stopped(self):
        m = self.scenario('plan_stale_mid_plan');self.assertEqual((m['status'], m['calls']), ('stopped', 2))
        self.assertEqual(BUDGET['scenarios']['plan_stale_mid_plan']['final_status'], 'stopped')

    def test_every_plan_scenario_number_is_tied_to_ce_facade_005_and_measured_live_is_not_claimed(self):
        for name, limits in BUDGET['scenarios'].items():
            if name.startswith('plan_'):
                self.assertTrue(all(limits[k]['changed_by'] == 'CE-FACADE-005' for k in ('max_llm_visible_calls', 'max_reader_calls', 'max_chooser_calls')), name)
        self.assertIn('fixture-derived', BUDGET['purpose']);self.assertIn('none yet for plans', BUDGET['purpose'])

    def test_a_default_look_that_calls_the_reader_trips_the_reader_budget(self):
        # Mutation of the real Facade: NuExtract in the default look (the wrong patch: 'extract values for the LLM's convenience').
        from unittest import mock
        from core import Facade
        real = Facade.look
        def look_with_extraction(self, *a, **k):
            out = real(self, *a, **k)
            snap = next(iter(self.snapshots))
            try:self.provider('reader').extract({'snapshot_id': self.snapshots[snap]['raw']['snapshot_id'], 'task': 't', 'fields': {'provider': 'p'}, 'records': [{'id': 'e1', 'text': 'Dr. A'}]}, self.snapshots[snap]['raw']['snapshot_id'])
            except KeyError:pass  # the fake reader counted the request before it looked for a pattern
            return out
        with mock.patch.object(Facade, 'look', look_with_extraction):
            m = cb.measure_scenarios()['plan_booking_look_do']
        self.assertTrue(any('reader 1' in v for v in cb.over_budget(m, BUDGET['scenarios']['plan_booking_look_do'])), m)

    def test_a_plan_that_secretly_needs_a_second_do_fails_the_budget(self):
        # Mutation: a plan that stops after its first successful step hands the work back to the LLM.
        from unittest import mock
        from core import Facade
        real = Facade.do
        def hands_back(self, *a, **k):
            r = real(self, *a, **k)
            return {**r, 'status': 'stopped', 'reason': 'control_needed'} if k.get('steps') is None and len(a) > 14 and a[14] and r['status'] == 'done' else r
        with mock.patch.object(Facade, 'do', hands_back):
            rows, problems = cb.table(BUDGET, cb.measure_scenarios())
        self.assertTrue(any(p.startswith('plan_booking_look_do') for p in problems), problems)

    def test_no_call_count_literal_is_claimed_by_the_tool(self):
        # Wrong patch: llm_visible_calls hardcoded in the response; a tool cannot know how many calls the LLM makes.
        self.assertNotIn('llm_visible_calls', (cb.HERE / 'core.py').read_text())

    def test_all_scenarios_pass_the_table(self):
        rows, problems = cb.table(BUDGET, self.measured)
        self.assertEqual(problems, []);self.assertTrue(all(r[3] == 'PASS' for r in rows))

    def test_a_second_reader_call_or_a_chooser_for_singletons_trips_the_real_measurement(self):
        # Mutation: patch the real Facade with each wrong repair and confirm the harness reports it.
        from unittest import mock
        from core import Facade
        real_read, real_choose = Facade.read, Facade.choose
        def read_twice(self, *a, **k):
            real_read(self, *a, **k);return real_read(self, *a, **k)
        with mock.patch.object(Facade, 'read', read_twice):
            m = cb.measure_scenarios()['booking_list']
        self.assertTrue(any('reader 2' in v for v in cb.over_budget(m, BUDGET['scenarios']['booking_list'])), m)
        def chooser_for_singleton(self, snapshot, goal, *a, **k):
            made = real_choose(self, snapshot, goal, *a, **k)
            self.provider('generic')(None, {'actions': [{'id': 'x', 'name': 'x'}]}) if made.get('route') == 'grounded_singleton' else None
            return made
        with mock.patch.object(Facade, 'choose', chooser_for_singleton):
            m = cb.measure_scenarios()['booking_list']
        self.assertTrue(any('chooser 1' in v for v in cb.over_budget(m, BUDGET['scenarios']['booking_list'])), m)

    def test_the_counting_harness_sees_every_tool_call(self):
        # Wrong patch: a harness that counts only cua_do would hide a hand-driven chain. Run in advanced mode, where the chain exists.
        names = cb.advanced_run("""
import asyncio, json, server, call_budget as cb
from core import Facade
from test_core import FakeVision
import test_do as fx
server.facade = Facade(fx.FlatDriver(), reader_factory=fx.LineReader, generic_factory=fx.NamedChooser, visual_factory=FakeVision, sleep=lambda s: None)
names = []
def call(name, **kw):
    names.append(name);return json.loads(cb.result_text(asyncio.run(server.mcp.call_tool(name, kw))))
obs = call('cua_observe', pid=1, window_id=2)
call('cua_read', snapshot=obs['snapshot'], task='t', fields={'provider': {'description': 'p'}}, record_ids=['e5'])
print(json.dumps(names))
""")
        self.assertEqual(names, ['cua_observe', 'cua_read'])
        self.assertEqual(cb.over_budget({'calls': 5, 'reader': 1, 'chooser': 1}, BUDGET['scenarios']['booking_list'])[0][:7], 'calls 5')


if __name__ == '__main__':unittest.main()
