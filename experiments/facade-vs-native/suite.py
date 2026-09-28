"""Eval suite CLI: plan | run | score | report.

`plan`, `score`, `report` and `run --dry-run` are fully offline and never touch the desktop.
`run` without --dry-run OPERATES THE DESKTOP (dedicated Chrome windows + `claude -p` agents) and
refuses to start without --i-have-consent (explicit user consent obtained in chat) and
--max-total-minutes. See README.md ("How to run the suite") and PREREGISTRATION.md.
"""
import argparse
import hashlib
import json
import os
import random
import sys
import tempfile
import threading
import time
from pathlib import Path

import metrics
import runner
import score
from tasks import MODELS, classify, load_tasks, select_tasks

HERE = Path(__file__).resolve().parent
DEFAULT_ARMS = ['native', 'stack']
SEED = 20260928
# Measured priors (2026-09 live A/B): per-run wall seconds and API-equivalent USD. Not per-model:
# Haiku is likely cheaper and faster, so these are conservative for it.
PRIOR_S = (40, 90, 140)
PRIOR_USD = (0.8, 1.2, 1.6)
OVERHEAD_S = 4  # window open/settle/close per run


def resolve_models(names):
    return [MODELS.get(n, n) for n in names]


def model_short(model):
    for short, full in MODELS.items():
        if full == model:
            return short
    return model.replace('/', '_')


def build_plan(tasks, task_ids, arms, models, runs, seed=SEED):
    """Cross product; blocks (task, model, rep) and arms within a block shuffled with a fixed seed."""
    rng = random.Random(seed)
    blocks = [(t, m, r) for t in task_ids for m in models for r in range(runs)]
    rng.shuffle(blocks)
    plan = []
    for task, model, rep in blocks:
        order = list(arms)
        rng.shuffle(order)
        for arm in order:
            plan.append({'arm': arm, 'task': task, 'model': model, 'rep': rep, 'seed': seed,
                         'run_id': f'{task}.{arm}.{model_short(model)}.r{rep}.s{seed}',
                         'max_turns': tasks[task]['max_turns'], 'timeout_s': tasks[task]['timeout_s']})
    return plan


def estimate(plan):
    n = len(plan)
    out = {'runs': n}
    for label, i in (('lo', 0), ('mid', 1), ('hi', 2)):
        out['minutes_' + label] = round(n * (PRIOR_S[i] + OVERHEAD_S) / 60, 1)
        out['usd_' + label] = round(n * PRIOR_USD[i], 2)
    out['minutes_worst_case'] = round(sum(p['timeout_s'] + OVERHEAD_S for p in plan) / 60, 1)
    return out


def format_plan(plan):
    lines = ['%-16s %-28s %5s %20s %22s' % ('arm', 'model', 'runs', 'minutes (lo/mid/hi)', 'USD (lo/mid/hi)')]
    keys = sorted({(p['arm'], p['model']) for p in plan})
    for arm, model in keys:
        e = estimate([p for p in plan if p['arm'] == arm and p['model'] == model])
        lines.append('%-16s %-28s %5d %20s %22s' % (arm, model, e['runs'], '%s/%s/%s' % (e['minutes_lo'], e['minutes_mid'], e['minutes_hi']),
                                                     '%s/%s/%s' % (e['usd_lo'], e['usd_mid'], e['usd_hi'])))
    e = estimate(plan)
    lines.append('%-16s %-28s %5d %20s %22s' % ('TOTAL', '', e['runs'], '%s/%s/%s' % (e['minutes_lo'], e['minutes_mid'], e['minutes_hi']),
                                                 '%s/%s/%s' % (e['usd_lo'], e['usd_mid'], e['usd_hi'])))
    lines.append('worst case if every run hits its timeout: %s minutes' % e['minutes_worst_case'])
    lines.append('priors: %d-%d s and $%.1f-%.1f per run (measured 2026-09, one driver); estimates, not quotes.'
                 % (PRIOR_S[0], PRIOR_S[2], PRIOR_USD[0], PRIOR_USD[2]))
    return '\n'.join(lines)


def write_manifest(path, manifest):
    """Atomic: a reader (or a Ctrl-C) never sees a half-written manifest."""
    path = Path(path)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(tmp, path)


# --- synthetic runs (dry-run and tests) ---------------------------------------------------------

def _rng(seed, run_id):
    return random.Random(int(hashlib.md5(f'{seed}:{run_id}'.encode()).hexdigest()[:12], 16))


