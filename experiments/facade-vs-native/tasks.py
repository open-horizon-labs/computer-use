"""Task manifest loading and event-log classification for the eval suite.

Outcomes come only from the fixture server's event log. Rules (see PREREGISTRATION.md):
any forbidden event -> wrong; all expected events in order -> correct; some -> partial;
none -> timeout if the agent timed out, else no-action.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_PATH = HERE / 'tasks.json'
MODELS = {'sonnet': 'claude-sonnet-5-5', 'haiku': 'claude-haiku-4-5-20251001', 'opus': 'claude-opus-5-5'}


def load_tasks(path=TASKS_PATH):
    return {t['id']: t for t in json.loads(Path(path).read_text())['tasks']}


def select_tasks(tasks, names=None, suite='core'):
    if names:
        missing = [n for n in names if n not in tasks]
        if missing:
            raise SystemExit('unknown task(s): %s' % ', '.join(missing))
        return list(names)
    return [i for i, t in tasks.items() if suite in t['suites']]


def _matches(spec, event):
    if event.get('action') != spec['action']:
        return False
    if 'id' in spec and spec['id'] != '*' and event.get('id') != spec['id']:
        return False
    if 'id_not' in spec and event.get('id') in spec['id_not']:
        return False
    if 'values' in spec and (event.get('values') or {}) != spec['values']:
        return False
    if 'unless_values' in spec and (event.get('values') or {}) == spec['unless_values']:
        return False
    return True


def forbidden_events(task, events):
    return [e for e in events if any(_matches(s, e) for s in task['forbidden'])]


def expected_progress(task, events):
    """Number of expected events matched in order (subsequence)."""
    want, done = task['expected'], 0
    for e in events:
        if done < len(want) and _matches(want[done], e):
            done += 1
    return done


def classify(task, events, timed_out=False):
    """Return (outcome, wrong_clicks)."""
    events = sorted(events, key=lambda e: e.get('ts', 0))
    wrong = len(forbidden_events(task, events))
    if wrong:
        return 'wrong', wrong
    done = expected_progress(task, events)
    if done == len(task['expected']):
        return 'correct', 0
    if done:
        return 'partial', 0
    return ('timeout' if timed_out else 'no-action'), 0
