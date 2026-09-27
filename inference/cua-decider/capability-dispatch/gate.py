"""CESS deterministic gate and mutation evidence; semantic sketch review is separate."""
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import dispatch
import test_dispatch

HERE = Path(__file__).resolve().parent


def run(names=None):
    suite = (unittest.TestSuite(test_dispatch.DispatchGates(name) for name in names) if names
             else unittest.defaultTestLoader.loadTestsFromTestCase(test_dispatch.DispatchGates))
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    return {'passed': result.wasSuccessful(), 'tests': result.testsRun,
            'failures': len(result.failures), 'errors': len(result.errors), 'log': output.getvalue()}


def main():
    baseline = run()
    mutations = {}
    with patch.object(test_dispatch, 'compile_plan', lambda r: {'models': ['gliner2']}):
        bad = run(['test_ce_cap_002_complete_request_taxonomy'])
        mutations['always_gliner2'] = {'rejected': not bad['passed'], **bad}
    for label, chooser in [('first_candidate', lambda r: r['candidate_ids'][0]),
                           ('always_fallback', lambda r: r['fallback_id'])]:
        def wrong(request, evidence, chooser=chooser):
            return {'status': 'selected', 'action_id': chooser(request), 'reason': 'wrong_patch'}
        with patch.object(dispatch, 'reduce_match', wrong):
            bad = run(['test_ce_cap_001_extract_then_compare'])
            mutations[label] = {'rejected': not bad['passed'], **bad}
    request = test_dispatch.example()
    trace = dispatch.Engine({'gliner2': lambda s, r: {'evidence': test_dispatch.spans(r)}}).decide(request, 'now')
    result = {'baseline': baseline, 'mutations': mutations,
              'regression_case': {'id': 'CE-CAP-001', 'request': request, 'observed': trace,
                                  'approved': {'action_id': 'second', 'models': ['gliner2'], 'method': 'extract'}},
              'active_case': {'id': 'CE-CAP-002', 'check': 'test_ce_cap_002_complete_request_taxonomy'},
              'semantic_review': 'Separate capable-model review recorded in SKETCH-REVIEW.json'}
    (HERE/'GATE.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'baseline_passed': baseline['passed'], 'tests': baseline['tests'],
                      'wrong_repairs_rejected': {k: v['rejected'] for k, v in mutations.items()}}))
    if not baseline['passed'] or not all(v['rejected'] for v in mutations.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
