import copy
import json
import sys
import unittest
from unittest.mock import patch

from dispatch import Engine, execute_bound
from page_candidates import NuExtractPage, ExtractThenChoose, filter_records

FIELDS = {'model': {'type': 'text', 'description': 'device model'},
          'condition': {'type': 'text', 'description': 'condition'},
          'kind': {'type': 'text', 'description': 'product type'}}
RULES = [{'field': k, 'value': v} for k, v in
         [('model', 'Anker 737'), ('condition', 'Used'), ('kind', 'power bank')]]


def data(n=27):
    return {'snapshot_id': 's1', 'records': [
        {'record_id': str(i), 'fields': {'model': 'Anker 737', 'condition': 'Used' if i == 26 else 'New',
                                       'kind': 'power bank'}} for i in range(n)]}


def request():
    return {'snapshot_id': 's1', 'kind': 'semantic', 'operation': 'click', 'goal': 'Choose a used power bank',
        'actions': [{'id': str(i), 'operation': 'click', 'evidence_text': 'Anker 737 power bank Used New',
                     'arguments': {'original_id': str(i)}} for i in range(27)],
        'page_filter': {'task': 'Read product fields', 'fields': FIELDS, 'predicates': RULES,
                        'candidate_ids': [str(i) for i in range(27)], 'coverage_complete': True}}


class Extractor:
    def __init__(self, result=None): self.result = result or data()
    def extract(self, req, sid): return copy.deepcopy(self.result)


class Generic:
    def __init__(self, choice='26'): self.calls = []; self.choice = choice
    def __call__(self, step, req):
        self.calls.append(req)
        return {'choice': self.choice, 'action_authorized': True, 'route': 'fake-julia'}


