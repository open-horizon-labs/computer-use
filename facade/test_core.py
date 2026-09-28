import copy
import sys
import unittest
from core import Facade,Gap


def window(sid='s00000001'):
    nodes=[{'element_index':0,'role':'AXWindow','label':'demo'},
      {'element_index':1,'parent_index':0,'role':'AXRow','label':'First product'},
      {'element_index':2,'parent_index':1,'role':'AXStaticText','value':'Used $80'},
      {'element_index':3,'parent_index':1,'role':'AXButton','label':'Inspect first','actions':['AXPress']},
      {'element_index':4,'parent_index':0,'role':'AXRow','label':'Second product'},
      {'element_index':5,'parent_index':4,'role':'AXStaticText','value':'New $90'},
      {'element_index':6,'parent_index':4,'role':'AXButton','label':'Inspect second','actions':['AXPress']}]
    for n in nodes:n.update(element_token=sid+':'+str(n['element_index']),enabled=True)
    return {'snapshot_id':sid,'pid':1,'window_id':2,'window_title':'Demo','elements':nodes,'_image':b'pixels'}

class FakeDriver:
    def __init__(self):self.version=0;self.change=False;self.executed=[];self.duplicate=False;self.pixel_change=False
    def call(self,tool,args,timeout=20):
        if tool=='list_windows':return {'windows':[{'pid':1,'window_id':2,'title':'Demo'}]}
        if tool=='click':self.executed.append(copy.deepcopy(args));return {'effect':'unverifiable'}
        return {}
    def observe(self,*args):
        self.version+=1;x=window('s'+format(self.version,'08x'))
        if self.change:x['elements'][3]['label']='Delete everything'
        if self.duplicate:x['elements'][6]['label']='Inspect first'
        if self.pixel_change:x['_image']=b'changed'
        return x

class FakeChooser:
    def __init__(self):self.requests=[];self.closed=False
    def __call__(self,step,request):
        self.requests.append(copy.deepcopy(request));return {'choice':request['actions'][0]['id'],'route':'julia-1','action_authorized':True}
    def close(self):self.closed=True

class FakeReader:
    def __init__(self):self.requests=[];self.missing=False;self.closed=False
    def extract(self,req,sid):
        self.requests.append(req)
        return {'snapshot_id':sid,'records':[{'record_id':r['id'],'fields':{'condition':None if self.missing else ('Used' if 'Used' in r['text'] else 'New')}} for r in req['records']]}
    def close(self):self.closed=True

