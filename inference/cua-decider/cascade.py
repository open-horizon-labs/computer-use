"""Persistent bounded selector, independent of browser and action execution.

JSON lines in/out. Each process represents one task. Never executes actions.
"""
import argparse
import hashlib
import json
import math
import sys
import time

from decision_providers import Decider, Jev, Qwen


class Cascade:
    def __init__(self, fast=None, fallback=None, *, threshold=0.95, max_fast_attempts=1):
        if not math.isfinite(threshold) or not 0 <= threshold <= 1 or max_fast_attempts < 1:
            raise ValueError('Invalid routing limits')
        self.fast = fast if fast is not None else Decider()
        self.fallback = fallback if fallback is not None else Qwen()
        self.threshold = threshold
        self.max_fast_attempts = max_fast_attempts
        self.last_fingerprint = None
        self.fast_attempts = 0
        self.escalated = False
        self.started = False

    def select(self, goal, observation, candidates, *, feedback=None, history=None):
        if not isinstance(goal, str) or not goal or not isinstance(candidates, dict):
            raise ValueError('Goal and candidate map required')
        if not 2 <= len(candidates) <= 32 or not {'reobserve', 'abstain'} <= candidates.keys():
            raise ValueError('Supply 2..32 candidates, including reobserve and abstain')
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in candidates.items()):
            raise ValueError('Candidate IDs and descriptions must be strings')
        if feedback not in (None, 'verified_progress', 'no_progress', 'failed', 'uncertain', 'safe_retry'):
            raise ValueError('Unknown feedback')
        fingerprint = hashlib.sha256(json.dumps([goal, observation, candidates], sort_keys=True).encode()).hexdigest()
        same = fingerprint == self.last_fingerprint
        if self.started:
            if feedback == 'verified_progress' and not same:
                self.fast_attempts = 0
                self.escalated = False
            elif feedback == 'safe_retry' and not same:
                pass  # Caller verified the prior attempt had no unsafe effect; retain budget.
            elif feedback != 'verified_progress' or same:
                self.escalated = True
        state = {'goal': goal, 'observation': observation, 'history': history or []}
        trace = []
        chosen = None
        reason = 'fast_confident'
        if same:
            reason = 'unchanged_observation'
        elif self.escalated:
            reason = 'progress_not_verified'
        elif self.fast_attempts >= self.max_fast_attempts:
            reason = 'fast_budget_exhausted'
        else:
            self.fast_attempts += 1
            began = time.perf_counter()
            try:
                answer = self.fast(state, candidates)
                self._validate(answer, candidates)
                confidence = answer.get('confidence')
                if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and math.isfinite(confidence) and 0 <= confidence <= 1 and confidence >= self.threshold and answer['choice'] not in ('reobserve', 'abstain'):
                    chosen = answer
                else:
                    reason = 'low_confidence_or_defer'
                trace.append({'provider': type(self.fast).__name__, 'ms': (time.perf_counter()-began)*1000, **answer})
            except Exception as exc:
                reason = 'fast_provider_error'
                trace.append({'provider': type(self.fast).__name__, 'ms': (time.perf_counter()-began)*1000, 'error': type(exc).__name__})
        route = 'fast'
        if chosen is None:
            self.escalated = True
            began = time.perf_counter()
            try:
                chosen = self.fallback(state, candidates)
                self._validate(chosen, candidates)
            except Exception as exc:
                # Fail closed without emitting upstream exception text or partial output.
                raise RuntimeError('Fallback failed; no action authorized: ' + type(exc).__name__) from None
            trace.append({'provider': type(self.fallback).__name__, 'ms': (time.perf_counter()-began)*1000, **chosen})
            route = 'fallback'
        self.last_fingerprint = fingerprint
        self.started = True
        return {'choice': chosen['choice'], 'route': route, 'reason': reason, 'requires_verification': True, 'trace': trace}

    @staticmethod
    def _validate(answer, candidates):
        if not isinstance(answer, dict) or answer.get('choice') not in candidates:
            raise ValueError('Provider returned an unapproved action ID')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fast', choices=['decider', 'jev'], default='decider')
    p.add_argument('--threshold', type=float, default=0.95)
    p.add_argument('--max-fast-attempts', type=int, default=1)
    args = p.parse_args()
    fast = Jev() if args.fast == 'jev' else Decider()
    router = Cascade(fast=fast, threshold=args.threshold, max_fast_attempts=args.max_fast_attempts)
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError('Expected JSON object')
                result = router.select(**request)
            except Exception as exc:
                result = {'error': type(exc).__name__, 'action_authorized': False}
            print(json.dumps(result), flush=True)
    finally:
        if hasattr(fast, 'close'):
            fast.close()


if __name__ == '__main__':
    main()
