"""CESS-governed strangler path for described English span matching.

Shadow stage returns the incumbent Jev decision while scoring the specialist on
the same current request. Active stage is refused without a recorded human
authorization, accepted CESS counterexample reference, and qualification report.
This module never executes a computer action.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re

from dispatch import Engine, Unsupported, compile_plan, request_digest


CONTRACT = 'described-span-match/en'
HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / 'ROLLOUT.json'


def applies(request):
    if request.get('kind') != 'match' or request.get('shape', 'spans') != 'spans' or request.get('language', 'en') != 'en':
        return False
    try:
        plan = compile_plan(request)
    except (Unsupported, TypeError, AttributeError):
        return False
    return plan['models'] == ['gliner2'] and bool(plan['steps'])


def _safe_summary(decision):
    return {key: decision.get(key) for key in ('status', 'action_id', 'reason', 'action_authorized', 'decision_ms', 'fallback_from')
            if key in decision and key != 'fallback_from'}


class Strangler:
    """Run one specialist cohort in shadow; make takeover an explicit reviewed step."""

    def __init__(self, providers, *, stage='shadow', promotion=None, audit_sink=None):
        if stage not in ('shadow', 'active'):
            raise ValueError('stage must be shadow or active')
        self.providers = dict(providers)
        self.stage = stage
        self.audit_sink = audit_sink
        if stage == 'active':
            required = ('authorized_by', 'accepted_ce', 'qualification_report', 'checkpoint')
            if not isinstance(promotion, dict) or any(not promotion.get(key) for key in required):
                raise ValueError('active takeover requires authority, accepted CESS CE, qualification report, and checkpoint identity')
            archive = json.loads((HERE / 'COUNTEREXAMPLES.json').read_text())
            accepted = {item['id'] for item in archive
                        if item.get('status') in ('accepted', 'approved')}
            if promotion['accepted_ce'] not in accepted:
                raise ValueError('active takeover must reference an accepted CESS counterexample')
            report = Path(promotion['qualification_report'])
            if not report.is_absolute():
                report = HERE.parents[2] / report
            if not report.is_file():
                raise ValueError('qualification report path does not exist')
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', promotion['checkpoint']):
                raise ValueError('checkpoint must use a full SHA-256 digest')
        self.promotion = promotion
        self.last_audit = None

    @classmethod
    def from_config(cls, providers, path=DEFAULT_CONFIG, *, stage=None, audit_sink=None):
        config = json.loads(path.read_text())
        if config.get('contract') != CONTRACT:
            raise ValueError('rollout config names an unsupported contract')
        return cls(providers, stage=stage or config.get('stage'), promotion=config.get('promotion'), audit_sink=audit_sink)

    def decide(self, request, current_snapshot):
        if not applies(request):
            ordinary = {k: v for k, v in self.providers.items() if k != 'incumbent_jev'}
            if 'incumbent_jev' in self.providers:
                ordinary['jev'] = self.providers['incumbent_jev']
            return Engine(ordinary).decide(request, current_snapshot)
        specialist_providers = {k: v for k, v in self.providers.items() if k != 'incumbent_jev'}
        if self.stage == 'active':
            specialist = Engine(specialist_providers).decide(request, current_snapshot)
            return {**specialist, 'rollout': {'contract': CONTRACT, 'stage': 'active'}}

        # Jev stays authoritative during shadow. The specialist sees the same
        # current candidates and criteria, but its choice cannot authorize action.
        incumbent_request = {**request, 'kind': 'semantic'}
        incumbent_provider = self.providers.get('incumbent_jev', self.providers['jev'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            incumbent_future = pool.submit(Engine({'jev': incumbent_provider}).decide, incumbent_request, current_snapshot)
            specialist_future = pool.submit(Engine(specialist_providers).decide, request, current_snapshot)
            incumbent = incumbent_future.result()
            specialist = specialist_future.result()
        if incumbent.get('action_authorized'):
            chosen = incumbent.get('action_id')
            offered = {a['id']: a for a in request.get('actions', [])}
            action = offered.get(chosen)
            if action is None or action.get('operation') != request.get('operation') or action.get('enabled') is False:
                incumbent = {**incumbent, 'status': 'defer', 'action_authorized': False,
                             'reason': 'incumbent_choice_does_not_bind_to_original_request'}
                incumbent.pop('action_id', None)
            else:
                incumbent = {**incumbent, 'binding_digest': request_digest(request)}
        event = {
            'contract': CONTRACT,
            'stage': 'shadow',
            'request_digest': hashlib.sha256(request_digest(request).encode()).hexdigest(),
            'incumbent': _safe_summary(incumbent),
            'specialist': _safe_summary(specialist),
            'agreement': incumbent.get('action_id') == specialist.get('action_id')
                         if incumbent.get('action_authorized') and specialist.get('action_authorized') else None,
            'counterexample_status': 'needs_independent_outcome_and_CESS_review'
                                     if incumbent.get('action_id') != specialist.get('action_id') else None,
        }
        self.last_audit = event
        if self.audit_sink:
            self.audit_sink(event)
        return {**incumbent, 'rollout': {'contract': CONTRACT, 'stage': 'shadow', 'specialist_observed': True}}
