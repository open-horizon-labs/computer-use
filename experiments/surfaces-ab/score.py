"""Score surfaces-A/B runs: outcome from ground truth, turns/tokens/cost/time from the transcript, interruptions from the monitor.

Reads manifest.json (one record per run, written by runner.py: the independent truth values, the doc text read back, the monitor
summary and timeline path) plus the sanitized transcripts and events.jsonl. Nothing here operates the desktop.
"""
import argparse
import json
import sys
from pathlib import Path

import monitor
import tasks

MAX_STRING = 4000


def sanitize(obj):
    """Copy of a stream-json object with screenshots and base64 removed and long strings capped (committed transcripts hold no images)."""
    if isinstance(obj, dict):
        if obj.get('type') == 'image' and isinstance(obj.get('source'), dict):
            size = len(str(obj['source'].get('data', '')))
            return {'type': 'image', 'omitted_bytes': size}
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    if isinstance(obj, str) and len(obj) > MAX_STRING:
        return obj[:MAX_STRING] + '...[%d chars cut]' % (len(obj) - MAX_STRING)
    return obj


def sanitize_file(src, dst):
    """Write a sanitized copy of a raw stream-json transcript; non-JSON lines are kept as capped text."""
    with open(src) as fin, open(dst, 'w') as fout:
        for line in fin:
            line = line.rstrip('\n')
            if not line.strip():
                continue
            try:
                fout.write(json.dumps(sanitize(json.loads(line))) + '\n')
            except json.JSONDecodeError:
                fout.write(json.dumps({'type': 'raw', 'text': line[:500]}) + '\n')


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def scan_transcript(path):
    """turns, mcp_calls, tokens, cost, final_text, errors from a claude -p stream-json transcript (best effort: not a versioned contract)."""
    out = {'turns': 0, 'mcp_calls': 0, 'cost_usd': None, 'duration_ms': None, 'final_text': '', 'is_error': None, 'subtype': None,
           'tokens': {'input': None, 'output': None, 'cache_read': None, 'cache_write': None}}
    if not Path(path).is_file():
        return out
    seen, num_turns = set(), None
    with open(path) as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get('type') == 'assistant':
                mid = (event.get('message') or {}).get('id')
                if mid is None or mid not in seen:
                    out['turns'] += 1
                    seen.add(mid)
                for node in walk(event.get('message', event)):
                    if node.get('type') == 'tool_use' and str(node.get('name', '')).startswith('mcp__'):
                        out['mcp_calls'] += 1
            if event.get('type') == 'result':
                num_turns = event.get('num_turns', num_turns)
                out['cost_usd'] = event.get('total_cost_usd', out['cost_usd'])
                out['duration_ms'] = event.get('duration_ms', out['duration_ms'])
                out['final_text'] = event.get('result') or out['final_text']
                out['is_error'] = event.get('is_error')
                out['subtype'] = event.get('subtype')
                u = event.get('usage') or {}
                out['tokens'] = {'input': u.get('input_tokens'), 'output': u.get('output_tokens'),
                                 'cache_read': u.get('cache_read_input_tokens'), 'cache_write': u.get('cache_creation_input_tokens')}
    if num_turns is not None:
        out['turns'] = num_turns
    return out


def load_events(path, run_id):
    p = Path(path)
    if not p.is_file():
        return []
    rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    return [r for r in rows if r.get('run') == run_id]


def load_timeline(path):
    p = Path(path) if path else None
    if not p or not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


# Apps a run itself starts or drives. Only their focus changes and windows count against an arm: Cua Driver routes input
# in the background, so anything else that appears or takes focus during a run is the user's own activity (measured
# 2026-10-01: every new_user_window in the computer-use rerun belonged to Zoom, Discord, Slack, Chrome, 1Password ...).
AGENT_APPS = ('Google Chrome for Testing', 'Calculator', 'TextEdit', 'qemu-system', 'Emulator',
              'Android Emulator', 'Simulator', 'Device Hub', 'DeviceHub', 'Cua Driver', 'CuaDriver')  # Device Hub: Xcode 27's Simulator


# The vanilla arm drives the real screen with a keyboard, so it can also open Spotlight, the Dock's apps, Safari, System Settings ...
VANILLA_EXTRA_APPS = ('Spotlight', 'Safari', 'System Settings', 'System Preferences', 'Finder', 'Dock')


