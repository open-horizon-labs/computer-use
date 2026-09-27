"""Live adapter for the qualified short-span experiment; other adapters are injectable."""
import json
import os
import subprocess
import threading
from pathlib import Path


def span_schema(descriptions):
    """Raw-schema equivalent of GLiNER2.create_schema().entities(descriptions).

    Raw entities values are not descriptions. The documented Schema builder
    stores descriptions separately; preserve that upstream wire contract.
    """
    return {'entities': {name: '' for name in descriptions},
            'entity_descriptions': dict(descriptions)}


class RemoteSpans:
    def __init__(self, model='fastino/gliner2-base-v1'):
        if model not in ('fastino/gliner2-base-v1', 'fastino/gliner2.5-multi-v1'):
            raise ValueError('unregistered checkpoint')
        self.model = model
        command = json.loads(os.environ.get('CUA_SPAN_COMMAND', '[]'))
        if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
            raise ValueError('Set CUA_SPAN_COMMAND to a JSON argv array for workers/span_worker.py; model ID is appended')
        self.process = subprocess.Popen(command + [model], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.lock = threading.Lock()
        self.ready = json.loads(self.process.stdout.readline())
        if not self.ready.get('ready') or self.ready.get('model') != model:
            raise RuntimeError('wrong or unavailable extractor')

    def __call__(self, step, request):
        if step['method'] != 'extract' or step['shape'] not in ('spans', 'long_spans'):
            raise ValueError('this adapter only supports separately scoped spans; record/relationship adapter required')
        actions = {a['id']: a for a in request['actions']}
        ids = request['candidate_ids']
        if not ids:
            return {'evidence': {}, 'model': self.model, 'inference_ms': 0}
        fields = {k: v.get('description') or k for k, v in step['fields'].items()}
        texts = [actions[aid]['evidence_text'] for aid in ids]
        with self.lock:
            self.process.stdin.write(json.dumps({'texts': texts, 'schemas': [span_schema(fields) for _ in ids]}) + '\n')
            self.process.stdin.flush()
            raw = json.loads(self.process.stdout.readline())
        if raw.get('error') or len(raw.get('results', [])) != len(ids):
            raise ValueError('incomplete extraction batch')
        evidence = {aid: result.get('entities', {}) for aid, result in zip(ids, raw['results'])}
        return {'evidence': evidence, 'model': self.model, 'inference_ms': raw['inference_ms']}

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


class FleetGeneric:
    """One installed Jev -> Qwen selector process per simulated or real task."""
    def __init__(self):
        launcher = Path.home()/'.local/share/fleet-cua-decider/select-fleet'
        command = json.loads(os.environ.get('CUA_SELECTOR_COMMAND', json.dumps([str(launcher), '--fast', 'jev'])))
        if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
            raise ValueError('CUA_SELECTOR_COMMAND must be a nonempty JSON argv array')
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)

    def __call__(self, step, request):
        if step['method'] != 'choose':
            raise ValueError('generic adapter requires choice operation')
        actions = {a['id']: a.get('description', a.get('evidence_text', a.get('name', '')))
                   for a in request['actions']}
        actions.update(reobserve='Observe again; do not act on unresolved evidence',
                       abstain='Stop when no safe authorized choice is supported')
        context = {k: request[k] for k in ('fields', 'predicates', 'order_by', 'candidate_ids', 'coverage_complete', 'fallback_id', 'specialist_context') if k in request}
        goal = request.get('goal', 'Choose the unique action satisfying all caller criteria and ordering. Use the supplied fallback only when every candidate is excluded; defer on unresolved evidence or ties.') + '\nCaller criteria and existing evidence: ' + json.dumps(context)
        payload = {'goal': goal, 'observation': request.get('observation', ''), 'candidates': actions,
                   'history': request.get('history', [])}
        if request.get('feedback'):
            payload['feedback'] = request['feedback']
        self.process.stdin.write(json.dumps(payload)+'\n'); self.process.stdin.flush()
        result = json.loads(self.process.stdout.readline())
        if result.get('choice') in ('reobserve', 'abstain'):
            result['action_authorized'] = False
        return result

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait()
