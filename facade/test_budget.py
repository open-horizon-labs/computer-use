"""Architectural guardrails: the default path stays ONE LLM-visible call (CALL_BUDGET.json, CE-FACADE-003).

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

    def test_cua_do_first_and_every_other_tool_is_advanced(self):
        tools = cb.tool_surface(SERVER_SOURCE)
        self.assertEqual(tools[0][0], 'cua_do');self.assertEqual(BUDGET['default_path_tools']['value'], ['cua_do'])
        self.assertTrue(all(doc.startswith('Advanced') for _, doc in tools[1:]))
        self.assertLessEqual(len(tools), BUDGET['max_tool_count']['value'])

    def test_a_new_unmarked_tool_fails(self):
        # Wrong patch: add a mandatory read/choose/verify tool to the default path.
        added = SERVER_SOURCE.replace('@mcp.tool(annotations=READ)\ndef cua_trace', '@mcp.tool(annotations=READ)\ndef cua_confirm() -> dict:\n    """Confirm the last action."""\n    return {}\n\n@mcp.tool(annotations=READ)\ndef cua_trace')
        self.assertNotEqual(added, SERVER_SOURCE)
        found = cb.surface_violations(added)
        self.assertTrue(any('cua_confirm' in v and 'Advanced' in v for v in found), found)

    def test_registering_another_tool_before_cua_do_fails(self):
        moved = SERVER_SOURCE.replace('@mcp.tool(annotations=ACT)\ndef cua_do', '@mcp.tool(annotations=READ)\ndef cua_pre() -> dict:\n    """Advanced: x."""\n    return {}\n\n@mcp.tool(annotations=ACT)\ndef cua_do', 1)
        self.assertTrue(any('registered first' in v for v in cb.surface_violations(moved)))

    def test_too_many_tools_fails(self):
        extra = ''.join('\n@mcp.tool(annotations=READ)\ndef cua_extra%d() -> dict:\n    """Advanced: x."""\n    return {}\n' % i for i in range(3))
        self.assertTrue(any('max_tool_count' in v for v in cb.surface_violations(SERVER_SOURCE + extra)))

    def test_advanced_marker_on_the_default_tool_fails(self):
        marked = SERVER_SOURCE.replace('"""Default path.', '"""Advanced: Default path.')
        self.assertTrue(any('marked Advanced' in v for v in cb.surface_violations(marked)))

    @unittest.skipUnless(HAVE_SERVER, 'needs mcp')
    def test_list_tools_agrees_with_the_source(self):
        import asyncio
        listed = [t.name for t in asyncio.run(server.mcp.list_tools())]
        self.assertEqual(listed, [name for name, _ in cb.tool_surface(SERVER_SOURCE)])


class SkillLint(unittest.TestCase):
    TEXT = cb.SKILL.read_text()

    def test_default_workflow_names_only_cua_do_first(self):
        self.assertEqual(cb.skill_violations(self.TEXT), [])
        section = cb.default_workflow_section(self.TEXT)
        self.assertLessEqual(len(set(__import__('re').findall(r'cua_[a-z_]+', section))), 2)

    def test_reintroducing_the_chain_in_prose_fails(self):
        # Wrong patch: instruct observe -> read -> choose -> act -> verify as the normal path.
        chain = self.TEXT.replace('## Advanced primitives', 'Then call `cua_observe`, `cua_read`, `cua_choose`, `cua_act` and `cua_verify` in turn.\n\n## Advanced primitives', 1)
        self.assertTrue(any('chain' in v or 'names' in v for v in cb.skill_violations(chain)))

    def test_leading_with_a_primitive_fails(self):
        led = self.TEXT.replace('Call `cua_do` once.', 'Call `cua_windows`, then `cua_do`.', 1)
        self.assertTrue(any('first' in v for v in cb.skill_violations(led)))

    def test_missing_section_fails(self):
        self.assertTrue(cb.skill_violations(self.TEXT.replace('## Default workflow', '## Something else')))


class Measure(unittest.TestCase):
    def test_measure_of_a_failing_run_is_reported(self):
        good = {'calls': 1, 'reader': 1, 'chooser': 0, 'max_bytes': 900, 'status': 'done', 'tools': ['cua_do']}
        limits = BUDGET['scenarios']['booking_list']
        self.assertEqual(cb.over_budget(good, limits), [])
        self.assertTrue(cb.over_budget({**good, 'calls': 9}, limits))  # the measured pre-cua_do behavior
        self.assertTrue(cb.over_budget({**good, 'reader': 2}, limits))  # a second reader call
        self.assertTrue(cb.over_budget({**good, 'chooser': 1}, limits))  # the chooser for a grounded singleton

    def test_table_flags_oversized_responses_and_primitive_use(self):
        base = {n: {'calls': 1, 'reader': 0, 'chooser': 0, 'max_bytes': 100, 'status': 'done', 'tools': ['cua_do']} for n in BUDGET['scenarios']}
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
        self.assertEqual(m['status'], 'done', m)
        self.assertEqual(cb.over_budget(m, limits), [], m)
        self.assertEqual(set(m['tools']), set(BUDGET['default_path_tools']['value']))
        self.assertLessEqual(m['max_bytes'], BUDGET['max_response_bytes']['value'])
        return m

    def test_booking_list_is_one_call_one_read_no_chooser(self):
        m = self.scenario('booking_list');self.assertEqual((m['calls'], m['reader'], m['chooser']), (1, 1, 0))

    def test_orders_confirm_stays_within_two_calls(self):
        m = self.scenario('orders_confirm');self.assertLessEqual(m['reader'], 2);self.assertLessEqual(m['chooser'], 1)

    def test_canvas_regions_stays_within_two_calls(self):
        m = self.scenario('canvas_regions');self.assertEqual(m['reader'], 0)

    def test_large_page_response_is_bounded(self):
        m = self.scenario('large_page_400');self.assertLess(m['max_bytes'], BUDGET['max_response_bytes']['value'])

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
        # Wrong patch: a harness that counts only cua_do would hide a hand-driven chain.
        import asyncio
        from core import Facade
        from test_core import FakeVision
        import test_do as fx
        server.facade = Facade(fx.FlatDriver(), reader_factory=fx.LineReader, generic_factory=fx.NamedChooser, visual_factory=FakeVision, sleep=lambda s: None)
        names = []
        def call(name, **kw):
            names.append(name);return json.loads(cb.result_text(asyncio.run(server.mcp.call_tool(name, kw))))
        obs = call('cua_observe', pid=1, window_id=2)
        call('cua_read', snapshot=obs['snapshot'], task='t', fields={'provider': {'description': 'p'}}, record_ids=['e5'])
        self.assertEqual(len(names), 2)
        self.assertEqual(cb.over_budget({'calls': 5, 'reader': 1, 'chooser': 1}, BUDGET['scenarios']['booking_list'])[0][:7], 'calls 5')


if __name__ == '__main__':unittest.main()