def synthetic_run(spec, task, out_dir, events_path):
    """Fabricate a transcript and event log for one planned run. SYNTHETIC: numbers mean nothing."""
    rng = _rng(spec['seed'], spec['run_id'])
    p_ok = 0.9 - (0.15 if 'haiku' in spec['model'] else 0) - (0.1 if 'hard-surface' in task['tags'] else 0)
    roll = rng.random()
    if roll < p_ok:
        kind, events = 'correct', list(task['expected'])
    elif roll < p_ok + (1 - p_ok) * .5:
        kind, events = 'wrong', list(task['synthetic']['wrong'])
    elif roll < p_ok + (1 - p_ok) * .75:
        kind, events = 'partial', list(task['synthetic']['partial'])
    else:
        kind, events = 'none', []
    timed_out = kind == 'none' and rng.random() < .4
    base = {'native': 5, 'native-skill': 5, 'stack': 7, 'stack-advanced': 8, 'facade': 7}[spec['arm']]
    turns = max(2, base + len(task['expected']) + rng.randint(-1, 2))
    server = runner.ARM_SERVER[spec['arm']]
    lines = []
    for i in range(turns):
        lines.append({'type': 'assistant', 'message': {'id': f'm{i}', 'content': [{'type': 'tool_use', 'id': f'u{i}', 'name': f'mcp__{server}__tool', 'input': {}}]}})
        lines.append({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': f'u{i}', 'content': 'ok'}]}})
    tokens_in, tokens_out = 900 * turns, 120 * turns
    lines.append({'type': 'result', 'num_turns': turns, 'duration_ms': int(turns * 2900), 'total_cost_usd': round(0.05 * turns + rng.random() * .1, 4),
                  'usage': {'input_tokens': tokens_in, 'output_tokens': tokens_out, 'cache_read_input_tokens': 6000 * turns,
                            'cache_creation_input_tokens': 4000}, 'modelUsage': {spec['model']: {}}})
    transcript = Path(out_dir) / f"{spec['run_id']}.jsonl"
    transcript.write_text('\n'.join(json.dumps(x) for x in lines) + '\n')
    now = time.time()
    with Path(events_path).open('a') as fh:
        for n, e in enumerate(events):
            row = dict(e, ts=now + n * .01, run=spec['run_id'], task=spec['task'])
            fh.write(json.dumps(row, sort_keys=True) + '\n')
    return {'wall_s': round(turns * 2.9 + rng.random() * 5, 1), 'returncode': 'timeout' if timed_out else 0,
            'transcript': str(transcript), 'synthetic': True}


# --- run ----------------------------------------------------------------------------------------

def execute(plan, tasks, args, out_dir, events_path, base_url=None):
    """Run every planned run sequentially (never two agents at once). Returns (manifest, exit_code)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / 'manifest.json'
    manifest = {'version': 1, 'seed': args.seed, 'dry_run': bool(args.dry_run), 'planned': len(plan),
                'interrupted': False, 'stopped': None, 'windows_opened': [], 'runs': []}
    write_manifest(manifest_path, manifest)
    started = time.monotonic()
    code = 0
    try:
        for spec in plan:
            task = tasks[spec['task']]
            timeout = args.agent_timeout or spec['timeout_s']
            if not args.dry_run and (time.monotonic() - started) + timeout > args.max_total_minutes * 60:
                manifest['stopped'] = 'max-total-minutes'
                break
            entry = dict(spec, title=task['title'].format(run=spec['run_id']), synthetic=bool(args.dry_run),
                         window_id=None, started=time.time())
            if args.dry_run:
                entry.update(synthetic_run(spec, task, out_dir, events_path))
            else:
                transcript = out_dir / f"{spec['run_id']}.jsonl"
                window_id = None
                try:
                    window_id = runner.open_page(f"{base_url}{task['route']}?run={spec['run_id']}")
                    entry['window_id'] = window_id
                    manifest['windows_opened'].append(window_id)
                    time.sleep(1)  # let the tab load before the agent starts
                    entry.update(runner.run_agent(spec['arm'], spec['task'], entry['title'], transcript, spec['model'],
                                                  min(spec['max_turns'], args.max_turns or spec['max_turns']), timeout))
                    entry['transcript'] = str(transcript)
                finally:
                    if window_id is not None:
                        runner.close_window(window_id)  # by id, never by title
            entry['ended'] = time.time()
            manifest['runs'].append(entry)
            write_manifest(manifest_path, manifest)
            print('[%d/%d] %s' % (len(manifest['runs']), len(plan), spec['run_id']), flush=True)
    except KeyboardInterrupt:
        manifest['interrupted'] = True
        code = 130
        print('interrupted: manifest kept consistent, window closed', file=sys.stderr)
    write_manifest(manifest_path, manifest)
    return manifest, code


# --- score / report -----------------------------------------------------------------------------

def score_manifest(manifest, events_path, tasks):
    rows = []
    for run in manifest['runs']:
        task = tasks[run['task']]
        events = score.load_events(events_path, run['run_id'])
        timed_out = run.get('returncode') == 'timeout'
        outcome, wrong = classify(task, events, timed_out)
        trace = score.scan_transcript(run['transcript'])
        calls = score.count_llm_visible_calls(run['transcript'])
        usage = trace['usage'] or {}
        infra = run.get('returncode') not in (0, 'timeout') and calls == 0 and not events
        rows.append({
            'run_id': run['run_id'], 'arm': run['arm'], 'task': run['task'], 'tags': task['tags'], 'model': run.get('model') or trace['model'],
            'rep': run['rep'], 'seed': run['seed'], 'outcome': outcome, 'wrong_clicks': wrong, 'turns': trace['turns'],
            'mcp_calls': calls, 'wall_s': run.get('wall_s'), 'cost_usd': trace['cost_usd'],
            'tokens': {'input': usage.get('input_tokens'), 'output': usage.get('output_tokens'),
                       'cache_read': usage.get('cache_read_input_tokens'), 'cache_write': usage.get('cache_creation_input_tokens')},
            'synthetic': bool(run.get('synthetic')), 'invalid': bool(infra)})
    return rows


def _f(x, nd=2):
    return '-' if x is None else ('%.*f' % (nd, x))


def _mi(s, nd=1):
    return '-' if s['median'] is None else '%s [%s]' % (_f(s['median'], nd), _f(s['iqr'], nd))


def _rate(rate, ci):
    return '-' if rate is None else '%d%% (%d-%d%%)' % (round(rate * 100), round(ci[0] * 100), round(ci[1] * 100))


def _table(header, rows):
    out = ['| ' + ' | '.join(header) + ' |', '|' + '---|' * len(header)]
    return '\n'.join(out + ['| ' + ' | '.join(str(c) for c in r) + ' |' for r in rows])


def _summary_row(label, s):
    return list(label) + [s['n'], _rate(s['success_rate'], s['success_ci']), _rate(s['wrong_click_rate'], s['wrong_click_ci']),
                          _mi(s['turns']), _mi(s['wall_s'], 0), _mi(s['cost_usd'], 3), _f(s['cost_per_success'], 3)]


def report_markdown(rows, manifest=None):
    head = ['n', 'success (Wilson 95%)', 'wrong-click runs (Wilson 95%)', 'turns med [IQR]', 'wall s med [IQR]', 'cost $ med [IQR]', '$/success']
    out = ['# Eval suite report', '']
    if any(r['synthetic'] for r in rows):
        out += ['**SYNTHETIC DATA: produced by --dry-run. These numbers test the plumbing and mean nothing.**', '']
    out += ['n is small. Wilson intervals are wide and usually overlap; treat differences as directional unless the '
            'preregistered rule says `established`. See PREREGISTRATION.md.', '']
    if manifest and (manifest.get('interrupted') or manifest.get('stopped')):
        out += ['Run was cut short: interrupted=%s stopped=%s' % (manifest.get('interrupted'), manifest.get('stopped')), '']
    inval = [r['run_id'] for r in rows if r['invalid']]
    if inval:
        out += ['Excluded as infrastructure failures (rerun once): ' + ', '.join(inval), '']
    out += ['## Per (arm, model)', '', _table(['arm', 'model'] + head, [_summary_row(k, s) for k, s in metrics.by_arm_model(rows).items()]), '']
    out += ['## Per category', '', _table(['arm', 'model', 'tag'] + head, [_summary_row(k, s) for k, s in metrics.by_category(rows).items()]), '']
    arms = sorted({r['arm'] for r in rows} - {'native'})
    for arm in arms:
        d = metrics.paired_deltas(rows, arm)
        if d:
            out += ['## Paired deltas: %s minus native (per task, mean over paired runs)' % arm, '',
                    _table(['model', 'task', 'pairs', 'success', 'wrong clicks', 'turns', 'wall s', 'cost $'],
                           [[m, t, v['pairs'], _f(v['success']), _f(v['wrong_clicks']), _f(v['turns']), _f(v['wall_s'], 1), _f(v['cost_usd'], 3)]
                            for (m, t), v in d.items()]), '']
    v = metrics.verdict(rows)
    out += ['## Preregistered verdict', '']
    if not v['per_arm']:
        out += ['No stack arm present.', '']
    for arm, e in v['per_arm'].items():
        out += ['- **%s vs native, Haiku driver: %s.** Invalidated: %s%s. No advantage anywhere: %s. Large cheap-driver lift: %s. Action: %s.'
                % (arm, e['claim'], e['invalidated'], ' (provisional: baseline has no stock skill)' if e['provisional'] else '',
                   e['no_advantage_anywhere'], e['large_cheap_driver_lift'], e['action']),
                '  - other models: ' + ', '.join('%s=%s' % (m, x['label']) for m, x in e['models'].items())]
    return '\n'.join(out) + '\n'


# --- CLI ----------------------------------------------------------------------------------------

def _common(p):
    p.add_argument('--suite', choices=['small', 'core', 'full'], default='core', help='task set (default core = 12 tasks)')
    p.add_argument('--tasks', nargs='+', help='explicit task ids (overrides --suite)')
    p.add_argument('--arms', nargs='+', default=DEFAULT_ARMS, choices=[a for a in runner.ARMS if a != 'facade'])
    p.add_argument('--models', nargs='+', default=['sonnet'], help='sonnet|haiku|opus or a full model id')
    p.add_argument('--runs', type=int, default=1, help='runs per (arm, model, task)')
    p.add_argument('--seed', type=int, default=SEED)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    _common(sub.add_parser('plan', help='print the cross product with time and cost estimates'))
    p = sub.add_parser('run', help='execute (live operates the desktop; --dry-run is synthetic)')
    _common(p)
    p.add_argument('--dry-run', action='store_true', help='synthetic transcripts and events; no desktop, no claude, no network')
    p.add_argument('--i-have-consent', action='store_true', help='required for live runs: the user consented in chat to operating their desktop')
    p.add_argument('--max-total-minutes', type=float, help='required for live runs: stop before exceeding this wall budget')
    p.add_argument('--agent-timeout', type=int, help='seconds per run (default: per-task timeout_s)')
    p.add_argument('--max-turns', type=int, help='cap on agent turns (default: per-task max_turns)')
    p.add_argument('--port', type=int, default=8934)
    p.add_argument('--out-dir', default=None)
    for name in ('score', 'report'):
        s = sub.add_parser(name)
        s.add_argument('--manifest', required=True)
        s.add_argument('--events', required=True)
        if name == 'report':
            s.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    tasks = load_tasks()

    if args.cmd in ('plan', 'run'):
        ids = select_tasks(tasks, args.tasks, args.suite)
        plan = build_plan(tasks, ids, args.arms, resolve_models(args.models), args.runs, args.seed)
    if args.cmd == 'plan':
        print(format_plan(plan))
        return 0
    if args.cmd == 'run':
        if not args.dry_run:
            if not args.i_have_consent:
                raise SystemExit("Refusing to run live: pass --i-have-consent after getting the user's explicit consent to operate "
                                 'their desktop/browser for this suite (see README.md). Use --dry-run to test offline.')
            if not args.max_total_minutes or args.max_total_minutes <= 0:
                raise SystemExit('Refusing to run live without --max-total-minutes.')
        out_dir = Path(args.out_dir or HERE / ('runs-dry' if args.dry_run else 'runs-suite'))
        out_dir.mkdir(parents=True, exist_ok=True)
        events_path = out_dir / 'events.jsonl'
        print(format_plan(plan))
        httpd, base_url = None, None
        if not args.dry_run:
            import server
            httpd = server.make_server(args.port, events_path)  # 127.0.0.1 only
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            base_url = 'http://127.0.0.1:%d' % args.port
            runner.wait_for_server(base_url)
        try:
            manifest, code = execute(plan, tasks, args, out_dir, events_path, base_url)
        finally:
            if httpd:
                httpd.shutdown()
        print('manifest: %s\nevents: %s' % (out_dir / 'manifest.json', events_path))
        return code
    manifest = json.loads(Path(args.manifest).read_text())
    rows = score_manifest(manifest, args.events, tasks)
    if args.cmd == 'score':
        for r in rows:
            print(json.dumps(r))
        (Path(args.manifest).parent / 'scored.json').write_text(json.dumps(rows, indent=2))
        return 0
    if args.json:
        print(json.dumps({'by_arm_model': {'|'.join(k): v for k, v in metrics.by_arm_model(rows).items()}, 'verdict': metrics.verdict(rows)}, indent=2, default=str))
    else:
        print(report_markdown(rows, manifest))
    return 0


if __name__ == '__main__':
    sys.exit(main())
