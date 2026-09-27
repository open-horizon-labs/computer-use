"""Active-stage replay against saved requests; never controls a desktop."""
import argparse
import json
from pathlib import Path
import statistics
import time

from dispatch import request_digest
from providers import FleetGeneric, RemoteSpans
from rollout import Strangler

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / 'benchmarks/cua-capability-dispatch-2026-09-27/booking-100-119.json'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=HERE/'simulation/strangler-active-replay-2026-09-27.json')
    args = parser.parse_args()
    saved = json.loads(SOURCE.read_text())['results']
    spans = RemoteSpans()
    tasks = []
    try:
        for task in saved:
            selector = FleetGeneric()
            try:
                policy = Strangler.from_config({'gliner2': spans, 'jev': selector}, stage='active')
                records = []
                for turn, step in enumerate(task['steps']):
                    request = step['model']['request']
                    began = time.perf_counter()
                    answer = policy.decide(request, request['snapshot_id'])
                    elapsed = (time.perf_counter()-began)*1000
                    action = next((a for a in request['actions'] if a['id'] == answer.get('action_id')), None)
                    binding_valid = bool(answer.get('action_authorized')
                                         and answer.get('snapshot_id') == request['snapshot_id']
                                         and answer.get('binding_digest') == request_digest(request)
                                         and action and action.get('operation') == request.get('operation')
                                         and action.get('enabled') is not False)
                    records.append({'turn': turn, 'expected_id': step['choice'],
                                    'selected_id': answer.get('action_id'),
                                    'correct': answer.get('action_id') == step['choice'],
                                    'current_request_binding_valid': binding_valid, 'reason': answer.get('reason'),
                                    'decision_ms': elapsed})
                tasks.append({'task_ref': str(task['seed']), 'decisions': records,
                              'all_correct': bool(records) and all(r['correct'] for r in records)})
            finally:
                selector.close()
    finally:
        spans.close()
    decisions = [r for task in tasks for r in task['decisions']]
    result = {'mode': 'active specialist replay; current-request binding check; no desktop execution',
              'contract': 'described-span-match/en', 'tasks': tasks,
              'summary': {'tasks': len(tasks), 'tasks_all_correct': sum(t['all_correct'] for t in tasks),
                          'decisions': len(decisions), 'correct': sum(r['correct'] for r in decisions),
                          'binding_valid': sum(r['current_request_binding_valid'] for r in decisions),
                          'median_warm_decision_ms': statistics.median(r['decision_ms'] for r in decisions)}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result['summary']))


if __name__ == '__main__':
    main()