class FakeVision(FakeChooser):
    def inspect(self,snapshot,postcondition,timeout):return {'state':'ready','evidence':'visible postcondition'}

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.driver=FakeDriver();self.generic=FakeChooser();self.reader=FakeReader();self.visual=FakeVision()
        self.starts=[]
        def generic():self.starts.append('generic');return self.generic
        self.f=Facade(self.driver,generic_factory=generic,reader_factory=lambda:self.reader,
                      visual_factory=lambda:self.visual)
        self.obs=self.f.observe(1,2)['snapshot']
    def exact(self):return self.f.choose(self.obs,'Inspect first',mode='exact',exact_name='Inspect first',exact_role='AXButton')
    def reading(self,coverage=True):
        return self.f.read(self.obs,'Read condition',{'condition':{'type':'text','description':'Explicit condition'}},
            ['e1','e4'],[{'field':'condition','value':'Used'}],coverage)
    def test_exact_no_model_and_preserved_driver_args(self):
        result=self.exact();self.assertEqual(self.starts,[])
        out=self.f.act(result['selection']);self.assertTrue(out['requires_verification'])
        self.assertEqual(self.driver.executed[0]['element_token'],'s00000002:3')
    def test_duplicate_exact_not_hidden_by_singleton_scope(self):
        self.driver.duplicate=True;self.obs=self.f.observe(1,2)['snapshot']
        result=self.f.choose(self.obs,'Inspect',candidate_ids=['e3'],mode='exact',exact_name='Inspect first')
        self.assertEqual(result['status'],'defer');self.assertNotIn('selection',result)
    def test_synthetic_id_rejected(self):
        with self.assertRaises(Gap):self.f.choose(self.obs,'Act',candidate_ids=['control'])
    def test_exact_requires_observed_name(self):
        with self.assertRaises(Gap):self.f.choose(self.obs,'Act',candidate_ids=['e3'],mode='exact')
    def test_semantic_calls_provider(self):
        result=self.f.choose(self.obs,'Inspect first',candidate_ids=['e3','e6'])
        self.assertEqual(self.starts,['generic']);self.assertEqual(result['selected_id'],'e3')
    def test_semantic_singleton_needs_filtered_reading(self):
        result=self.f.choose(self.obs,'Inspect first',candidate_ids=['e3'])
        self.assertEqual(result['reason'],'singleton_requires_grounded_reading')
        self.assertEqual(self.starts,[])
    def test_stale_snapshot(self):
        self.f.observe(1,2)
        with self.assertRaises(Gap):self.exact()
    def test_changed_ui_rejects_action(self):
        selection=self.exact()['selection'];self.driver.change=True
        with self.assertRaises(Gap):self.f.act(selection)
        self.assertEqual(self.driver.executed,[])
    def test_mutating_returned_decision_cannot_change_stored_action(self):
        result=self.exact();result['decision']['action_id']='e6'
        self.f.act(result['selection']);self.assertTrue(self.driver.executed[0]['element_token'].endswith(':3'))
    def test_replay_rejected(self):
        selection=self.exact()['selection'];self.f.act(selection)
        with self.assertRaises(Gap):self.f.act(selection)
    def test_overlap_rejected(self):
        with self.assertRaises(Gap):self.f.read(self.obs,'Read',{'x':{'description':'x'}},['e1','e2'])
    def test_record_evidence_not_cross_contaminated(self):
        self.reading();rows=self.reader.requests[0]['records']
        self.assertIn('$80',rows[0]['text']);self.assertNotIn('$90',rows[0]['text'])
    def test_reading_joins_only_eligible_descendant_control(self):
        read=self.reading();result=self.f.choose(self.obs,'Inspect eligible product',reading=read['reading'])
        self.assertEqual(result['selected_id'],'e3');self.assertEqual(len(self.generic.requests[0]['actions']),1)
    def test_missing_condition_blocks_choice(self):
        self.reader.missing=True;r=self.reading()
        result=self.f.choose(self.obs,'Inspect',reading=r['reading'])
        self.assertEqual(result['status'],'defer');self.assertEqual(self.starts,[])
    def test_incomplete_scope_blocks_choice(self):
        r=self.reading(False);result=self.f.choose(self.obs,'Inspect',reading=r['reading'])
        self.assertEqual(result['status'],'defer')
    def test_record_mapping_cannot_escape_record(self):
        r=self.reading()
        with self.assertRaises(Gap):self.f.choose(self.obs,'Inspect',reading=r['reading'],record_actions={'e1':'e6'})
    def test_excluded_candidate_cannot_be_reintroduced(self):
        r=self.reading()
        with self.assertRaises(Gap):self.f.choose(self.obs,'Inspect',reading=r['reading'],candidate_ids=['e3','e6'])
    def test_visual_pixels_change_rejects(self):
        selection=self.f.choose(self.obs,'Inspect',candidate_ids=['e3','e6'],mode='visual')['selection']
        self.driver.pixel_change=True
        with self.assertRaises(Gap):self.f.act(selection)
    def test_verify_fresh_and_absence_unknown(self):
        result=self.f.verify(1,2,'Missing',mode='exact',name='Missing')
        self.assertEqual(result['status'],'unknown');self.assertEqual(self.driver.version,2)
    def test_visual_verification_is_independent(self):
        result=self.f.verify(1,2,'The result is visible')
        self.assertEqual(result['status'],'satisfied');self.assertTrue(result['independent_observation'])
    def test_visual_failure_is_traced_unknown(self):
        def fail(*args):raise ValueError('invalid response')
        self.visual.inspect=fail
        result=self.f.verify(1,2,'Visible result')
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(self.f.events[-1]['status'],'unknown')
    def test_table_preserves_cells_without_container_label(self):
        state=self.f.state(self.obs)
        state['nodes'][2]['role']='AXCell'
        text,_=self.f.subtree(state,'e1')
        self.assertIn('cells',text)
        self.assertIn('Used $80',text)
        self.assertNotIn('First product',text)
        self.assertNotIn('$90',text)
    def test_string_field_alias_supports_predicate(self):
        read=self.f.read(self.obs,'Read condition',{'condition':{'type':'string','description':'Explicit condition'}},
            ['e1','e4'],[{'field':'condition','value':'Used'}],True)
        self.assertEqual(read['filter']['eligible_ids'],['e1'])
    def test_worker_cleanup(self):
        self.reading();self.f.choose(self.obs,'Inspect',candidate_ids=['e3','e6']);self.f.close()
        self.assertTrue(self.reader.closed);self.assertTrue(self.generic.closed)
    def test_timeout_age(self):
        self.f.clock=lambda:self.f.snapshots[self.obs]['created']+121
        with self.assertRaises(Gap):self.exact()
    def test_trace_no_page_text(self):
        self.reading();self.exact()
        self.assertNotIn('$80',str(self.f.events));self.assertNotIn('Inspect first',str(self.f.events))

if __name__=='__main__':unittest.main()
