"""Surfaces A/B runner: stock Cua Driver MCP ("native") vs this project's look/do MCP server ("computer-use").
OPERATES THE DESKTOP -- read README.md first. Refuses to run without --i-have-consent.

Per (task, arm): start only the surface the job needs, start the interruption monitor, run one headless `claude -p`
restricted to exactly that arm's MCP server, stop the monitor, read independent ground truth, then clean up what the
harness started. Do not touch the mouse or keyboard during a run: the monitor cannot tell your moves from the agent's.
"""
import argparse
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import monitor
import score
import server
import surfaces
import tasks

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODEL = 'claude-sonnet-5-5'
ARMS = ('native', 'computer-use', 'vanilla')
DEFAULT_ARMS = ('native', 'computer-use')  # vanilla uses the user's REAL screen and mouse: opt in with --arms vanilla
# The MCP server key for the computer-use arm is `computer-use-oh`: Claude Code reserves `computer-use` and drops a server by that name
# `computer-use` (reserved built-in name; measured in the first smoke run: mcp_servers was empty and the agent had no tools).
ARM_SERVER = {'native': 'cua-driver', 'computer-use': 'computer-use-oh', 'vanilla': 'vanilla-cu'}
DEFAULT_PYTHON = '/Users/muness1/src/open-horizon-labs/computer-use/.venv-facade/bin/python'
# Every built-in that can act outside the arm's MCP server (the stream-json init lists Monitor, Cron*, RemoteTrigger, SendMessage,
# Artifact... besides the classic file/shell tools). ToolSearch stays: both arms need it to load their deferred MCP tools.
_BASE_DENY = ['Bash', 'Edit', 'Write', 'NotebookEdit', 'Read', 'Glob', 'Grep', 'WebFetch', 'WebSearch', 'Agent', 'Task', 'Monitor',
              'CronCreate', 'CronDelete', 'RemoteTrigger', 'ScheduleWakeup', 'PushNotification', 'SendMessage', 'Artifact', 'ArtifactData',
              'ArtifactComments', 'EnterWorktree', 'ExitWorktree', 'LSP', 'DesignSync']
ALLOWED = {arm: ['mcp__' + srv] for arm, srv in ARM_SERVER.items()}
ALLOWED['vanilla'] = ['mcp__vanilla-cu__computer', 'ToolSearch']  # the one tool; ToolSearch loads it (deferred)
# Skill is off in native (the installed skill would reintroduce facade guidance); the computer-use arm never needs it either.
DISALLOWED = {'native': _BASE_DENY + ['Skill'], 'computer-use': _BASE_DENY + ['Skill'], 'vanilla': _BASE_DENY + ['Skill']}

TAIL = (' Use only the tools available to you. Do not act on any other window, tab or app. '
        'When finished, report exactly what you did and how you verified the result.')
# Per-minute-of-run cost priors for `--plan`, replaced by measured numbers once a suite has run. (seconds lo/mid/hi, USD lo/mid/hi)
PRIORS = {'web': ((40, 90, 200), (0.4, 0.9, 1.8)), 'mac': ((40, 100, 240), (0.4, 1.0, 2.0)),
          'android': ((90, 200, 450), (0.8, 1.8, 3.5)), 'ios': ((90, 200, 450), (0.8, 1.8, 3.5))}
SETUP_S = {'web': 6, 'mac': 8, 'android': 120, 'ios': 8}


def build_prompt(task, arm, facts):
    """User intent only. The arm differs only in how the surface is introduced (see README: native is handed an open window,
    computer-use a URL or device id, because that is how each tool is meant to be addressed). No answers, no decoys, no tool hints."""
    spec = tasks.TASKS[task]
    goal = spec['prompt'].format(**{k: v for k, v in facts.items() if k == 'file'}) if '{file}' in spec['prompt'] else spec['prompt']
    surface = spec['surface']
    if arm == 'vanilla':  # what a plain user would say: it is on the screen, in front. No window titles, URLs, app ids or device ids.
        intro = {'web': 'The page is open on screen. ', 'mac': 'The %s app is open on screen. ' % facts.get('app'),
                 'android': 'An Android emulator is open on screen. ', 'ios': 'An iPhone 17 Pro simulator is open on screen. '}[surface]
    elif surface == 'web':
        intro = ('A Chrome window whose title begins with %r is open on this Mac. ' % facts['title']) if arm == 'native' else 'Open %s in the browser. ' % facts['url']
    elif surface == 'mac':
        intro = 'The %s app is running on this Mac. ' % facts['app']
    elif surface == 'android':
        intro = ('An Android emulator window is open on this Mac. ' if arm == 'native'
                 else 'An Android emulator is running (device id %s). ' % facts['device'])
    else:
        app = facts.get('app') or 'Device Hub'
        intro = (('The iPhone 17 Pro simulator is open on this Mac in Device Hub (Xcode 27). ' if app == 'Device Hub'
                  else 'The iPhone 17 Pro simulator is open on this Mac in the Simulator app. ') if arm == 'native'
                 else 'An iPhone 17 Pro simulator is running (device id %s). ' % facts['device'])
    return intro + goal + TAIL


