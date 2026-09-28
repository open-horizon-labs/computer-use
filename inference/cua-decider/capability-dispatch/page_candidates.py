"""NuExtract-first candidate preparation; never chunks chooser comparisons.

All records belong to one caller-owned Driver snapshot. Extraction chunks are
merged before predicates run. Missing evidence remains unknown, not excluded.
"""
import json
import os
from pathlib import Path
import re
import sys
import time
from decimal import InvalidOperation

from dispatch import predicate, typed
from worker_transport import JsonWorker
from runtime_config import load_runtime_config


class NuExtractPage:
    def __init__(self, command=None, chunk_size=5, timeout=20):
        load_runtime_config()
        if not isinstance(chunk_size, int) or not 1 <= chunk_size <= 30:
            raise ValueError('chunk_size must be 1..30')
        if not 0 < timeout <= 20:
            raise ValueError('timeout must be in (0, 20]')
        self.chunk_size, self.timeout = chunk_size, timeout
        default = [sys.executable, str(Path(__file__).resolve().parents[3] / 'workers/page_extract_worker.py')]
        self.worker = JsonWorker(command if command is not None else
                                 json.loads(os.environ.get('CUA_EXTRACT_COMMAND', json.dumps(default))))

    def extract(self, request, current_snapshot):
        """Return all grounded records, or fail the entire extraction closed."""
        sid = request.get('snapshot_id')
        if not sid or sid != current_snapshot:
            raise ValueError('stale snapshot')
        fields, records = request['fields'], request['records']
        if not fields or not 1 <= len(fields) <= 12:
            raise ValueError('expected 1..12 described fields')
        if any(not isinstance(v, str) or not v for v in fields.values()):
            raise ValueError('field descriptions must be nonempty text')
        ids = [r['id'] for r in records]
        if len(set(ids)) != len(ids) or any(not i for i in ids):
            raise ValueError('duplicate or empty record IDs')
        if any(not isinstance(r['text'], str) or not r['text'] for r in records):
            raise ValueError('empty record evidence')
        began = time.monotonic()
        deadline = began + self.timeout - min(0.25, self.timeout / 4)
        all_rows, chunks = [], []
        for offset in range(0, len(records), self.chunk_size):
            batch = records[offset:offset+self.chunk_size]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('whole extraction deadline exceeded')
            start = time.monotonic()
            result = self.worker.exchange({'snapshot_id': sid, 'task': request['task'],
                                            'fields': fields, 'records': batch}, remaining)
            if result.get('error'):
                raise RuntimeError('NuExtract endpoint failure: ' + str(result['error']) + ' status=' + str(result.get('http_status')))
            if result.get('snapshot_id') != sid or result.get('model') != 'numind/NuExtract3':
                raise ValueError('wrong extraction snapshot or model')
            rows = result.get('records', [])
            source = {r['id']: r['text'] for r in batch}
            row_ids = [row['record_id'] for row in rows]
            if len(row_ids) != len(source) or set(row_ids) != set(source):
                raise ValueError('missing, duplicate or invented extraction record')
            validated = {}
            for row in rows:
                if set(row['fields']) != set(fields):
                    raise ValueError('incomplete extraction schema')
                values = {}
                for name, item in row['fields'].items():
                    if item is None:
                        values[name] = None
                    elif (isinstance(item, dict) and isinstance(item.get('value'), str)
                          and item['value'] and item.get('source_quote') == item['value']
                          and item['value'] in source[row['record_id']]):
                        values[name] = item['value']
                    else:
                        # Treat ungrounded output as missing, never manufacture confidence.
                        values[name] = None
                validated[row['record_id']] = {'record_id': row['record_id'], 'fields': values}
            all_rows.extend(validated[r['id']] for r in batch)
            chunks.append({'record_count': len(batch), 'endpoint_ms': (time.monotonic()-start)*1000})
        return {'snapshot_id': sid, 'model': 'numind/NuExtract3', 'records': all_rows,
                'chunks': chunks, 'wall_ms': (time.monotonic()-began)*1000, 'calibrated': False}

    def close(self):
        self.worker.close()


