"""Replaceable S4 projection: typed requests -> evidence plan -> bound action.

No application vocabulary or provider-specific inference is part of the matcher.
Providers implement a normalized, source-grounded evidence contract.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
import time


class Unsupported(ValueError):
    pass


def request_digest(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True, allow_nan=False).encode()).hexdigest()


def valid_probability(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1


def compile_plan(request):
    kind = request.get('kind', 'semantic')
    if kind == 'auto':
        kind = 'semantic'
    if request.get('visual_only') and kind != 'exact':
        raise Unsupported('visual-only evidence requires controller/qualified visual path')
    if kind == 'exact':
        return {'steps': [], 'reducer': 'exact', 'models': []}
    if kind == 'semantic':
        return {'steps': [{'model': 'jev', 'method': 'choose'}],
                'reducer': 'offered_choice', 'models': ['jev']}
    if kind == 'classify':
        if not request.get('labels') or not request.get('label_actions'):
            raise Unsupported('classification requires described classes and caller action mapping')
        return {'steps': [{'model': 'decide', 'method': 'classify'}],
                'reducer': 'class_to_action', 'models': ['decide']}
    if kind != 'match':
        raise Unsupported('unknown semantic request kind')
    if request.get('visual_only'):
        raise Unsupported('visual-only evidence requires controller/qualified visual path')
    fields = request.get('fields', {})
    if not fields or not (request.get('predicates') or request.get('order_by')):
        raise Unsupported('match requires caller fields and predicates or ordering')
    span_fields = {k: v for k, v in fields.items() if 'labels' not in v}
    steps = []
    if span_fields:
        shape = request.get('shape', 'spans')
        if shape not in ('spans', 'records', 'relations', 'long_spans'):
            raise Unsupported('unsupported evidence shape')
        if shape != 'spans' or request.get('language', 'en') != 'en':
            model = 'gliner2.5'
        elif any(v.get('description') for v in span_fields.values()):
            model = 'gliner2'
        else:
            model = 'gliner'
        steps.append({'model': model, 'method': 'extract', 'fields': span_fields,
                      'shape': shape, 'language': request.get('language', 'en')})
    for field, spec in fields.items():
        if 'labels' in spec:
            steps.append({'model': 'decide', 'method': 'classify_records',
                          'field': field, 'labels': spec['labels']})
    return {'steps': steps, 'reducer': 'match',
            'models': list(dict.fromkeys(s['model'] for s in steps))}


def typed(value, spec):
    kind = spec.get('type', 'text')
    text = re.sub(r'\s+', ' ', str(value)).strip()
    if kind == 'text':
        return text.casefold()
    if kind == 'time':
        match = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*(AM|PM)', text, re.I)
        if match:
            hour, minute, meridiem = int(match[1]), int(match[2] or 0), match[3].upper()
            if not (1 <= hour <= 12 and 0 <= minute < 60):
                raise ValueError('invalid clock time')
            return (hour % 12 + (12 if meridiem == 'PM' else 0)) * 60 + minute
        match = re.fullmatch(r'(\d{1,2}):(\d{2})', text)
        if match and 0 <= int(match[1]) < 24 and 0 <= int(match[2]) < 60:
            return int(match[1]) * 60 + int(match[2])
        raise ValueError('unsupported clock time')
    if kind == 'duration_minutes':
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*[- ]?\s*(minutes?|mins?|hours?|hrs?)', text, re.I)
        if not match:
            raise ValueError('missing or unsupported duration unit')
        return Decimal(match[1]) * (60 if match[2].lower().startswith('h') else 1)
    if kind == 'money':
        if spec.get('currency') != 'USD':
            raise ValueError('unsupported currency')
        if not isinstance(value, (int, float)):
            match = re.fullmatch(r'(?:\$|USD\s*)(\d+(?:\.\d+)?)', text)
            if not match:
                raise ValueError('missing or unsupported currency unit')
            text = match[1]
    elif kind != 'number':
        raise ValueError('unsupported field type')
    number = Decimal(text)
    if not number.is_finite():
        raise ValueError('non-finite number')
    return number


PREDICATE_OPS = ('eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'contains', 'not_contains')


def predicate(actual, rule, spec):
    op = rule.get('op', 'eq')
    op = 'neq' if op == 'ne' else op  # 'ne' is a discoverable alias for 'neq'
    if op not in PREDICATE_OPS:
        raise Unsupported('unsupported predicate op ' + repr(rule.get('op')) + '; allowed ops: ' + ', '.join(PREDICATE_OPS))
    if op in ('gt', 'gte', 'lt', 'lte') and spec.get('type', 'text') == 'text':
        # Text is compared as displayed (S4.8); lexicographic ordering of strings
        # like "9 min" vs "30 min" is a silent wrong answer, so refuse it.
        raise Unsupported('ordering ops gt/gte/lt/lte apply only to typed number/money/time/duration fields; text fields support eq, neq, contains, not_contains')
    if op in ('contains', 'not_contains'):
        # Text-only: a substring match on a coerced number/money hides unit and
        # precision errors instead of raising them. typed() already casefolds
        # and whitespace-normalizes text for both sides.
        if spec.get('type', 'text') != 'text':
            raise Unsupported('contains/not_contains apply only to text fields; use eq/neq/gt/gte/lt/lte for number, money, time or duration fields')
        expected = typed(rule['value'], spec)
        return (expected in actual) if op == 'contains' else (expected not in actual)
    expected = typed(rule['value'], spec)
    operations = {'eq': lambda: actual == expected, 'neq': lambda: actual != expected,
                  'gt': lambda: actual > expected, 'gte': lambda: actual >= expected,
                  'lt': lambda: actual < expected, 'lte': lambda: actual <= expected}
    return operations[op]()


def reduce_match(request, evidence, boundary_recheck=False):
    actions = {a['id']: a for a in request['actions']}
    fields = request['fields']
    rules = request.get('predicates', [])
    rank = request.get('order_by', [])
    needed = {r['field'] for r in rules + rank}
    if not request.get('coverage_complete'):
        return {'status': 'defer', 'reason': 'scope_incomplete'}
    candidates = request['candidate_ids']
    if len(set(candidates)) != len(candidates) or any(a not in actions for a in candidates):
        raise ValueError('candidate IDs must be distinct and currently offered')
    trace, eligible, unknown = {}, [], []
    for aid in candidates:
        action = actions[aid]
        if action.get('operation') != request['operation'] or action.get('enabled') is False:
            trace[aid] = {'state': 'excluded', 'reason': 'wrong_operation_or_disabled'}
            continue
        values, gaps = {}, []
        for field in needed:
            spec = fields[field]
            found = set()
            for span in evidence.get(aid, {}).get(field, []):
                confidence = span.get('confidence', 0)
                if not valid_probability(confidence) or confidence < spec.get('min_confidence', 0.35):
                    continue
                if 'labels' in spec:
                    if span.get('kind') != 'class' or span.get('text') not in spec['labels']:
                        continue
                else:
                    source = action['evidence_text']
                    start, end = span.get('start'), span.get('end')
                    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(source):
                        continue
                    if source[start:end] != span.get('text'):
                        continue
                try:
                    found.add(typed(span['text'], spec))
                except (ValueError, InvalidOperation):
                    continue
            if len(found) == 1:
                values[field] = next(iter(found))
            else:
                gaps.append(field)
        # Approved CE-SIM-006: overlap never equals a match; it can only
        # make boundary evidence uncertain for generic recheck.
        if boundary_recheck:
            for rule in rules:
                field = rule['field']
                if field not in values or fields[field].get('type', 'text') != 'text' or rule.get('op', 'eq') != 'eq':
                    continue
                expected = typed(rule['value'], fields[field])
                actual = values[field]
                if expected and actual != expected and re.search(r'(?<!\w)'+re.escape(expected)+r'(?!\w)', actual):
                    values.pop(field)
                    gaps.append(field)
        failed = any(r['field'] in values and not predicate(values[r['field']], r, fields[r['field']]) for r in rules)
        state = 'excluded' if failed else ('unknown' if gaps else 'eligible')
        trace[aid] = {'state': state, 'values': {k: str(v) for k, v in values.items()}, 'gaps': gaps}
        if state == 'unknown':
            unknown.append(aid)
        if state == 'eligible':
            eligible.append((aid, values))
    if unknown:
        return {'status': 'defer', 'reason': 'incomplete_or_conflicting_evidence', 'checks': trace}
    if not eligible:
        fallback = request.get('fallback_id')
        if fallback in actions and actions[fallback].get('operation') == request['operation'] and actions[fallback].get('enabled') is not False:
            return {'status': 'selected', 'action_id': fallback, 'reason': 'explicit_fallback', 'checks': trace}
        return {'status': 'defer', 'reason': 'no_match', 'checks': trace}
    for ordering in reversed(rank):
        if ordering.get('direction', 'asc') not in ('asc', 'desc'):
            raise Unsupported('invalid ordering direction')
        eligible.sort(key=lambda x: x[1][ordering['field']], reverse=ordering.get('direction') == 'desc')
    key = lambda row: tuple(row[1][r['field']] for r in rank)
    if len(eligible) > 1 and key(eligible[0]) == key(eligible[1]):
        return {'status': 'defer', 'reason': 'tied_matches', 'checks': trace}
    return {'status': 'selected', 'action_id': eligible[0][0], 'reason': 'unique_match', 'checks': trace}


class Engine:
    def __init__(self, providers, *, boundary_recheck=True):
        """providers maps model family to callable(step, request) -> normalized output."""
        self.providers = providers
        self.boundary_recheck = boundary_recheck

    def decide(self, request, current_snapshot):
        began = time.perf_counter()
        try:
            binding = request_digest(request)
        except (ValueError, TypeError):
            return {'status': 'defer', 'action_authorized': False, 'reason': 'invalid_request_encoding'}
        primary = self._decide_once(request, current_snapshot)
        primary['binding_digest'] = binding
        recoverable = {'provider_unavailable', 'provider_failed', 'classification_unaccepted',
                       'incomplete_or_conflicting_evidence', 'tied_matches', 'scope_incomplete',
                       'exact_target_not_unique'}
        if (primary.get('status') != 'defer' or primary.get('reason') not in recoverable
                or request.get('kind', 'semantic') in ('auto', 'semantic') or 'jev' not in self.providers):
            return primary
        checks = primary.get('checks', {})
        allowed = []
        for action in request['actions']:
            aid = action['id']
            if action.get('operation') != request['operation'] or action.get('enabled') is False:
                continue
            if checks.get(aid, {}).get('state') == 'excluded':
                continue
            if request.get('kind') == 'match' and aid not in request['candidate_ids']:
                continue
            if request.get('kind') == 'exact' and not all(action.get(k) == v for k, v in request['target'].items()):
                continue
            if request.get('kind') == 'classify' and aid not in request['label_actions'].values():
                continue
            allowed.append(action)
        if not allowed:
            return primary
        generic_request = {**request, 'kind': 'semantic', 'actions': allowed,
                           'specialist_context': {'reason': primary['reason'], 'checks': checks,
                                                  'evidence': primary.get('evidence', {})}}
        fallback = self._decide_once(generic_request, current_snapshot)
        if primary['reason'] in ('tied_matches', 'scope_incomplete') and fallback.get('action_authorized'):
            fallback = {**fallback, 'status': 'defer', 'action_authorized': False,
                        'reason': 'generic_choice_cannot_resolve_missing_authority_or_scope'}
            fallback.pop('action_id', None)
        return {**fallback, 'binding_digest': binding, 'fallback_from': primary,
                'decision_ms': (time.perf_counter()-began)*1000}

    def _decide_once(self, request, current_snapshot):
        began = time.perf_counter()
        base = {'snapshot_id': request.get('snapshot_id'), 'action_authorized': False}
        if request.get('snapshot_id') != current_snapshot or not current_snapshot:
            return {**base, 'status': 'defer', 'reason': 'stale_snapshot'}
        try:
            actions = {a['id']: a for a in request['actions']}
            if len(actions) != len(request['actions']):
                raise ValueError('duplicate action IDs')
            plan = compile_plan(request)
            base['plan'] = plan
            if plan['reducer'] == 'exact':
                ids = [a['id'] for a in request['actions'] if a.get('operation') == request['operation'] and a.get('enabled') is not False
                       and all(a.get(k) == v for k, v in request['target'].items())]
                result = {'status': 'selected', 'action_id': ids[0], 'reason': 'exact_control'} if len(ids) == 1 else {'status': 'defer', 'reason': 'exact_target_not_unique'}
            else:
                unavailable = [m for m in plan['models'] if m not in self.providers]
                available_steps = [s for s in plan['steps'] if s['model'] in self.providers]
                if not available_steps:
                    return {**base, 'status': 'defer', 'reason': 'provider_unavailable', 'unavailable': unavailable}
                # Independent extraction/classification steps; same current row IDs.
                outputs, errors = [], []
                with ThreadPoolExecutor(max_workers=len(available_steps)) as pool:
                    futures = [pool.submit(self.providers[s['model']], s, request) for s in available_steps]
                    for step, future in zip(available_steps, futures):
                        try:
                            outputs.append(future.result())
                        except Exception as exc:
                            errors.append({'model': step['model'], 'error': type(exc).__name__})
                base['provider_outputs'] = outputs
                if errors:
                    base['provider_errors'] = errors
                if unavailable:
                    base['unavailable'] = unavailable
                if not outputs:
                    return {**base, 'status': 'defer', 'reason': 'provider_failed'}
                if plan['reducer'] == 'match':
                    evidence = {}
                    for output in outputs:
                        for aid, fields in output['evidence'].items():
                            if aid not in request['candidate_ids']:
                                raise ValueError('provider invented record ID')
                            for field, spans in fields.items():
                                evidence.setdefault(aid, {}).setdefault(field, []).extend(spans)
                    result = (reduce_match(request, evidence, boundary_recheck=True)
                              if self.boundary_recheck else reduce_match(request, evidence))
                    base['evidence'] = evidence
                elif plan['reducer'] == 'class_to_action':
                    output = outputs[0]
                    label = output.get('label')
                    confidence = output.get('confidence', 0)
                    if label not in request['labels'] or not valid_probability(confidence) or confidence < request['min_confidence']:
                        result = {'status': 'defer', 'reason': 'classification_unaccepted'}
                    else:
                        result = {'status': 'selected', 'action_id': request['label_actions'].get(label), 'reason': 'mapped_class'}
                else:
                    output = outputs[0]
                    result = {'status': 'selected', 'action_id': output.get('choice'), 'reason': 'semantic_choice'} if output.get('action_authorized', True) else {'status': 'defer', 'reason': 'semantic_unaccepted'}
            if result['status'] == 'selected':
                aid = result.get('action_id')
                if aid not in actions or actions[aid].get('operation') != request['operation'] or actions[aid].get('enabled') is False:
                    result = {'status': 'defer', 'reason': 'unoffered_or_wrong_operation'}
                else:
                    result['action_authorized'] = True
            return {**base, **result, 'decision_ms': (time.perf_counter()-began)*1000}
        except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
            return {**base, 'status': 'defer', 'reason': 'invalid_contract_or_evidence', 'error': type(exc).__name__}
        except Exception as exc:
            return {**base, 'status': 'defer', 'reason': 'provider_failed', 'error': type(exc).__name__}


def execute_bound(request, selection, current_snapshot, execute):
    """Driver adapter owns live observation, actual arguments and post-action verification."""
    if not selection.get('action_authorized') or selection.get('snapshot_id') != current_snapshot or request['snapshot_id'] != current_snapshot:
        raise ValueError('not authorized for current snapshot')
    if selection.get('binding_digest') != request_digest(request):
        raise ValueError('request or execution arguments changed after selection')
    action = next(a for a in request['actions'] if a['id'] == selection['action_id'])
    if action.get('operation') != request['operation'] or action.get('enabled') is False:
        raise ValueError('wrong operation')
    return execute(action['operation'], action['arguments'])