def mcp_config(arm, out_dir):
    py = os.environ.get('CUA_FACADE_PYTHON') or DEFAULT_PYTHON
    servers = {'computer-use-oh': {'command': py, 'args': [str(ROOT / 'computer_use/server.py')]},
               'cua-driver': {'command': str(Path.home() / '.local/bin/cua-driver'), 'args': ['mcp']},
               'vanilla-cu': {'command': py, 'args': [str(HERE / 'vanilla_cu.py')]}}
    path = Path(out_dir).resolve() / ('mcp-config.%s.json' % arm)
    path.write_text(json.dumps({'mcpServers': {ARM_SERVER[arm]: servers[ARM_SERVER[arm]]}}, indent=2))
    return path


def claude_argv(arm, prompt, model, max_turns, config):
    return ['claude', '-p', prompt, '--model', model, '--max-turns', str(max_turns), '--strict-mcp-config', '--mcp-config', str(config),
            '--allowedTools', ','.join(ALLOWED[arm]), '--disallowedTools', ','.join(DISALLOWED[arm]),
            '--output-format', 'stream-json', '--verbose']


def run_agent(arm, prompt, raw_path, model, max_turns, timeout, config):
    """Run claude in its own process group (killed whole on timeout, so no MCP child survives). Returns {wall_s, returncode}."""
    began = time.monotonic()
    with open(raw_path, 'w') as out:
        proc = subprocess.Popen(claude_argv(arm, prompt, model, max_turns, config), stdout=out, stderr=subprocess.STDOUT,
                                cwd=tempfile.mkdtemp(prefix='cua-ab-'), start_new_session=True)  # scratch cwd: no AGENTS.md or memory contamination
        try:
            code = proc.wait(timeout)
        except subprocess.TimeoutExpired:
            code = 'timeout'
            _kill_group(proc.pid)
            proc.wait()
        except BaseException:
            _kill_group(proc.pid)
            raise
    return {'wall_s': round(time.monotonic() - began, 1), 'returncode': code}


def _kill_group(pid):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except OSError:
            return
        time.sleep(1.5)


def preflight(arms, task_ids):
    problems = []
    if not shutil.which('claude'):
        problems.append('claude is not on PATH')
    if 'native' in arms and not (Path.home() / '.local/bin/cua-driver').exists():
        problems.append('~/.local/bin/cua-driver is missing')
    if 'vanilla' in arms:
        if not Path(os.environ.get('CUA_FACADE_PYTHON') or DEFAULT_PYTHON).exists():
            problems.append('python with the mcp package missing for the vanilla server (set CUA_FACADE_PYTHON)')
        import vanilla_cu
        problems += vanilla_cu.doctor()
    if 'computer-use' in arms:
        if not Path(os.environ.get('CUA_FACADE_PYTHON') or DEFAULT_PYTHON).exists():
            problems.append('facade python missing (set CUA_FACADE_PYTHON): %s' % (os.environ.get('CUA_FACADE_PYTHON') or DEFAULT_PYTHON))
    foreign = surfaces.foreign_facades(surfaces.processes(), surfaces.own_pids())
    if foreign:
        problems.append('another computer-use facade session is running (it and the arm would kill each other\'s browser and share the '
                        'agent display, and the stray sweep could kill its helpers); stop it first: %s' % '; '.join('%d %s' % (p, c[:80]) for p, c in foreign))
    if any(tasks.TASKS[t]['surface'] == 'web' for t in task_ids) and ('native' in arms or 'vanilla' in arms):
        try:
            surfaces.chrome_binary()
        except RuntimeError as error:
            problems.append(str(error))
    return problems