def attributed(timeline, arm=None):
    """Interruptions caused by the run's own apps: focus taken by one, and its windows appearing on the user's screens.
    The vanilla arm also owns what its keyboard can open (VANILLA_EXTRA_APPS)."""
    apps = AGENT_APPS + (VANILLA_EXTRA_APPS if arm == 'vanilla' else ())
    mine = lambda name: any(a.lower() in (name or '').lower() for a in apps)
    focus = [e for e in timeline if e.get('kind') == 'focus_change' and mine(e.get('to_app'))]
    wins = [e for e in timeline if e.get('kind') == 'new_user_window' and mine(e.get('app') or e.get('owner'))]
    return {'agent_focus_steals': len(focus), 'agent_windows_on_user_screens': len(wins),
            'agent_apps_seen': sorted({e.get('to_app') or e.get('app') or e.get('owner') for e in focus + wins})}


def score_run(run, events_path, base):
    """One result row for a manifest record. Paths in the record are relative to `base`."""
    trace = scan_transcript(base / run['transcript'])
    timed_out = run.get('returncode') == 'timeout'
    kind = tasks.TASKS[run['task']]['kind']
    needs_truth = run['task'] == 'upload' or kind == 'text'
    if run.get('truth_error') or (needs_truth and run.get('truth') is None):
        # No independent truth (probe failed): never judge against None (it used to score 'wrong' via a 'none' substring match).
        outcome, detail = 'unscored', {'note': run.get('truth_error') or 'no ground truth recorded'}
    else:
        outcome, detail = tasks.judge(run['task'], events=load_events(events_path, run.get('page_run') or run['run_id']), text=trace['final_text'],
                                      truth=run.get('truth'), doc=run.get('doc_text'), acted=trace['mcp_calls'] > 0, timed_out=timed_out)
    mon = run.get('monitor') or {}
    timeline = load_timeline(base / run['timeline']) if run.get('timeline') else []
    return {
        'arm': run['arm'], 'task': run['task'], 'run_id': run['run_id'], 'outcome': outcome, 'detail': detail,
        'turns': trace['turns'], 'mcp_calls': trace['mcp_calls'], 'tokens': trace['tokens'], 'cost_usd': trace['cost_usd'],
        'wall_s': run.get('wall_s'), 'returncode': run.get('returncode'), 'stop': trace['subtype'],
        'interruptions': {k: mon.get(k) for k in ('focus_changes', 'focus_steals', 'new_user_windows', 'windows_to_user_display',
                                                  'overlay_windows', 'cursor_move_samples', 'cursor_bursts', 'cursor_px',
                                                  'cursor_moves_on_agent_display', 'new_agent_windows', 'monitor_ok')},
        'attributed': attributed(timeline, run['arm']),
        'annoyances': monitor.annoyances(timeline, mon),
        'final_text': trace['final_text'][:300], 'truth': run.get('truth'),
    }


def table(rows):
    head = ['task', 'arm', 'outcome', 'turns', 'calls', 'tokens in/out/cache', 'cost $', 'wall s', 'focus steals', 'new user windows', 'cursor px (bursts)']
    lines = ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)]
    for r in rows:
        t, i = r['tokens'], r['interruptions']
        tok = '%s/%s/%s' % (t['input'], t['output'], (t['cache_read'] or 0) + (t['cache_write'] or 0))
        lines.append('| ' + ' | '.join(str(x) for x in [
            r['task'], r['arm'], r['outcome'], r['turns'], r['mcp_calls'], tok,
            '%.2f' % r['cost_usd'] if r['cost_usd'] is not None else '-', '%.0f' % r['wall_s'] if r['wall_s'] is not None else '-',
            i['focus_steals'], i['new_user_windows'], '%s (%s)' % (i['cursor_px'], i['cursor_bursts'])]) + ' |')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--events', default=None, help='default: events.jsonl next to the manifest')
    args = parser.parse_args(argv)
    manifest = Path(args.manifest)
    base = manifest.parent
    events = args.events or str(base / 'events.jsonl')
    rows = [score_run(r, events, base) for r in json.loads(manifest.read_text())]
    (base / 'results.json').write_text(json.dumps(rows, indent=2))
    (base / 'results.md').write_text(table(rows) + '\n')
    print(table(rows))
    for r in rows:
        for note in r['annoyances']:
            print('  [%s/%s] %s' % (r['task'], r['arm'], note))
    return 0


if __name__ == '__main__':
    sys.exit(main())
