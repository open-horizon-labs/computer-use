"""Fixture caller for S4; all task-specific semantics live in booking-request.json.

The existing Driver harness owns actual snapshot refs, clicks, fresh observations,
bounded attempts, and the post-task oracle. The selector never receives the oracle.
"""
import argparse
import asyncio
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from dispatch import Engine
from providers import RemoteSpans

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BENCHMARK = REPO / 'inference/benchmarks/gliner-decide-cua-2026-09-25/benchmark.py'


class ContractCaller:
    def __init__(self, contract, provider):
        self.contract = contract
        self.provider = provider
        self.engine = Engine({'gliner2': provider})
        self.selected_values = None
        self.traces = []

    def __call__(self, state, candidates):
        if state['goal'] != self.contract['goal']:
            raise ValueError('caller contract is for a different goal')
        snapshot = hashlib.sha256(json.dumps({'state': state, 'candidates': candidates}, sort_keys=True).encode()).hexdigest()
        actions = [{'id': aid, 'operation': 'click', 'role': 'button', 'description': desc,
                    'evidence_text': desc} for aid, desc in candidates.items() if aid not in ('reobserve', 'abstain')]
        request = copy.deepcopy(self.contract['request'])
        request.update(snapshot_id=snapshot, actions=actions)
        confirmations = [a for a in actions if a['description'] == self.contract['confirmation_description']]
        if confirmations:
            # Source is one explicitly scoped current heading, not the goal paragraph
            # or unrelated global page text. Fields are still extracted by GLiNER2.
            headings = []
            for line in state['observation'].splitlines():
                stripped = line.strip()
                if stripped.startswith('- heading '):
                    try:
                        text = json.JSONDecoder().raw_decode(stripped[len('- heading '):])[0]
                    except (ValueError, TypeError):
                        continue
                    if text.startswith(self.contract['confirmation_heading_prefix']):
                        headings.append(text)
            if len(confirmations) != 1 or len(headings) != 1 or self.selected_values is None:
                return {'choice': 'abstain', 'reason': 'confirmation_scope_or_identity_missing'}
            confirmations[0]['evidence_text'] = headings[0]
            request['candidate_ids'] = [confirmations[0]['id']]
            request['order_by'] = []
            request['predicates'] += [{'field': field, 'op': 'eq', 'value': value}
                                      for field, value in self.selected_values.items()]
        else:
            request['candidate_ids'] = [a['id'] for a in actions if a['description'].startswith(self.contract['candidate_prefix'])]
            fallbacks = [a['id'] for a in actions if a['description'] == self.contract['fallback_description']]
            if len(fallbacks) == 1:
                request['fallback_id'] = fallbacks[0]
        result = self.engine.decide(request, snapshot)
        self.traces.append({'request': request, 'result': result})
        selected = result.get('action_id') if result.get('action_authorized') else 'abstain'
        if selected not in candidates or result['snapshot_id'] != snapshot:
            raise ValueError('unoffered or stale selection')
        if not confirmations and selected in request['candidate_ids']:
            self.selected_values = {field: result['evidence'][selected][field][0]['text']
                                    for field in request['fields']}
        return {'choice': selected, 'provider': 's4-capability-dispatch',
                'request': request, 'decision': result, 'confidence': None}

    def close(self):
        self.provider.close()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=int, default=100)
    parser.add_argument('--count', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads((HERE/'booking-request.json').read_text())
    provider = ContractCaller(contract, RemoteSpans())
    spec = importlib.util.spec_from_file_location('capability_booking_benchmark', BENCHMARK)
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    benchmark.Jev = lambda: provider
    sys.argv = [str(BENCHMARK), '--provider', 'jev', '--start', str(args.start), '--count', str(args.count), '--output', str(args.output)]
    try:
        await benchmark.main()
    finally:
        provider.close()
    data = json.loads(args.output.read_text())
    data['metadata'].update(provider='S4 capability dispatch', model='fastino/gliner2-base-v1',
                            device='RTX 3060 Ti', request_contract=contract,
                            controller='Fixed caller contract authored by controlling LLM before execution; planner generation latency excluded',
                            inference='One batched NER request per action decision; no classification/LLM selector on this route',
                            model_choice='Derived from described short-span request; all five families covered by dispatch contract tests')
    args.output.write_text(json.dumps(data, indent=2)+'\n')
    (args.output.parent/(args.output.stem+'-evidence.json')).write_text(json.dumps(provider.traces, indent=2)+'\n')


if __name__ == '__main__':
    asyncio.run(main())
