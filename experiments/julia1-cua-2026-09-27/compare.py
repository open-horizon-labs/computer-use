"""Paired Julia-1 vs saved Jev/GLiNER2 outcomes; no desktop actions."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'inference/cua-decider/capability-dispatch'))
from simulation import corpus


HISTORICAL = ROOT / 'inference/benchmarks/cua-capability-dispatch-2026-09-27/booking-100-119.json'
BASELINE = ROOT / 'inference/cua-decider/capability-dispatch/simulation/strangler-shadow-trial-2026-09-27.json'
OUTPUT = HERE / 'RESULTS.json'
SIMULATION_CASES = {
    'SIM-001-default-jev', 'SIM-002-unavailable-specialist',
    'SIM-005-healthy-specialist', 'SIM-021-product-prices',
}


def candidate_map(request):
    return {action['id']: action.get('description', action.get('evidence_text', action.get('name', '')))
            for action in request['actions']}


def model_query(case_id, request, source_state=None):
    context = {key: request[key] for key in (
        'fields', 'predicates', 'order_by', 'candidate_ids', 'coverage_complete',
        'fallback_id', 'specialist_context') if key in request}
    source_state = source_state or {
        'goal': request.get('goal', ''),
        'observation': request.get('observation', ''),
        'history': request.get('history', []),
    }
    goal = source_state.get('goal') or request.get(
        'goal',
        'Choose the unique action satisfying all caller criteria and ordering. '
        'Use the supplied fallback only when every candidate is excluded; defer '
        'on unresolved evidence or ties.')
    instructions = goal + '\nCaller criteria and existing evidence: ' + json.dumps(context, ensure_ascii=False)
    criteria = candidate_map(request)
    criteria.update({
        'reobserve': 'Observe again; do not act on unresolved evidence',
        'abstain': 'Stop when no safe authorized choice is supported',
    })
    # Preserve the same original goal, accessibility snapshot, and history the
    # CUA selector saw. Julia receives caller criteria in the question, while
    # the complete UI evidence remains in state as its API expects.
    state = dict(source_state)
    return {'id': case_id, 'state': state, 'instructions': instructions, 'criteria': criteria}


def load_cases():
    baseline = json.loads(BASELINE.read_text())
    baseline_rows = {row['id']: row for row in baseline['results']}
    cases = []
    for item in corpus():
        if item['id'] in SIMULATION_CASES:
            request = item['frames'][0]['request']
            state = {key: request[key] for key in ('goal', 'observation', 'history') if key in request}
            cases.append((item['id'], request, item['approved']['effects'][0], None, state))
    for task in json.loads(HISTORICAL.read_text())['results']:
        for turn, step in enumerate(task['steps']):
            cases.append((f"booking-{task['seed']}-{turn}", step['model']['request'], step['choice'],
                          str(task['seed']), step['state']))
    if {case[0] for case in cases} != set(baseline_rows):
        raise ValueError('Evaluation requests do not exactly match the paired Jev/GLiNER2 baseline')
    return cases, baseline_rows, baseline


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def aggregate(rows):
    def metrics(arm_rows):
        values = [row['latency_ms'] for row in arm_rows]
        return {
            'correct': sum(row['correct'] for row in arm_rows),
            'total': len(arm_rows),
            'accuracy': sum(row['correct'] for row in arm_rows) / len(arm_rows) if arm_rows else None,
            'median_ms': statistics.median(values) if values else None,
            'p95_ms': percentile(values, .95) if values else None,
        }

    result = {'all_39': metrics(rows)}
    for kind in sorted({row['request_kind'] for row in rows}):
        result[f'kind_{kind}'] = metrics([row for row in rows if row['request_kind'] == kind])
    booking = [row for row in rows if row['task_ref'] is not None]
    result['booking_35'] = metrics(booking)
    tasks = {}
    for row in booking:
        tasks.setdefault(row['task_ref'], []).append(row)
    result['booking_tasks_all_steps_correct'] = sum(all(item['correct'] for item in group)
                                                    for group in tasks.values())
    return result


def main():
    command_text = os.environ.get('JULIA_WORKER_COMMAND', '')
    if not command_text:
        raise SystemExit('Set JULIA_WORKER_COMMAND to the JSON argv for the remote Julia worker')
    command = json.loads(command_text)
    if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
        raise SystemExit('JULIA_WORKER_COMMAND must be a nonempty JSON argv array')

    cases, baseline, _baseline_file = load_cases()
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, bufsize=1)
    rows = []
    try:
        ready_line = process.stdout.readline()
        ready = json.loads(ready_line)
        if not ready.get('ready') or ready.get('weights_sha256') != 'df853bf7fe424420011f3d0c47a05d7341aa9eefa7fb9f203ea4aada4ad95b72':
            raise RuntimeError('Julia worker did not prove readiness with the expected checkpoint hash')
        print(json.dumps({'worker_ready': True, 'load_ms': ready['load_ms'],
                          'gpu': ready['gpu'], 'engine': ready['engine']}), flush=True)
        for case_id, request, expected, task_ref, source_state in cases:
            payload = model_query(case_id, request, source_state)
            began = time.perf_counter()
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + '\n')
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            roundtrip_ms = (time.perf_counter() - began) * 1000
            if response.get('error'):
                raise RuntimeError(f"Julia worker failed for {case_id}: {response['error']}")
            if response.get('id') != case_id:
                raise RuntimeError('Julia worker response ID mismatch')
            recorded = baseline[case_id]
            jev_decision = recorded['arms']['jev_only']['decision']
            specialist_decision = recorded['arms']['capability']['decision']
            result = {
                'id': case_id,
                'task_ref': task_ref,
                'request_kind': request.get('kind', 'semantic'),
                'expected_action_id': expected,
                'julia_action_id': response['choice'],
                'julia_correct': response['choice'] == expected,
                'julia_confidence': response['max_probability'],
                'julia_inference_ms': response['inference_ms'],
                'julia_roundtrip_ms': roundtrip_ms,
                'encoded_tokens': response['encoded_tokens'],
                'option_tokens': response['option_tokens'],
                'jev_action_id': jev_decision.get('action_id'),
                'jev_correct': recorded['arms']['jev_only']['correct'],
                'jev_ms': recorded['arms']['jev_only']['ms'],
                'gliner2_dispatch_action_id': specialist_decision.get('action_id'),
                'gliner2_dispatch_correct': recorded['arms']['capability']['correct'],
                'gliner2_dispatch_ms': recorded['arms']['capability']['ms'],
            }
            rows.append(result)
            print(json.dumps({'id': case_id, 'julia_correct': result['julia_correct'],
                              'julia_ms': round(roundtrip_ms, 2),
                              'jev_correct': result['jev_correct'],
                              'gliner2_correct': result['gliner2_dispatch_correct']}), flush=True)
        data = {
            'mode': 'paired finite-choice Julia screen over fixed saved CUA requests; no desktop actions',
            'model': ready,
            'protocol': {
                'cases': len(rows),
                'options': 'action IDs/descriptions plus reobserve and abstain; no expected answers passed to Julia',
                'typed_match_context': 'caller fields, predicates, ordering, candidate scope and fallback only',
                'baseline': 'same request IDs and expected action IDs from strangler-shadow-trial-2026-09-27.json',
                'limits': 'reused development booking fixture; steps are correlated; no held-out live Driver task',
            },
            'summary': {
                'julia': aggregate([{'correct': row['julia_correct'], 'latency_ms': row['julia_roundtrip_ms'],
                                     'request_kind': row['request_kind'], 'task_ref': row['task_ref']} for row in rows]),
                'jev': aggregate([{'correct': row['jev_correct'], 'latency_ms': row['jev_ms'],
                                   'request_kind': row['request_kind'], 'task_ref': row['task_ref']} for row in rows]),
                'gliner2_dispatch': aggregate([{'correct': row['gliner2_dispatch_correct'],
                                                'latency_ms': row['gliner2_dispatch_ms'],
                                                'request_kind': row['request_kind'], 'task_ref': row['task_ref']} for row in rows]),
                'julia_model_load_ms': ready['load_ms'],
                'julia_warm_median_inference_ms_excluding_first': statistics.median(
                    row['julia_inference_ms'] for row in rows[1:]),
            },
            'results': rows,
        }
        OUTPUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
        print(json.dumps(data['summary'], indent=2), flush=True)
    finally:
        if process.poll() is None:
            process.stdin.close()
            process.wait(timeout=15)


if __name__ == '__main__':
    main()
