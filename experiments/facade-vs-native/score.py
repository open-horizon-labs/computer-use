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
import sys
from collections import Counter
from pathlib import Path

from fixtures import BOOKING_EXPECTED_ID, CANVAS_EXPECTED_ID, ORDERS_EXPECTED_ID

# Ceiling on LLM-visible MCP calls per task on the facade's default path (facade/CALL_BUDGET.json).
BUDGET_PATH = Path(__file__).resolve().parents[2] / 'facade' / 'CALL_BUDGET.json'
EXPECTED = {'booking': {BOOKING_EXPECTED_ID}, 'orders': {ORDERS_EXPECTED_ID}, 'canvas': {CANVAS_EXPECTED_ID}}
# For orders, only a cancel that reaches confirmation counts as a real attempt.
TERMINAL_ACTION = {'booking': 'book', 'orders': 'cancel_confirm', 'canvas': 'press'}


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
    seen_messages = set()
    num_turns = None
    routes = Counter()
    caller_preselected_count = 0
    cost_usd = None
    duration_ms = None
    usage = {}
    model = None
    if not Path(transcript_path).is_file():
        return {'turns': 0, 'routes': {}, 'caller_preselected_count': 0, 'cost_usd': None, 'duration_ms': None, 'usage': {}, 'model': None}
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
                # stream-json emits one assistant event per content block; one LLM turn = one message id.
                mid = (event.get('message') or {}).get('id')
                if mid is None or mid not in seen_messages:
                    turns += 1
                    if mid is not None:
                        seen_messages.add(mid)
            if event.get('type') == 'result':
                num_turns = event.get('num_turns', num_turns)
                cost_usd = event.get('total_cost_usd', cost_usd)
                duration_ms = event.get('duration_ms', duration_ms)
                usage = event.get('usage') or usage
                model = next(iter(event.get('modelUsage') or {}), model)
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
    return {'turns': num_turns if num_turns is not None else turns, 'routes': dict(routes), 'caller_preselected_count': caller_preselected_count,
            'cost_usd': cost_usd, 'duration_ms': duration_ms, 'usage': usage, 'model': model}


def count_llm_visible_calls(transcript_path):
    """MCP tool calls the driving LLM made: tool_use blocks named mcp__* in assistant events.

    Every such block is one LLM turn's hop (the 87% of wall time the facade must not multiply). Only assistant
    events count, so a tool_result or a repeated summary event is never counted, and Bash/Read are not MCP hops.
    """
    if not Path(transcript_path).is_file():
        return 0
    count = 0
    with open(transcript_path) as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get('type') != 'assistant':
                continue
            for node in walk(event.get('message', event)):
                if node.get('type') == 'tool_use' and str(node.get('name', '')).startswith('mcp__'):
                    count += 1
    return count


def budget_for(task, budget_path=BUDGET_PATH):
    """Max LLM-visible calls allowed for a live task on the facade arm, or None when unbudgeted."""
    tasks = json.loads(Path(budget_path).read_text()).get('live_task_budgets', {})
    entry = tasks.get(task, {}).get('max_llm_visible_calls')
    return entry['value'] if isinstance(entry, dict) else None


def headline(rows):
    """Facade-vs-native ratios of mean LLM-visible calls and turns, per task, when both arms are present."""
    out = []
    for task in sorted({r['task'] for r in rows}):
        arms = {arm: [r for r in rows if r['task'] == task and r['arm'] == arm] for arm in ('facade', 'native')}
        if not arms['facade'] or not arms['native']:
            continue
        mean = lambda arm, key: sum(r[key] for r in arms[arm]) / len(arms[arm])
        entry = {'task': task}
        for key in ('llm_visible_calls', 'turns'):
            native = mean('native', key)
            entry[key + '_ratio'] = round(mean('facade', key) / native, 2) if native else None
            entry['facade_' + key], entry['native_' + key] = round(mean('facade', key), 1), round(native, 1)
        out.append(entry)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--events', required=True)
    parser.add_argument('--fail-over-budget', action='store_true',
                        help='exit nonzero when a facade run used more LLM-visible calls than facade/CALL_BUDGET.json allows')
    args = parser.parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text())
    rows = []
    for run in manifest:
        events = load_events(args.events, run['run_id'])
        outcome, wrong_clicks = classify(run['task'], events)
        trace = scan_transcript(run['transcript'])
        calls = count_llm_visible_calls(run['transcript'])
        limit = budget_for(run['task']) if run['arm'] == 'facade' else None
        row = {
            'arm': run['arm'], 'task': run['task'], 'run_id': run['run_id'],
            'outcome': outcome, 'wrong_clicks': wrong_clicks,
            'turns': trace['turns'], 'llm_visible_calls': calls, 'call_budget': limit,
            'over_budget': limit is not None and calls > limit, 'wall_s': run.get('wall_s'),
            'cost_usd': trace['cost_usd'], 'agent_duration_ms': trace['duration_ms'],
            'model': trace['model'],
            'tokens': {'input': trace['usage'].get('input_tokens'), 'output': trace['usage'].get('output_tokens'),
                       'cache_read': trace['usage'].get('cache_read_input_tokens'),
                       'cache_write': trace['usage'].get('cache_creation_input_tokens')},
            'routes': trace['routes'], 'caller_preselected_count': trace['caller_preselected_count'],
        }
        rows.append(row)
        print(json.dumps(row))
    for entry in headline(rows):
        print(json.dumps({'headline': entry}))
    over = [r['run_id'] for r in rows if r['over_budget']]
    if over:
        print('OVER BUDGET: %s' % ', '.join(over), file=sys.stderr)
    return 1 if over and args.fail_over_budget else 0


if __name__ == '__main__':
    sys.exit(main())
