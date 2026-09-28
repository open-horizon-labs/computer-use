"""Offline test for score.py's live-harness guard: synthetic transcripts, no runs, no desktop."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import score


def call(name, uid='t1'):
    return {'type': 'tool_use', 'id': uid, 'name': name, 'input': {}}


def transcript(*blocks_per_turn):
    lines = []
    for blocks in blocks_per_turn:
        lines.append({'type': 'assistant', 'message': {'content': blocks}})
        lines.append({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'content': 'x'}]}})
    lines.append({'type': 'result', 'total_cost_usd': 0.1, 'duration_ms': 1000, 'result': 'done'})
    return '\n'.join(json.dumps(line) for line in lines) + '\n'


class ScoreGuards(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def write(self, name, text):
        path = self.dir / name;path.write_text(text);return str(path)

    def test_counts_only_mcp_tool_use_blocks_in_assistant_events(self):
        # Wrong patches: count every tool_use (Bash/Read are not MCP hops), count tool_result echoes, or count the result event.
        text = transcript([call('mcp__cua-task__cua_do'), call('Bash')], [call('mcp__cua-task__cua_finish')], [{'type': 'text', 'text': 'mcp__x'}])
        self.assertEqual(score.count_llm_visible_calls(self.write('t.jsonl', text)), 2)

    def test_missing_transcript_counts_zero(self):
        self.assertEqual(score.count_llm_visible_calls(str(self.dir / 'nope.jsonl')), 0)

    def test_budget_for_reads_the_repo_budget(self):
        self.assertEqual(score.budget_for('booking'), json.loads(score.BUDGET_PATH.read_text())['live_task_budgets']['booking']['max_llm_visible_calls']['value'])
        self.assertIsNone(score.budget_for('unknown-task'))

    def manifest(self, facade_calls, native_calls):
        rows = []
        for arm, n in (('facade', facade_calls), ('native', native_calls)):
            path = self.write(arm + '.jsonl', transcript(*[[call('mcp__x__tool')] for _ in range(n)]))
            rows.append({'arm': arm, 'task': 'booking', 'run_id': arm + '-booking-1', 'transcript': path, 'wall_s': 1})
        return self.write('manifest.json', json.dumps(rows)), self.write('events.jsonl', '')

    def run_score(self, manifest, events, *flags):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = score.main(['--manifest', manifest, '--events', events, *flags])
        return code, [json.loads(line) for line in out.getvalue().splitlines()], err.getvalue()

    def test_over_budget_is_reported_and_only_fails_with_the_flag(self):
        # Wrong patch: print the calls but never compare them to the budget.
        manifest, events = self.manifest(facade_calls=9, native_calls=5)
        code, rows, err = self.run_score(manifest, events)
        self.assertEqual(code, 0);self.assertTrue(rows[0]['over_budget']);self.assertEqual(rows[0]['llm_visible_calls'], 9)
        self.assertIn('OVER BUDGET', err)
        code, _, _ = self.run_score(manifest, events, '--fail-over-budget')
        self.assertEqual(code, 1)

    def test_within_budget_passes_the_flag(self):
        manifest, events = self.manifest(facade_calls=2, native_calls=5)
        code, rows, _ = self.run_score(manifest, events, '--fail-over-budget')
        self.assertEqual(code, 0);self.assertFalse(rows[0]['over_budget'])

    def test_native_arm_is_never_over_the_facade_budget(self):
        manifest, events = self.manifest(facade_calls=1, native_calls=50)
        _, rows, _ = self.run_score(manifest, events, '--fail-over-budget')
        native = next(r for r in rows if r.get('arm') == 'native')
        self.assertFalse(native['over_budget']);self.assertIsNone(native['call_budget'])

    def test_headline_ratio_of_calls_and_turns_versus_native(self):
        manifest, events = self.manifest(facade_calls=1, native_calls=5)
        _, rows, _ = self.run_score(manifest, events)
        head = next(r['headline'] for r in rows if 'headline' in r)
        self.assertEqual((head['task'], head['llm_visible_calls_ratio'], head['turns_ratio']), ('booking', 0.2, 0.2))

    def test_no_headline_when_only_one_arm_is_present(self):
        manifest, events = self.manifest(facade_calls=1, native_calls=5)
        only = json.loads(Path(manifest).read_text())[:1]
        path = self.write('one.json', json.dumps(only))
        _, rows, _ = self.run_score(path, events)
        self.assertFalse(any('headline' in r for r in rows))


if __name__ == '__main__':
    unittest.main()
