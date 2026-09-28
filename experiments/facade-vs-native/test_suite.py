"""Offline tests for the eval suite. No desktop, no claude, no network, no sockets.

Each guard names the tempting wrong patch it fails.
"""
import argparse
import ast
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import metrics
import pages
import runner
import score
import server
import suite
from tasks import classify, load_tasks, select_tasks

HERE = Path(__file__).resolve().parent
TASKS = load_tasks()


def const_strings(path):
    """String constants in a source file, excluding docstrings (so prose can mention forbidden words)."""
    tree = ast.parse(Path(path).read_text())
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body and isinstance(node.body[0], ast.Expr) \
                and isinstance(getattr(node.body[0], 'value', None), ast.Constant):
            docs.add(id(node.body[0].value))
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def ev(action, ident, **kw):
    return dict(action=action, id=ident, **kw)


class Manifest(unittest.TestCase):
    def test_coverage_and_shape(self):
        # Wrong patch: ship fewer than the required 12 tasks or drop a required stress category.
        self.assertGreaterEqual(len(TASKS), 12)
        self.assertEqual(len(select_tasks(TASKS, suite='core')), 12)
        tags = {t for task in TASKS.values() for t in task['tags']}
        for need in ('list-select', 'table', 'confirm-dialog', 'canvas', 'form-fill', 'wizard', 'long-list', 'small-text', 'low-contrast',
                     'similar-labels', 'icon-only', 'region-disambiguation', 'duplicate-labels', 'dynamic-ui', 'destructive-decoy',
                     'stale-identity', 'flat-ax', 'nested-groups'):
            self.assertIn(need, tags)
        for task in TASKS.values():
            for key in ('id', 'tags', 'prompt', 'route', 'title', 'expected', 'forbidden', 'max_turns', 'timeout_s'):
                self.assertIn(key, task)
            self.assertTrue(task['expected'] and task['forbidden'])
            self.assertIn(task['route'].lstrip('/'), pages.PAGES)

    def test_every_page_renders_logs_and_matches_title(self):
        # Wrong patch: a page whose <title> differs from tasks.json (the agent is told the window title),
        # or a button that never calls log() (ground truth would be blind to it).
        for task in TASKS.values():
            status, ctype, body = server.handle_request(task['route'] + '?run=r1', '/nonexistent')
            page = body.decode()
            self.assertEqual(status, 200)
            self.assertIn('<title>%s</title>' % task['title'].format(run='r1'), page, task['id'])
            self.assertIn('log(', page)
            self.assertIn('r1', page)
            for tag in re.findall(r'<button[^>]*>', page):
                self.assertIn('onclick=', tag, task['id'])
            self.assertIn("task:'", page)

    def test_log_roundtrip_and_values(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'e.jsonl'
            server.handle_request('/log?run=x&task=form&action=submit&id=form&v_name=Ada', path)
            server.handle_request('/log?run=y&task=form&action=cancel&id=form', path)
            status, _, body = server.handle_request('/log?run=x', path)
            rows = json.loads(body)
            self.assertEqual([r['values'] for r in rows], [{'name': 'Ada'}])
            self.assertEqual(server.handle_request('/nope', path)[0], 404)

    def test_run_id_is_sanitised_in_pages(self):
        # Wrong patch: interpolate the raw run query into inline JS.
        _, _, body = server.handle_request("/form?run=a';alert(1);'", '/x')
        self.assertNotIn("alert(1);'", body.decode())

    def test_invoice_page_has_one_exact_match_and_near_duplicates(self):
        rows = pages.invoice_rows()
        self.assertEqual(len(rows), 100)
        exact = [r[0] for r in rows if r[1] == 'Northwind Traders' and r[2] == 1240.0]
        self.assertEqual(exact, [pages.INVOICE_TARGET])
        self.assertGreaterEqual(sum(r[2] == 1240.0 for r in rows), 3)
        self.assertGreaterEqual(sum(r[1].startswith('Northwind') for r in rows), 6)


class Classification(unittest.TestCase):
    def test_every_task_classifies_synthetic_logs(self):
        # Wrong patch: classify only on the terminal action, so a wrong-target click before/after a correct one is missed.
        for tid, task in TASKS.items():
            exp, wrong, partial = task['expected'], task['synthetic']['wrong'], task['synthetic']['partial']
            self.assertEqual(classify(task, exp), ('correct', 0), tid)
            self.assertEqual(classify(task, []), ('no-action', 0), tid)
            self.assertEqual(classify(task, [], timed_out=True), ('timeout', 0), tid)
            self.assertEqual(classify(task, wrong)[0], 'wrong', tid)
            self.assertGreaterEqual(classify(task, exp + wrong)[1], 1, tid)
            self.assertEqual(classify(task, exp + wrong)[0], 'wrong', tid)
            if partial:
                self.assertEqual(classify(task, partial), ('partial', 0), tid)
            else:
                self.assertEqual(len(exp), 1)

    def test_destructive_delete_is_always_wrong(self):
        # Wrong patch: score only the download event, letting "did the right thing then also deleted" pass.
        t = TASKS['destructive']
        good = [ev('press', 'export_open'), ev('download', 'csv')]
        self.assertEqual(classify(t, good)[0], 'correct')
        self.assertEqual(classify(t, good + [ev('delete', 'account')])[0], 'wrong')
        self.assertEqual(classify(t, [ev('press', 'export_open'), ev('delete', 'whatever')])[0], 'wrong')
        self.assertEqual(classify(t, [ev('press', 'export_open'), ev('download', 'json')])[0], 'wrong')
        self.assertEqual(classify(t, [ev('press', 'export_open')])[0], 'partial')

    def test_stale_identity_wrong_select_counts(self):
        # Wrong patch: only judge the final resolve, hiding a click on the swapped-in wrong row.
        t = TASKS['swap']
        self.assertEqual(classify(t, [ev('select', 't3'), ev('select', 't2'), ev('resolve', 't2')])[0], 'wrong')
        self.assertEqual(classify(t, [ev('select', 't2'), ev('resolve', 't2')])[0], 'correct')
        self.assertEqual(classify(t, [ev('resolve', 't2'), ev('select', 't2')])[0], 'partial')  # resolve before select does not count

    def test_form_values_exact(self):
        t = TASKS['form']
        vals = dict(t['expected'][0]['values'])
        self.assertEqual(classify(t, [ev('submit', 'form', values=vals)])[0], 'correct')
        self.assertEqual(classify(t, [ev('submit', 'form', values=dict(vals, postal='30301 '))])[0], 'wrong')
        self.assertEqual(classify(t, [ev('cancel', 'form')])[0], 'wrong')

    def test_wizard_requires_earlier_choice_in_finish(self):
        t = TASKS['wizard']
        self.assertEqual(classify(t, [ev('finish', 'team:monthly')])[0], 'wrong')
        self.assertEqual(classify(t, [ev('finish', 'team:annual')])[0], 'no-action')  # finish without the recorded choices is not enough

    def test_timeout_never_hides_wrong_or_correct(self):
        t = TASKS['booking']
        self.assertEqual(classify(t, [ev('book', 's07')], timed_out=True)[0], 'wrong')
        self.assertEqual(classify(t, [ev('book', 's10')], timed_out=True)[0], 'correct')


class PromptLint(unittest.TestCase):
    @staticmethod
    def leaks(task):
        prompt = task['prompt'].lower()
        intent = {x.lower() for x in task['intent_terms']}
        found = []
        words = list(task['decoy_labels'])
        words += [l for l in task['answer_labels'] + [e['id'] for e in task['expected']] if l.lower() not in intent]
        for w in words:
            if re.search(r'(?<![\w-])%s(?![\w-])' % re.escape(w.lower()), prompt):
                found.append(w)
        return found

    def test_no_prompt_names_the_answer_or_a_decoy(self):
        # Wrong patch: "help" the agent with the target id/label or list the decoys in the prompt.
        for tid, task in TASKS.items():
            self.assertEqual(self.leaks(task), [], tid)
            self.assertTrue(task['decoy_labels'], tid)

    def test_lint_catches_a_leaky_prompt(self):
        leaky = dict(TASKS['booking'], prompt='Book s10, not Dr. Morgan Reyesford.')
        self.assertEqual(sorted(self.leaks(leaky)), ['Dr. Morgan Reyesford', 's10'])

    def test_frame_adds_no_hints(self):
        frame = runner.PROMPT_FRAME.format(title='T', goal='G').lower()
        for task in TASKS.values():
            for w in task['decoy_labels'] + [e['id'] for e in task['expected']]:
                self.assertNotIn(w.lower(), frame)


class Metrics(unittest.TestCase):
    def test_wilson(self):
        lo, hi = metrics.wilson(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=3);self.assertAlmostEqual(hi, 0.7634, places=3)
        self.assertEqual(metrics.wilson(0, 0), (None, None))
        self.assertEqual(metrics.wilson(3, 3)[1], 1.0)
        self.assertLess(metrics.wilson(3, 3)[0], 0.5)  # n=3 all-correct is far from certain

    def test_median_iqr(self):
        s = metrics.median_iqr([1, 2, 3, 4, 100])
        self.assertEqual((s['median'], s['iqr']), (3, 2))

    def row(self, arm, task='booking', rep=0, model=metrics.HAIKU, outcome='correct', wrong=0, turns=10, wall=60, cost=1.0, tags=None):
        return {'arm': arm, 'task': task, 'rep': rep, 'model': model, 'outcome': outcome, 'wrong_clicks': wrong, 'turns': turns,
                'mcp_calls': turns, 'wall_s': wall, 'cost_usd': cost, 'tags': list(tags or ['dom']), 'invalid': False}

    def test_cost_per_success_divides_all_spend_by_successes(self):
        # Wrong patch: average cost of successful runs only, hiding what failures cost.
        rows = [self.row('native', cost=1.0), self.row('native', rep=1, cost=3.0, outcome='wrong', wrong=1)]
        s = metrics.summarize(rows)
        self.assertEqual(s['cost_per_success'], 4.0)
        self.assertIsNone(metrics.summarize([self.row('native', outcome='wrong', wrong=1)])['cost_per_success'])

    def test_invalid_runs_excluded(self):
        rows = [self.row('native'), dict(self.row('native', rep=1), invalid=True)]
        self.assertEqual(metrics.summarize(rows)['n'], 1)

    def test_paired_deltas(self):
        rows = [self.row('native', turns=5, cost=1.0), self.row('stack', turns=8, cost=1.5, outcome='wrong', wrong=2)]
        d = metrics.paired_deltas(rows, 'stack')[(metrics.HAIKU, 'booking')]
        self.assertEqual((d['pairs'], d['turns'], d['cost_usd'], d['success'], d['wrong_clicks']), (1, 3, 0.5, -1, 2))

    def synth(self, stack_turns, stack_success=1.0, runs=3, tasks=12):
        rows = []
        for t in range(tasks):
            for rep in range(runs):
                tags = ['canvas'] if t % 4 == 0 else ['dom']
                rows.append(self.row('native', task='t%d' % t, rep=rep, turns=10 + rep, tags=tags))
                ok = rep < round(stack_success * runs)
                rows.append(self.row('stack', task='t%d' % t, rep=rep, turns=stack_turns + rep, tags=tags, outcome='correct' if ok else 'wrong', wrong=0 if ok else 1))
        return rows

    def test_verdict_directional_when_stack_beats_turns(self):
        v = metrics.verdict(self.synth(stack_turns=5))['per_arm']['stack']
        self.assertEqual(v['claim'], 'directional')
        self.assertFalse(v['invalidated'])

    def test_verdict_no_when_worse_anywhere_beyond_band(self):
        # stack fewer turns but less successful: "worse on none" fails.
        v = metrics.verdict(self.synth(stack_turns=5, stack_success=0.34))['per_arm']['stack']
        self.assertEqual(v['claim'], 'no')

    def test_verdict_ties_inside_noise_band_do_not_count(self):
        # Wrong patch: call any nonzero difference a win.
        v = metrics.verdict(self.synth(stack_turns=10))['per_arm']['stack']
        self.assertEqual(v['claim'], 'no')
        self.assertTrue(v['invalidated'])

    def test_insufficient_data_blocks_every_rule(self):
        # Wrong patch: issue a verdict from 2 runs per cell or 5 tasks.
        v = metrics.verdict(self.synth(stack_turns=5, runs=2))['per_arm']['stack']
        self.assertEqual(v['claim'], 'insufficient-data')
        self.assertFalse(v['invalidated'])
        v = metrics.verdict(self.synth(stack_turns=5, tasks=5))['per_arm']['stack']
        self.assertEqual(v['claim'], 'insufficient-data')

    def test_pivot_triggers(self):
        rows = self.synth(stack_turns=10, stack_success=1.0)
        for r in rows:  # native fails a third of the time
            if r['arm'] == 'native' and r['rep'] == 0:
                r.update(outcome='wrong', wrong_clicks=1)
        v = metrics.verdict(rows)['per_arm']['stack']
        self.assertTrue(v['large_cheap_driver_lift'])
        self.assertIn('server-side agent', v['action'])
        none = metrics.verdict(self.synth(stack_turns=10))['per_arm']['stack']
        self.assertTrue(none['no_advantage_anywhere'])
        self.assertIn('salvage', none['action'])

    def test_preregistration_matches_code(self):
        # Wrong patch: tune a threshold in metrics.py after seeing results without amending the preregistration.
        doc = ' '.join((HERE / 'PREREGISTRATION.md').read_text().split())
        for needle in ('[%.2f, %.2f]' % (metrics.NOISE_FLOOR, metrics.NOISE_CAP), 'b = %.2f' % metrics.NOISE_DEFAULT,
                       'absolute %.2f' % metrics.RATE_BAND, 'at least %.2f higher' % metrics.LARGE_LIFT_SUCCESS,
                       'at least %d%% lower' % round(metrics.LARGE_LIFT_COST * 100), 'at least %d tasks each have at least %d valid runs' % (metrics.MIN_TASKS, metrics.MIN_RUNS_PER_CELL)):
            self.assertIn(needle, doc)
        self.assertIn('matches or beats the stack on every metric across the suite', doc)


class Plan(unittest.TestCase):
    def plan(self, suite_name='core', runs=3, arms=('native', 'stack', 'stack-advanced'), models=('haiku', 'sonnet'), seed=1):
        ids = select_tasks(TASKS, suite=suite_name)
        return suite.build_plan(TASKS, ids, list(arms), suite.resolve_models(models), runs, seed)

    def test_full_run_arithmetic(self):
        # 12 tasks x 3 runs x 3 arms x 2 models
        e = suite.estimate(self.plan())
        self.assertEqual(e['runs'], 216)
        self.assertAlmostEqual(e['minutes_mid'], round(216 * 94 / 60, 1))
        self.assertEqual((e['usd_lo'], e['usd_mid'], e['usd_hi']), (172.8, 259.2, 345.6))

    def test_small_run_arithmetic(self):
        p = suite.build_plan(TASKS, select_tasks(TASKS, suite='small'), ['native', 'stack'], suite.resolve_models(['sonnet']), 1)
        self.assertEqual(len(p), 6)
        self.assertEqual(suite.estimate(p)['usd_mid'], 7.2)

    def test_blocks_hold_every_arm_and_seed_fixes_order(self):
        a, b = self.plan(seed=5), self.plan(seed=5)
        self.assertEqual([x['run_id'] for x in a], [x['run_id'] for x in b])
        self.assertNotEqual([x['run_id'] for x in a], [x['run_id'] for x in self.plan(seed=6)])
        self.assertEqual(len({x['run_id'] for x in a}), len(a))
        first = [x['arm'] for x in a[:3]]
        self.assertEqual(sorted(first), ['native', 'stack', 'stack-advanced'])
        self.assertGreater(len({tuple(x['arm'] for x in a[i:i + 3]) for i in range(0, len(a), 3)}), 1)  # arms are shuffled, not fixed-order

    def test_plan_cli_prints(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(suite.main(['plan', '--suite', 'small']), 0)
        self.assertIn('TOTAL', out.getvalue())


class Safety(unittest.TestCase):
    def test_live_run_refuses_without_consent(self):
        # Wrong patch: default consent to True or only warn.
        with mock.patch.object(runner, 'open_page') as op, mock.patch.object(runner, 'run_agent') as ra:
            with self.assertRaises(SystemExit) as cm:
                suite.main(['run', '--max-total-minutes', '10'])
            self.assertIn('--i-have-consent', str(cm.exception))
            op.assert_not_called();ra.assert_not_called()
            with self.assertRaises(SystemExit) as cm:
                suite.main(['run', '--i-have-consent'])
            self.assertIn('--max-total-minutes', str(cm.exception))
            op.assert_not_called()

    def test_legacy_runner_refuses_without_consent(self):
        with mock.patch('sys.argv', ['runner.py']), mock.patch.object(runner, 'open_page') as op:
            with self.assertRaises(SystemExit):
                runner.main()
            op.assert_not_called()

    def test_window_handling_is_by_id_without_activate_or_open(self):
        # Wrong patch: `open <url>` (adds a tab to the user's window), `activate`, or closing by title.
        for name in ('runner.py', 'suite.py'):
            strings = const_strings(HERE / name)
            for s in strings:
                self.assertNotIn('activate', s.lower(), name)
                self.assertNotEqual(s.strip().split(' ')[0], 'open', name)
                if 'close' in s.lower():  # closing by title/name could hit a user window
                    self.assertNotIn('whose', s, name);self.assertNotIn('title', s, name)
            if name == 'runner.py':
                self.assertIn('id of (make new window)', strings)
                self.assertTrue(any('close window id' in s for s in strings))
                self.assertFalse(any('close (every window' in s or 'close window 1' in s for s in strings))
        src = (HERE / 'runner.py').read_text()
        self.assertNotRegex(src, r"\['open'")
        self.assertNotIn('subprocess.run([\'open\'', src)

    def test_agent_isolation_flags(self):
        # Wrong patch: run the agent inside the repo or allow file/shell tools.
        src = (HERE / 'runner.py').read_text()
        self.assertIn('cwd=tempfile.mkdtemp', src)
        self.assertIn("'--strict-mcp-config'", src)
        self.assertIn("'--max-turns'", src)
        for arm, deny in runner.DISALLOWED_TOOLS.items():
            for tool in ('Bash', 'Read', 'Write', 'Edit'):
                self.assertIn(tool, deny, arm)
        self.assertIn('Skill', runner.DISALLOWED_TOOLS['native'])
        self.assertNotIn('Skill', runner.DISALLOWED_TOOLS['native-skill'])

    def test_server_is_loopback_only(self):
        # Wrong patch: bind '' or 0.0.0.0 so the fixtures leave the machine.
        strings = const_strings(HERE / 'server.py')
        self.assertIn('127.0.0.1', strings)
        self.assertNotIn('0.0.0.0', strings)

    def test_stack_advanced_sets_env_and_arms_differ(self):
        with tempfile.TemporaryDirectory() as d:
            adv = json.loads(runner.mcp_config('stack-advanced', d).read_text())['mcpServers']['cua-task']
            base = json.loads(runner.mcp_config('stack', d).read_text())['mcpServers']['cua-task']
            nat = json.loads(runner.mcp_config('native', d).read_text())['mcpServers']
        self.assertEqual(adv['env'], {'CUA_TASK_ADVANCED': '1'})
        self.assertNotIn('env', base)
        self.assertEqual(list(nat), ['cua-driver'])
        self.assertTrue(Path(adv['args'][0]).is_absolute())

    def live_args(self, **kw):
        return argparse.Namespace(**dict(dict(seed=1, dry_run=False, max_total_minutes=60, agent_timeout=None, max_turns=None), **kw))

    def test_ctrl_c_closes_only_created_windows_and_keeps_manifest_consistent(self):
        # Wrong patch: let KeyboardInterrupt skip close_window or leave a half-written manifest.
        plan = suite.build_plan(TASKS, ['booking'], ['native', 'stack'], [suite.MODELS['sonnet']], 2, 1)
        opened, closed = [], []

        def open_page(url):
            opened.append(100 + len(opened));return opened[-1]

        def run_agent(*a, **k):
            if len(opened) == 2:
                raise KeyboardInterrupt
            return {'wall_s': 1.0, 'returncode': 0}

        with tempfile.TemporaryDirectory() as d, mock.patch.object(runner, 'open_page', open_page), \
                mock.patch.object(runner, 'run_agent', run_agent), mock.patch.object(runner, 'close_window', closed.append), \
                mock.patch.object(suite.time, 'sleep'), redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            manifest, code = suite.execute(plan, TASKS, self.live_args(), d, Path(d) / 'e.jsonl', 'http://127.0.0.1:1')
            on_disk = json.loads((Path(d) / 'manifest.json').read_text())
        self.assertEqual(code, 130)
        self.assertEqual(closed, opened)
        self.assertEqual(on_disk['interrupted'], True)
        self.assertEqual(len(on_disk['runs']), 1)
        self.assertEqual(on_disk['windows_opened'], opened)

    def test_wall_budget_stops_before_overrun(self):
        plan = suite.build_plan(TASKS, ['booking'], ['native'], [suite.MODELS['sonnet']], 1, 1)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(runner, 'open_page') as op:
            manifest, code = suite.execute(plan, TASKS, self.live_args(max_total_minutes=0.5), d, Path(d) / 'e', 'http://127.0.0.1:1')
        self.assertEqual((manifest['stopped'], len(manifest['runs']), code), ('max-total-minutes', 0, 0))
        op.assert_not_called()

    def test_runs_are_sequential(self):
        # Wrong patch: parallelise agents (two agents fight over one desktop). No threads/pools in the executor.
        src = (HERE / 'suite.py').read_text()
        for bad in ('ThreadPoolExecutor', 'multiprocessing', 'asyncio', 'Popen'):
            self.assertNotIn(bad, src)


class DryRun(unittest.TestCase):
    def test_end_to_end_without_desktop(self):
        # Wrong patch: dry-run that quietly shells out to Chrome or claude.
        with tempfile.TemporaryDirectory() as d, mock.patch.object(runner, 'open_page', side_effect=AssertionError('desktop')), \
                mock.patch.object(runner, 'run_agent', side_effect=AssertionError('claude')), \
                mock.patch('subprocess.run', side_effect=AssertionError('subprocess')):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(suite.main(['run', '--dry-run', '--suite', 'core', '--arms', 'native', 'stack', 'stack-advanced',
                                             '--models', 'haiku', 'sonnet', '--runs', '3', '--out-dir', d]), 0)
            manifest = json.loads((Path(d) / 'manifest.json').read_text())
            self.assertEqual(len(manifest['runs']), 216)
            self.assertTrue(manifest['dry_run'] and all(r['synthetic'] for r in manifest['runs']))
            rows = suite.score_manifest(manifest, Path(d) / 'events.jsonl', TASKS)
            self.assertEqual(len(rows), 216)
            self.assertTrue({r['outcome'] for r in rows} <= {'correct', 'wrong', 'partial', 'no-action', 'timeout'})
            self.assertIn('correct', {r['outcome'] for r in rows})
            for r in rows:
                self.assertGreater(r['turns'], 0)
                self.assertEqual(r['mcp_calls'], r['turns'])
                self.assertIsNotNone(r['cost_usd'])
                self.assertIsNotNone(r['tokens']['cache_read'])
            for cmd in ('score', 'report'):
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(suite.main([cmd, '--manifest', str(Path(d) / 'manifest.json'), '--events', str(Path(d) / 'events.jsonl')]), 0)
            self.assertIn('SYNTHETIC', out.getvalue())
            self.assertIn('Preregistered verdict', out.getvalue())
            self.assertIn('Wilson', out.getvalue())
            self.assertIn('n is small', out.getvalue())

    def test_synthetic_wrong_runs_score_wrong(self):
        with tempfile.TemporaryDirectory() as d:
            plan = suite.build_plan(TASKS, list(TASKS), ['native'], [suite.MODELS['haiku']], 4, 3)
            args = argparse.Namespace(seed=3, dry_run=True, agent_timeout=None, max_turns=None)
            with redirect_stdout(io.StringIO()):
                manifest, _ = suite.execute(plan, TASKS, args, d, Path(d) / 'e.jsonl')
            rows = suite.score_manifest(manifest, Path(d) / 'e.jsonl', TASKS)
        self.assertTrue(any(r['outcome'] == 'wrong' and r['wrong_clicks'] >= 1 for r in rows))

    def test_turns_count_message_ids_not_content_blocks(self):
        # Wrong patch: count every assistant event (stream-json emits one per content block).
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 't.jsonl'
            lines = [{'type': 'assistant', 'message': {'id': 'm1', 'content': [{'type': 'text', 'text': 'a'}]}},
                     {'type': 'assistant', 'message': {'id': 'm1', 'content': [{'type': 'tool_use', 'name': 'mcp__x__y'}]}},
                     {'type': 'assistant', 'message': {'id': 'm2', 'content': []}}]
            p.write_text('\n'.join(json.dumps(x) for x in lines))
            self.assertEqual(score.scan_transcript(str(p))['turns'], 2)


if __name__ == '__main__':
    unittest.main()
