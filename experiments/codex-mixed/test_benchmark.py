"""Adversarial checks for the experiment, without starting agents or devices."""
import json
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import runner
import audit_traces
import rank_losses
import post_runner
import summarize


class MeasurementTests(unittest.TestCase):
    def test_protocol_violation_has_precedence_over_actual_permission_block(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            (source / 'metrics.jsonl').write_text(json.dumps({'run_id':'probe','arm':'native','task':'ios','outcome':'no-action'})+'\n')
            (source / 'probe.jsonl').write_text('{}\n')
            trace = {'calls':[], 'usage':None, 'violations':['extra command']}
            with patch.object(runner, 'parse', return_value=trace), patch.object(audit_traces, 'permission_blocked', return_value=True):
                row = summarize.export(source)[0]
            self.assertEqual(row['outcome'], 'protocol-violation')
            self.assertTrue(row['permission_blocked'])

    def test_post_runner_changes_only_the_oh_server_argument(self):
        command = runner.argv('oh', 'web', 'UNCHANGED PROMPT')
        changed = post_runner.with_runtime(command, Path('/candidate'))
        pairs = [(before, after) for before, after in zip(command, changed) if before != after]
        self.assertEqual(len(command), len(changed))
        self.assertEqual(len(pairs), 1)
        self.assertTrue(pairs[0][0].startswith('mcp_servers.computer-use-oh.args='))
        self.assertEqual(command[-1], changed[-1])

    def test_cache_is_a_subset_and_missing_usage_is_not_zero(self):
        actual = runner.usage_metrics({"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 12, "reasoning_output_tokens": 7})
        self.assertEqual(actual["total_tokens"], 112)
        self.assertEqual(actual["uncached_input_tokens"], 20)
        self.assertIsNone(runner.usage_metrics(None)["total_tokens"])

    def test_command_substring_does_not_authorize_shell_shortcuts(self):
        argv = ["/python", "/fixture dir/tui.py", "/tmp/result.json"]
        self.assertTrue(runner.exact_fixture_command(shlex.join(argv), argv))
        self.assertTrue(runner.exact_fixture_command(shlex.join(["/bin/zsh", "-c", shlex.join(argv)]), argv))
        self.assertFalse(runner.exact_fixture_command(shlex.join(argv) + "; cat /tmp/result.json", argv))
        self.assertFalse(runner.exact_fixture_command("cat " + shlex.join(argv), argv))

    def test_pty_aggregate_is_not_a_tool_call_count(self):
        calls = [{"tool": "command_execution"}, {"server": "cua_repl", "tool": "js"}]
        m = runner.call_metrics(calls, "native", "mixed")
        self.assertEqual(m["observed_tool_items"], 2)
        self.assertEqual(m["mcp_calls"], 1)
        self.assertIsNone(m["tool_calls"])

    def test_receipt_alone_does_not_prove_required_sequence(self):
        self.assertFalse(runner.expected_tui({"receipt": "BIRCH-3-OK"}))
        data = {"receipt": "BIRCH-3-OK", "events": [
            {"action": "select", "product": "Birch"},
            {"action": "quantity", "value": "3"},
            {"action": "confirm", "product": "Birch", "quantity": "3"},
        ]}
        self.assertTrue(runner.expected_tui(data))
        data["events"].append(data["events"][-1])
        self.assertFalse(runner.expected_tui(data))

    def test_wrong_values_and_double_confirm_do_not_pass_dispatch(self):
        events = [{"action": a, "project": "Aurora", "quantity": "3", "included": True} for a in ("review", "confirm")]
        self.assertTrue(runner.expected_dispatch({"events": events}))
        self.assertFalse(runner.expected_dispatch({"events": events + [events[-1]]}))
        self.assertFalse(runner.expected_dispatch({"events": [{**e, "quantity": "4"} for e in events]}))

    def test_trace_keeps_failures_and_checks_oh_launches(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            event = {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "computer-use-oh", "tool": "do", "arguments": {"steps": [{"do": "launch", "argv": ["cat", "result.json"]}]}}}
            path.write_text("non-JSON startup warning\n" + json.dumps(event) + "\n" + json.dumps({"type": "turn.failed", "error": {"message": "timed out"}}))
            trace = runner.parse(path, "oh", "terminal", ["python", "tui.py", "result.json"])
            self.assertIn("non_fixture_launch", trace["violations"])
            self.assertIsNone(trace["usage"])
            self.assertTrue(trace["errors"])

    def test_mobile_app_launch_is_not_a_terminal_fixture_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.jsonl'
            event = {'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'server': 'computer-use-oh', 'tool': 'do',
                     'arguments': {'device': runner.IOS, 'steps': [{'do': 'launch', 'app': 'Settings', 'expect': None}]}}}
            path.write_text(json.dumps(event))
            self.assertEqual(runner.parse(path, 'oh', 'ios', None)['violations'], [])
            event['item']['arguments']['steps'][0]['argv'] = ['cat', 'result.json']
            path.write_text(json.dumps(event))
            self.assertIn('non_fixture_launch', runner.parse(path, 'oh', 'ios', None)['violations'])

    def test_native_repl_is_not_permission_for_file_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            event = {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "cua_repl", "tool": "js", "arguments": {"code": "var fs = await import('node:fs/promises'); await fs.readFile('/skills/SKILL.md', 'utf8')"}}}
            path.write_text(json.dumps(event))
            self.assertIn("native_out_of_contract_node_io", runner.parse(path, "native", "web", None)["violations"])

    def test_mobile_version_claim_cannot_replace_independent_screen(self):
        about = {"status": "ok", "text": ["About", "iOS Version", "26.5"]}
        self.assertEqual(runner.mobile_result("ios", "dark", "26.5", "iOS 26.5", about)[0], "correct")
        for observed in ({"status": "ok", "text": ["Home"]}, {**about, "status": "refused"}):
            self.assertNotEqual(runner.mobile_result("ios", "dark", "26.5", "iOS 26.5", observed)[0], "correct")
        self.assertNotEqual(runner.mobile_result("ios", "light", "26.5", "iOS 26.5", about)[0], "correct")
        self.assertNotEqual(runner.mobile_result("ios", "dark", "26.5", "iOS 126.5", about)[0], "correct")

    def test_failed_mobile_reset_cannot_inherit_prior_dark_success(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "run", return_value=SimpleNamespace(stdout="Night mode: yes")):
            with self.assertRaisesRegex(RuntimeError, "baseline"):
                runner.prepare("android", "test", Path(directory))


class LossRankingTests(unittest.TestCase):
    def test_permission_failure_is_not_a_comparable_speed_win(self):
        rows = [{'task': 'ios', 'arm': arm, 'outcome': outcome, 'wall_s': wall, 'total_tokens': 10}
                for arm, outcome, wall in [('native', 'permission-blocked', 1), ('oh', 'correct', 100)]]
        loss = rank_losses.rank(rows, 1)[0]
        self.assertEqual(loss['audit_reasons'], ['comparison_unavailable'])
        self.assertIsNone(loss['wall_excess_s'])

    def test_quick_failure_and_missing_usage_remain_audit_cases(self):
        rows = [{'task': 'vnc', 'arm': arm, 'outcome': outcome, 'wall_s': wall, 'total_tokens': tokens}
                for arm, outcome, wall, tokens in [('native', 'correct', 100, 50), ('oh', 'refused', 1, None)]]
        loss = rank_losses.rank(rows, 1)[0]
        self.assertIn('completion', loss['audit_reasons'])
        self.assertIn('usage_unavailable', loss['audit_reasons'])
        self.assertIsNone(loss['token_excess'])
        self.assertEqual(rank_losses.rank(rows), [], 'unfinished cells cannot determine a ranking')


class TraceAuditTests(unittest.TestCase):
    def test_only_matching_started_completed_events_are_timed(self):
        # A completion seen after observer startup must not inherit fabricated time.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'timing.jsonl'
            events = [
                {'run_id': 'a', 'item_id': '1', 'event': 'item.completed', 'observed_ns': 20},
                {'run_id': 'a', 'item_id': '2', 'event': 'item.started', 'observed_ns': 100},
                {'run_id': 'b', 'item_id': '2', 'event': 'item.completed', 'observed_ns': 500},
                {'run_id': 'a', 'item_id': '2', 'event': 'item.completed', 'observed_ns': 1000000100},
            ]
            path.write_text(''.join(json.dumps(e) + '\n' for e in events))
            self.assertEqual(audit_traces.durations(path), {('a', '2'): 1.0})

    def test_non_json_tool_exception_is_not_lost_from_the_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.jsonl'
            event = {'type': 'item.completed', 'item': {'id': '1', 'type': 'mcp_tool_call', 'tool': 'look',
                     'result': {'content': [{'type': 'text', 'text': "Error executing tool look: 'pid'"}]}}}
            path.write_text(json.dumps(event))
            row = audit_traces.calls(path, {})[0]
            self.assertEqual(row['reason'], 'missing_pid')
            self.assertTrue(row['mcp_error'])

    def test_permission_block_requires_tool_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.jsonl'
            agent = {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Computer Use was not approved to use Example'}}
            path.write_text(json.dumps(agent))
            self.assertFalse(audit_traces.permission_blocked(path))
            refusal = {'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'result': {'isError': True, 'content': [
                {'type': 'text', 'text': 'Computer Use was not approved to use Example'}]}}}
            path.write_text(json.dumps(refusal))
            self.assertTrue(audit_traces.permission_blocked(path))

    def test_audit_keeps_failure_evidence_without_page_content_or_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run.jsonl'
            result = {'status': 'stopped', 'reason': 'delivery_unverified',
                      'text': ['PRIVATE_PAGE_SENTINEL'], 'steps': [{'do': 'type', 'status': 'stopped', 'ms': 20}]}
            item = {'id': '1', 'type': 'mcp_tool_call', 'tool': 'do', 'server': 'oh',
                    'arguments': {'steps': [{'do': 'type', 'text': 'PRIVATE_INPUT_SENTINEL'}]},
                    'result': {'content': [{'type': 'text', 'text': json.dumps(result)}]}}
            path.write_text(json.dumps({'type': 'item.completed', 'item': item}))
            rows = audit_traces.calls(path, {})
            self.assertEqual(rows[0]['reason'], 'delivery_unverified')
            self.assertIsNone(rows[0]['observed_call_s'])
            self.assertNotIn('PRIVATE_', json.dumps(rows))


class TargetQualification(unittest.TestCase):
    def test_missing_inventory_requires_tool_evidence_not_agent_claim(self):
        import audit_traces
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'trace.jsonl'
            def tool(text):
                return {'type':'item.completed','item':{'type':'mcp_tool_call','result':{'content':[{'type':'text','text':text}]}}}
            invalid = tool('Invalid app: OH Benchmark')
            missing = tool(json.dumps({'apps':[{'displayName':'Other App'}]}))
            present = tool(json.dumps({'apps':[{'displayName':'OH Benchmark'}]}))
            path.write_text('\n'.join(json.dumps(x) for x in [invalid,missing]))
            self.assertTrue(audit_traces.target_inventory_blocked(path,'OH Benchmark'))
            path.write_text('\n'.join(json.dumps(x) for x in [invalid,present]))
            self.assertFalse(audit_traces.target_inventory_blocked(path,'OH Benchmark'))
            path.write_text(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'Invalid app: OH Benchmark'}}))
            self.assertFalse(audit_traces.target_inventory_blocked(path,'OH Benchmark'))


if __name__ == "__main__":
    unittest.main()