class PageTests(unittest.TestCase):
    def filtered(self, d, complete=True):
        return filter_records(d, fields=FIELDS, predicates=RULES, coverage_complete=complete, current_snapshot='s1')

    def test_all_records_then_filter_not_first_chunk(self):
        result = self.filtered(data())
        self.assertEqual(result['eligible_ids'], ['26'])
        self.assertEqual(len(result['excluded_ids']), 26)

    def test_unknown_condition_is_not_excluded(self):
        d = data(); d['records'][0]['fields']['condition'] = None
        self.assertEqual(self.filtered(d)['unknown_ids'], ['0'])

    def test_accessory_is_excluded_even_with_missing_condition(self):
        d = data(); d['records'][0]['fields'].update(condition=None, kind='case')
        self.assertIn('0', self.filtered(d)['excluded_ids'])

    def test_identity_overlap_is_unknown_not_match(self):
        d = data(); d['records'][26]['fields']['model'] = 'Anker 737 Max'
        self.assertEqual(self.filtered(d)['unknown_ids'], ['26'])

    def test_missing_coverage_blocks_chooser(self):
        g=Generic(); req=request(); req['page_filter']['coverage_complete']=False
        result=ExtractThenChoose(Extractor(),g)({'method':'choose'},req)
        self.assertFalse(result['action_authorized']); self.assertEqual(g.calls,[])

    def test_unknown_blocks_chooser(self):
        g=Generic(); d=data(); d['records'][0]['fields']['condition']=None
        result=ExtractThenChoose(Extractor(d),g)({'method':'choose'},request())
        self.assertEqual(result['reason'],'unresolved_evidence'); self.assertEqual(g.calls,[])

    def test_arguments_remain_bound_to_original_request(self):
        req=request(); g=Generic(); wrapper=ExtractThenChoose(Extractor(),g)
        result=Engine({'jev':wrapper}).decide(req,'s1')
        self.assertEqual([a['id'] for a in g.calls[0]['actions']],['26'])
        self.assertEqual(execute_bound(req,result,'s1',lambda op,args:args),{'original_id':'26'})
        req['actions'][26]['arguments']={'original_id':'0'}
        with self.assertRaises(ValueError):execute_bound(req,result,'s1',lambda *a:None)

    def test_revived_excluded_choice_is_rejected(self):
        with self.assertRaises(ValueError):
            ExtractThenChoose(Extractor(),Generic('0'))({'method':'choose'},request())

    def test_oversized_survivors_not_tournament_ranked(self):
        d=data()
        for row in d['records']:row['fields']['condition']='Used'
        g=Generic(); result=ExtractThenChoose(Extractor(d),g)({'method':'choose'},request())
        self.assertEqual(result['reason'],'candidate_limit_after_extraction'); self.assertEqual(g.calls,[])

    def test_explicit_overflow_sees_all_survivors(self):
        d=data()
        for row in d['records']:row['fields']['condition']='Used'
        g=Generic(); overflow=Generic()
        ExtractThenChoose(Extractor(d),g,overflow=overflow)({'method':'choose'},request())
        self.assertEqual(len(overflow.calls[0]['actions']),27); self.assertEqual(g.calls,[])

    def test_stale_snapshot(self):
        d=data(); d['snapshot_id']='old'
        with self.assertRaises(ValueError):self.filtered(d)

    def test_invalid_predicate_even_when_missing(self):
        with self.assertRaises(Exception):
            filter_records(data(), fields=FIELDS, predicates=[{'field':'model','op':'contains','value':'737'}],
                           coverage_complete=True,current_snapshot='s1')

    def test_chunk_transport_identity_and_grounding(self):
        class Worker:
            def __init__(self):self.calls=[]
            def exchange(self, payload, timeout):
                self.calls.append(payload)
                return {'snapshot_id':'s1','model':'numind/NuExtract3','records':[
                    {'record_id':r['id'],'fields':{'price':{'value':'$999','source_quote':'$999'}}}
                    for r in reversed(payload['records'])]}
        worker=Worker()
        with patch('page_candidates.JsonWorker',return_value=worker):
            ex=NuExtractPage(chunk_size=5)
            result=ex.extract({'snapshot_id':'s1','task':'read prices','fields':{'price':'asking price'},
                'records':[{'id':str(i),'text':'Used $80'} for i in range(27)]},'s1')
        self.assertEqual([len(c['records']) for c in worker.calls],[5,5,5,5,5,2])
        self.assertEqual([r['record_id'] for r in result['records']],[str(i) for i in range(27)])
        self.assertTrue(all(r['fields']['price'] is None for r in result['records']))

    def test_missing_batch_fails_closed(self):
        class Worker:
            def exchange(self,payload,timeout):return {'snapshot_id':'s1','model':'numind/NuExtract3','records':[]}
        with patch('page_candidates.JsonWorker',return_value=Worker()):
            ex=NuExtractPage()
            with self.assertRaises(ValueError):ex.extract({'snapshot_id':'s1','task':'read','fields':{'a':'a'},
                'records':[{'id':'x','text':'x'}]},'s1')

    def test_real_transport_deadline(self):
        ex=NuExtractPage(command=[sys.executable,'-c','import time; time.sleep(10)'],timeout=.3)
        try:
            with self.assertRaises(TimeoutError):ex.extract({'snapshot_id':'s1','task':'read','fields':{'a':'a'},
                'records':[{'id':'x','text':'x'}]},'s1')
            self.assertIsNotNone(ex.worker.process.poll())
        finally:ex.close()


    def test_malformed_batches_never_authorize(self):
        for mode in ('duplicate', 'stale', 'schema', 'endpoint'):
            class Worker:
                def exchange(self, payload, timeout):
                    row = {'record_id': 'x', 'fields': {'a': None}}
                    if mode == 'endpoint': return {'error': 'HTTPError', 'http_status': 502}
                    return {'snapshot_id': 'old' if mode == 'stale' else 's1', 'model': 'numind/NuExtract3',
                            'records': [row, row] if mode == 'duplicate' else
                                       [{'record_id': 'x', 'fields': {}}] if mode == 'schema' else [row]}
            with self.subTest(mode=mode), patch('page_candidates.JsonWorker', return_value=Worker()):
                ex=NuExtractPage()
                with self.assertRaises((ValueError, RuntimeError)):
                    ex.extract({'snapshot_id':'s1','task':'read','fields':{'a':'field'},
                                'records':[{'id':'x','text':'x'}]},'s1')

    def test_request_mutation_and_cross_record_evidence(self):
        d=data(); d['records'][26]['fields']['condition']=None
        # Another record being Used cannot repair this candidate's condition.
        d['records'][0]['fields']['condition']='Used';d['records'][0]['fields']['model']='Other'
        result=self.filtered(d)
        self.assertEqual(result['eligible_ids'],[]);self.assertEqual(result['unknown_ids'],['26'])
        req=request();req['page_filter']['candidate_ids'].pop()
        with self.assertRaises(ValueError):ExtractThenChoose(Extractor(),Generic())({'method':'choose'},req)

if __name__ == '__main__': unittest.main()
