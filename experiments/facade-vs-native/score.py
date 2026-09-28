"""Score facade-vs-native A/B runs against events.jsonl ground truth.

Reads runner.py's manifest.json (one entry per run) plus the transcripts it
recorded (`claude -p --output-format stream-json` output, one JSON object per
line) and events.jsonl (the fixture server's own record of every button
click). Prints one line per run: correct/wrong/no-action, wrong-click count,
turns, wall time, cost, facade routes actually used, and caller_preselected
flags. Nothing here operates the desktop; it only reads files the runner
already produced.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from fixtures import BOOKING_EXPECTED_ID, ORDERS_EXPECTED_ID

EXPECTED = {'booking': {BOOKING_EXPECTED_ID}, 'orders': {ORDERS_EXPECTED_ID}}
# For orders, only a cancel that reaches confirmation counts as a real attempt.
TERMINAL_ACTION = {'booking': 'book', 'orders': 'cancel_confirm'}


def load_events(events_path, run_id):
    events = []
    if not Path(events_path).is_file():
        return events
    with open(events_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get('run') == run_id:
                events.append(row)
    return events


def classify(task, events):
    terminal = TERMINAL_ACTION[task]
    hits = [e['id'] for e in events if e.get('action') == terminal]
    wrong = [i for i in hits if i not in EXPECTED[task]]
    correct = [i for i in hits if i in EXPECTED[task]]
    if correct and not wrong:
        return 'correct', len(wrong)
    if wrong:
        return 'wrong', len(wrong)
    return 'no-action', 0


def walk(obj):
    """Yield every dict found anywhere in a nested JSON structure."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk(item)


def scan_transcript(transcript_path):
    """Best-effort extraction from a claude -p stream-json transcript.

    Tool results are opaque JSON text inside content blocks; we don't assume
    a fixed schema, we just walk every parsed object looking for the fields
    the facade's cua_trace/cua_choose/cua_verify results carry (route,
    caller_preselected, driver_version) plus turn count / cost / timing that
    `claude -p --output-format stream-json` reports on its own top-level
    'result' event.
    """
    turns = 0
    routes = Counter()
    caller_preselected_count = 0
    cost_usd = None
    duration_ms = None
    if not Path(transcript_path).is_file():
        return {'turns': 0, 'routes': {}, 'caller_preselected_count': 0, 'cost_usd': None, 'duration_ms': None}
    with open(transcript_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get('type') == 'assistant':
                turns += 1
            if event.get('type') == 'result':
                cost_usd = event.get('total_cost_usd', cost_usd)
                duration_ms = event.get('duration_ms', duration_ms)
            # Tool call arguments/results often arrive as raw JSON text inside
            # a content block; try to parse any string that looks like one.
            for node in walk(event):
                text = node.get('text') if isinstance(node, dict) else None
                if isinstance(text, str) and text.strip().startswith('{'):
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    for inner in walk(parsed):
                        route = inner.get('route')
                        if isinstance(route, str):
                            routes[route] += 1
                        elif isinstance(route, list):
                            for r in route:
                                if isinstance(r, str):
                                    routes[r] += 1
                        if inner.get('caller_preselected') is True:
                            caller_preselected_count += 1
    return {'turns': turns, 'routes': dict(routes), 'caller_preselected_count': caller_preselected_count,
            'cost_usd': cost_usd, 'duration_ms': duration_ms}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--events', required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text())
    for run in manifest:
        events = load_events(args.events, run['run_id'])
        outcome, wrong_clicks = classify(run['task'], events)
        trace = scan_transcript(run['transcript'])
        print(json.dumps({
            'arm': run['arm'], 'task': run['task'], 'run_id': run['run_id'],
            'outcome': outcome, 'wrong_clicks': wrong_clicks,
            'turns': trace['turns'], 'wall_s': run.get('wall_s'),
            'cost_usd': trace['cost_usd'], 'agent_duration_ms': trace['duration_ms'],
            'routes': trace['routes'], 'caller_preselected_count': trace['caller_preselected_count'],
        }))


if __name__ == '__main__':
    main()