def filter_records(extracted, *, fields, predicates, coverage_complete, current_snapshot):
    """Conjunctive same-record predicates, no ranking or inferred taxonomy."""
    if not current_snapshot or extracted.get('snapshot_id') != current_snapshot:
        raise ValueError('stale extraction')
    for rule in predicates:
        # Validate criteria even if every source value is missing.
        if rule['field'] not in fields:
            raise ValueError('unknown predicate field')
        predicate(typed(rule['value'], fields[rule['field']]), rule, fields[rule['field']])
    checks, eligible, unknown, excluded = {}, [], [], []
    for row in extracted['records']:
        aid = row['record_id']
        if aid in checks:
            raise ValueError('duplicate extracted record')
        failed, gaps = [], []
        for rule in predicates:
            name, spec = rule['field'], fields[rule['field']]
            raw = row['fields'].get(name)
            try:
                if raw is None:
                    raise ValueError('missing field')
                actual, expected = typed(raw, spec), typed(rule['value'], spec)
                # Preserve the existing identity-boundary policy. A longer value
                # containing the target is ambiguous, never an automatic match.
                if (spec.get('type', 'text') == 'text' and rule.get('op', 'eq') == 'eq'
                        and actual != expected and expected
                        and re.search(r'(?<!\w)' + re.escape(expected) + r'(?!\w)', actual)):
                    gaps.append(name)
                elif not predicate(actual, rule, spec):
                    failed.append(name)
            except (ValueError, InvalidOperation, TypeError):
                gaps.append(name)
        state = 'excluded' if failed else 'unknown' if gaps else 'eligible'
        checks[aid] = {'state': state, 'failed': failed, 'gaps': gaps}
        {'eligible': eligible, 'unknown': unknown, 'excluded': excluded}[state].append(aid)
    return {'snapshot_id': current_snapshot, 'eligible_ids': eligible, 'unknown_ids': unknown,
            'excluded_ids': excluded, 'checks': checks, 'coverage_complete': coverage_complete is True,
            'complete': coverage_complete is True and not unknown}


class ExtractThenChoose:
    """Default generic wrapper. Qualified GLiNER2 and exact paths stay upstream.

    request.page_filter declares extraction fields, predicates, task, candidate
    IDs and coverage. No filter means the existing generic provider is used.
    Reporting callers can use extract/filter directly without a chooser call.
    """
    def __init__(self, extractor, generic, *, max_candidates=18, overflow=None):
        self.extractor, self.generic = extractor, generic
        self.max_candidates, self.overflow = max_candidates, overflow

    def __call__(self, step, request):
        if 'page_filter' not in request:
            return self.generic(step, request)
        if step['method'] != 'choose':
            raise ValueError('candidate preparation requires choice operation')
        spec = request['page_filter']
        actions = {a['id']: a for a in request['actions']}
        ids = spec['candidate_ids']
        if len(actions) != len(request['actions']) or len(set(ids)) != len(ids) or set(ids) != set(actions):
            raise ValueError('page filter must cover every offered action exactly once')
        if any(actions[i].get('enabled') is False or actions[i].get('operation') != request['operation'] for i in ids):
            raise ValueError('filter scope includes unavailable actions')
        descriptions = {k: v['description'] for k, v in spec['fields'].items()}
        extraction = self.extractor.extract({'snapshot_id': request['snapshot_id'], 'task': spec['task'],
            'fields': descriptions, 'records': [{'id': i, 'text': actions[i]['evidence_text']} for i in ids]},
            request['snapshot_id'])
        filtered = filter_records(extraction, fields=spec['fields'], predicates=spec['predicates'],
            coverage_complete=spec['coverage_complete'], current_snapshot=request['snapshot_id'])
        base = {'route': 'nuextract-then-choose', 'extraction': extraction, 'filter': filtered,
                'action_authorized': False, 'calibrated': False}
        if not filtered['complete'] or not filtered['eligible_ids']:
            return {**base, 'choice': 'abstain', 'reason': 'unresolved_evidence' if not filtered['complete'] else 'no_match',
                    'chooser_called': False}
        retained = filtered['eligible_ids']
        provider = self.generic if len(retained) <= self.max_candidates else self.overflow
        if provider is None:
            return {**base, 'choice': 'abstain', 'reason': 'candidate_limit_after_extraction', 'chooser_called': False}
        # These IDs/arguments are retained verbatim. Engine binds its result to
        # the original request; excluded IDs can never be reintroduced below.
        narrowed = {**request, 'actions': [actions[i] for i in retained],
                    'candidate_ids': retained, 'specialist_context': {
                        'prior': request.get('specialist_context'),
                        'page_extraction': [r for r in extraction['records'] if r['record_id'] in retained],
                        'page_filter': {'eligible_ids': retained, 'excluded_ids': filtered['excluded_ids'],
                                        'coverage_complete': True}}}
        result = provider(step, narrowed)
        if result.get('choice') not in retained + ['abstain', 'reobserve']:
            raise ValueError('chooser revived excluded or unoffered candidate')
        return {**result, **base, 'chooser_route': result.get('route', result.get('model')),
                'chooser_called': True, 'choice': result.get('choice'),
                'action_authorized': result.get('action_authorized', True) and result.get('choice') in retained}

    def close(self):
        try:
            self.extractor.close()
        finally:
            try:
                self.generic.close()
            finally:
                if self.overflow is not None and self.overflow is not self.generic:
                    self.overflow.close()