def plan(task_ids, arms, runs):
    """Offline estimate from the priors (no side effects). Returns (minutes lo/mid/hi, usd lo/mid/hi, rows)."""
    tot_s, tot_usd, rows = [0, 0, 0], [0, 0, 0], []
    for t in task_ids:
        surf = tasks.TASKS[t]['surface']
        (s, u) = PRIORS[surf]
        for _ in arms:
            for i in range(3):
                tot_s[i] += (s[i] + SETUP_S[surf]) * runs
                tot_usd[i] += u[i] * runs
        rows.append((t, surf, s, u))
    return [round(x / 60, 1) for x in tot_s], [round(x, 2) for x in tot_usd], rows


def record_run(manifest_path, manifest):
    tmp = manifest_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(manifest, indent=2))
    tmp.replace(manifest_path)


def page_token(run_id):
    """The run id the PAGE shows (URL, title, event log): neutral, so neither arm's prompt names the arm (the window title used to read
    'Clinic Slots native-booking-...' vs a URL with 'run=computer-use-booking-...')."""
    import hashlib
    return 'r' + hashlib.sha256(run_id.encode()).hexdigest()[:10]


def run_one(arm, task, args, base_url, out_dir, events_path):
    """One run. Raises surfaces.SetupRefused (or another error) only BEFORE the agent starts; once it has run, any later failure
    (truth probe, sanitizing) is recorded on the record, which is still returned and scored (never silently a skip)."""
    spec = tasks.TASKS[task]
    run_id = '%s-%s-%d' % (arm, task, int(time.time()))
    page_run = page_token(run_id)
    print('== %s / %s run=%s ==' % (task, arm, run_id), flush=True)
    work = Path(tempfile.mkdtemp(prefix='cua-ab-work-'))
    before = surfaces.processes()
    record = {'run_id': run_id, 'page_run': page_run, 'arm': arm, 'task': task, 'surface': spec['surface'], 'model': args.model, 'started': time.strftime('%Y-%m-%dT%H:%M:%S')}
    surface, mon, ran = None, None, False
    try:
        foreign = surfaces.foreign_facades(surfaces.processes(), surfaces.own_pids())
        if foreign:  # re-checked per run: another session may have started one since preflight
            raise surfaces.SetupRefused('another facade session is running: %s' % '; '.join('%d %s' % (p, c[:60]) for p, c in foreign))
        surface = surfaces.open_surface(task, arm, page_run, base_url, work)
        record['facts'] = {k: v for k, v in surface.facts.items()}
        prompt = build_prompt(task, arm, surface.facts)
        record['prompt'] = prompt
        config = mcp_config(arm, out_dir)
        raw = out_dir / ('%s.raw.jsonl' % run_id)
        mon = monitor.Monitor(out_dir / ('%s.monitor.jsonl' % run_id))
        mon.start()
        ran = True
        try:
            record.update(run_agent(arm, prompt, raw, args.model, args.max_turns, args.agent_timeout, config))
        finally:
            record['monitor'] = mon.stop()
            record['timeline'] = '%s.monitor.jsonl' % run_id
        try:
            truth = surface.read_truth()
        except Exception as error:  # the run happened: keep it, unscored, instead of losing it as a 'skip' (or scoring None as wrong)
            truth = None
            record['truth_error'] = '%s: %s' % (type(error).__name__, error)
        if task == 'textedit':
            record['doc_text'] = (truth or {}).get('doc_text')
        else:
            record['truth'] = truth if truth not in ({}, '') else None
        score.sanitize_file(raw, out_dir / ('%s.transcript.jsonl' % run_id))
        raw.unlink()
        record['transcript'] = '%s.transcript.jsonl' % run_id
    except KeyboardInterrupt as error:
        record['error'] = '%s: %s' % (type(error).__name__, error)
        raise
    except Exception as error:
        record['error'] = '%s: %s' % (type(error).__name__, error)
        if not ran:
            raise
    finally:
        if mon is not None and mon.proc is not None and mon.proc.poll() is None:
            mon.stop()
        errors = surface.close() if surface is not None else []
        new = surfaces.new_processes(before, surfaces.processes())
        stray = surfaces.killable(new, surfaces.own_pids())
        if stray:
            surfaces.kill_pids([p for p, _ in stray])
        time.sleep(1)
        left = [(p, c[:80]) for p, c in surfaces.new_processes(before, surfaces.processes())]
        record['cleanup'] = {'close_errors': errors, 'killed_strays': [(p, c[:80]) for p, c in stray], 'still_running_after_cleanup': left}
        shutil.rmtree(work, ignore_errors=True)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arms', nargs='+', default=list(DEFAULT_ARMS), choices=ARMS)
    parser.add_argument('--tasks', nargs='+', default=list(tasks.ORDER), choices=list(tasks.ORDER))
    parser.add_argument('--runs', type=int, default=1)
    parser.add_argument('--model', default=MODEL)
    parser.add_argument('--max-turns', type=int, default=60)
    parser.add_argument('--agent-timeout', type=int, default=600, help='seconds per run')
    parser.add_argument('--max-total-minutes', type=float, default=180)
    parser.add_argument('--seed', type=int, default=20261001, help='arm order within each task is shuffled with this seed')
    parser.add_argument('--out-dir', default=None, help='default: experiments/surfaces-ab/runs/<timestamp>')
    parser.add_argument('--plan', action='store_true', help='print the cost/time estimate and exit (no side effects, no consent needed)')
    parser.add_argument('--i-have-consent', action='store_true',
                        help='required for a live run: acknowledges the user consented in chat to this session operating the desktop; it is not itself consent')
    args = parser.parse_args(argv)
    if args.plan:
        mins, usd, rows = plan(args.tasks, args.arms, args.runs)
        for t, surf, s, u in rows:
            print('%-11s %-8s %3d/%3d/%3d s  $%.1f/%.1f/%.1f per run' % (t, surf, *s, *u))
        print('TOTAL %d tasks x %d arms x %d run(s): %s min (lo/mid/hi), $%s (lo/mid/hi); worst case %d min at the per-run timeout' % (
            len(args.tasks), len(args.arms), args.runs, '/'.join(map(str, mins)), '/'.join(map(str, usd)),
            len(args.tasks) * len(args.arms) * args.runs * (args.agent_timeout + 60) // 60))
        return 0
    if not args.i_have_consent:
        raise SystemExit('Refusing to run: pass --i-have-consent after getting the user\'s explicit consent to operate their desktop for this '
                         'comparison (see README.md). The flag is an acknowledgment that the maintainer recorded consent, not consent itself.')
    problems = preflight(args.arms, args.tasks)
    if problems:
        raise SystemExit('Preflight failed:\n  ' + '\n  '.join(problems))
    out_dir = Path(args.out_dir) if args.out_dir else HERE / 'runs' / time.strftime('%Y%m%d-%H%M%S')
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / 'events.jsonl'
    httpd = server.make_server(0, events_path)  # loopback only, a free port
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base_url = 'http://127.0.0.1:%d' % httpd.server_address[1]
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    rng = random.Random(args.seed)
    manifest, manifest_path, began = [], out_dir / 'manifest.json', time.monotonic()
    print('Do not touch the mouse or keyboard during runs: the interruption monitor cannot tell your input from the agent\'s.', flush=True)
    try:
        for task in args.tasks:
            for _ in range(args.runs):
                for arm in rng.sample(args.arms, len(args.arms)):
                    if (time.monotonic() - began) / 60 > args.max_total_minutes:
                        print('max-total-minutes reached; stopping before %s/%s' % (task, arm))
                        raise KeyboardInterrupt
                    try:
                        record = run_one(arm, task, args, base_url, out_dir, events_path)
                    except Exception as error:  # setup refusal before the agent ran (app already running, no agent display...): record, move on
                        print('  skipped: %s' % error)
                        manifest.append({'arm': arm, 'task': task, 'skipped': str(error)})
                        record_run(manifest_path, manifest)
                        continue
                    manifest.append(record)
                    record_run(manifest_path, manifest)
    except KeyboardInterrupt:
        print('interrupted; manifest holds the runs finished so far', file=sys.stderr)
    finally:
        httpd.shutdown()
        record_run(manifest_path, manifest)
    done = [r for r in manifest if 'skipped' not in r and 'transcript' in r]
    if done:
        rows = [score.score_run(r, events_path, out_dir) for r in done]
        (out_dir / 'results.json').write_text(json.dumps(rows, indent=2))
        (out_dir / 'results.md').write_text(score.table(rows) + '\n')
        print(score.table(rows))
        for r in rows:
            for note in r['annoyances']:
                print('  [%s/%s] %s' % (r['task'], r['arm'], note))
    print('Results in %s' % out_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
