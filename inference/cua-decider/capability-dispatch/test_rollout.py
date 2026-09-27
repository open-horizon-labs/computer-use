"""Adversarial checks for the CESS governed specialist strangler."""
import copy
import unittest

from rollout import Strangler, applies
from simulation import stock
from dispatch import execute_bound, request_digest


class StranglerChecks(unittest.TestCase):
    def setUp(self):
        self.request, self.evidence = stock()
        self.calls = []
        def jev(step, request):
            self.calls.append('jev')
            return {'choice': 'a'}
        def extract(step, request):
            self.calls.append('gliner2')
            return self.evidence
        self.providers = {'jev': jev, 'incumbent_jev': jev, 'gliner2': extract}

    def test_shadow_observes_specialist_but_returns_bound_incumbent(self):
        events = []
        result = Strangler(self.providers, audit_sink=events.append).decide(self.request, 's1')
        self.assertEqual(result['action_id'], 'a')
        self.assertEqual(result['binding_digest'], request_digest(self.request))
        self.assertEqual(events[0]['incumbent']['action_id'], 'a')
        self.assertEqual(events[0]['specialist']['action_id'], 'b')
        self.assertFalse(events[0]['agreement'])
        self.assertEqual(events[0]['counterexample_status'], 'needs_independent_outcome_and_CESS_review')
        self.assertEqual(set(self.calls), {'jev', 'gliner2'})

    def test_shadow_result_is_executable_only_against_original_binding(self):
        result = Strangler(self.providers).decide(self.request, 's1')
        executed = []
        execute_bound(self.request, result, 's1', lambda op, args: executed.append((op, args)))
        changed = copy.deepcopy(self.request)
        changed['actions'][0]['arguments']['target'] = 'mutated'
        with self.assertRaises(ValueError):
            execute_bound(changed, result, 's1', lambda *_: self.fail('must not execute'))

    def test_only_described_english_span_matching_enters_cohort(self):
        self.assertTrue(applies(self.request))
        semantic = copy.deepcopy(self.request); semantic['kind'] = 'semantic'
        self.assertFalse(applies(semantic))
        structured = copy.deepcopy(self.request); structured['shape'] = 'records'
        self.assertFalse(applies(structured))

    def test_repo_config_activates_only_the_qualified_contract(self):
        policy = Strangler.from_config(self.providers)
        self.assertEqual(policy.stage, 'active')
        self.assertTrue(applies(self.request))

    def test_active_takeover_requires_explicit_review_record(self):
        with self.assertRaises(ValueError):
            Strangler(self.providers, stage='active')

    def test_active_rejects_unknown_ce_or_missing_report(self):
        with self.assertRaisesRegex(ValueError, 'accepted CESS counterexample'):
            Strangler(self.providers, stage='active', promotion={
                'authorized_by': 'user', 'accepted_ce': 'CE-INVENTED',
                'qualification_report': 'README.md', 'checkpoint': 'sha256:' + 'a' * 64})
        with self.assertRaisesRegex(ValueError, 'qualification report'):
            Strangler(self.providers, stage='active', promotion={
                'authorized_by': 'user', 'accepted_ce': 'CE-CAP-001',
                'qualification_report': 'missing.md', 'checkpoint': 'sha256:' + 'a' * 64})

    def test_active_uses_specialist_and_keeps_jev_only_for_recovery(self):
        promotion = {'authorized_by': 'user', 'accepted_ce': 'CE-CAP-001',
                     'qualification_report': 'experiments/decide-precision-2026-09-27/RESULTS.md',
                     'checkpoint': 'sha256:' + 'a' * 64}
        result = Strangler(self.providers, stage='active', promotion=promotion).decide(self.request, 's1')
        self.assertEqual(result['action_id'], 'b')
        self.assertEqual(result['rollout']['stage'], 'active')
        self.assertEqual(self.calls, ['gliner2'])

    def test_active_incomplete_scope_consults_jev_but_still_defers(self):
        promotion = {'authorized_by': 'user', 'accepted_ce': 'CE-CAP-001',
                     'qualification_report': 'experiments/decide-precision-2026-09-27/RESULTS.md',
                     'checkpoint': 'sha256:' + 'a' * 64}
        request = {**self.request, 'coverage_complete': False}
        result = Strangler(self.providers, stage='active', promotion=promotion).decide(request, 's1')
        self.assertFalse(result['action_authorized'])
        self.assertEqual(result['reason'], 'generic_choice_cannot_resolve_missing_authority_or_scope')
        self.assertEqual(self.calls, ['gliner2', 'jev'])


if __name__ == '__main__':
    unittest.main()
