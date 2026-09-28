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

def booking_window(sid='s00000001'):
    # 12 repeated <li> records, each identical apart from its own field text and
    # an identical 'Book' button -- the live A/B failure shape from fix 1/2/3.
    providers=[('Provider A','Consultation','60 min','1:30 PM'),('Provider B','Follow-up','30 min','2:00 PM'),
               ('Provider C','Follow-up','30 min','2:15 PM'),('Provider D','Consultation','45 min','2:30 PM'),
               ('Provider E','Follow-up','30 min','1:45 PM'),('Provider F','Follow-up','30 min','2:45 PM'),
               ('Provider G','Follow-up','30 min','3:15 PM'),('Provider H','Follow-up','30 min','4:00 PM'),
               ('Provider I','Follow-up','30 min','2:05 PM'),('Provider J','Telehealth','half-hour','3:00 PM'),
               ('Provider K','Follow-up','30 min','11:00 AM'),('Provider L','Consultation','30 min','2:20 PM')]
    nodes=[{'element_index':0,'role':'AXWindow','label':'Clinic Slots'}]
    index=1
    for name,service,duration,start in providers:
        li=index;index+=1
        nodes.append({'element_index':li,'parent_index':0,'role':'AXGroup','label':'Slot '+name})
        for value in (name,service,duration,'Starts '+start):
            nodes.append({'element_index':index,'parent_index':li,'role':'AXStaticText','value':value});index+=1
        nodes.append({'element_index':index,'parent_index':li,'role':'AXButton','label':'Book','actions':['AXPress']});index+=1
    for n in nodes:n.update(element_token=sid+':'+str(n['element_index']),enabled=True)
    return {'snapshot_id':sid,'pid':1,'window_id':2,'window_title':'Clinic Slots','elements':nodes,'_image':b'pixels'}


class FakeDriver:
    def __init__(self):
        self.version=0;self.change=False;self.executed=[];self.duplicate=False;self.pixel_change=False
        self.no_snapshot=False;self.window_open=True;self.background_input=None;self.booking=False
        # Perception defaults to not-installed so existing tests are unaffected.
        self.perception_payload={'installed':False}
        self.capture_id=None;self.window_bounds=None;self.parse_calls=[];self.parse_result={'regions':[]}
        self.parse_refusal=None
    def perception_status(self):return copy.deepcopy(self.perception_payload)
    def call(self,tool,args,timeout=20):
        if tool=='list_windows':
            return {'windows':[{'pid':1,'window_id':2,'title':'Demo'}] if self.window_open else []}
        if tool in ('click','type_text'):self.executed.append(copy.deepcopy(args));return {'effect':'unverifiable'}
        if tool=='parse_visual_regions':
            self.parse_calls.append(copy.deepcopy(args))
            if self.parse_refusal:return {'refusal':self.parse_refusal}
            return copy.deepcopy(self.parse_result)
        return {}
    def observe(self,*args):
        self.version+=1
        x=booking_window('s'+format(self.version,'08x')) if self.booking else window('s'+format(self.version,'08x'))
        if self.change:x['elements'][3]['label']='Delete everything'
        if self.duplicate:x['elements'][6]['label']='Inspect first'
        if self.pixel_change:x['_image']=b'changed'
        if self.background_input is not None:x['background_input']=self.background_input
        if self.capture_id:x['capture_id']=self.capture_id
        if self.window_bounds:x['window_bounds']=self.window_bounds
        if self.no_snapshot:
            x.pop('snapshot_id',None);x['refusal']={'code':'degraded'};x['degraded_reason']='window_minimized'
        return x


class VersionedDriver:
    """Minimal driver stub; deliberately not a FakeDriver subclass so its own
    'version' instance attribute never shadows the version() probe method."""
    def __init__(self,version_tuple):self._version=version_tuple
    def version(self):return self._version
    def call(self,tool,args,timeout=20):
        return {'windows':[{'pid':1,'window_id':2,'title':'Demo'}]} if tool=='list_windows' else {}
    def observe(self,*args):return window('sversioned')

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
        # S4.2 §5: a unique best binds; no chooser round trip for a grounded singleton.
        self.assertEqual(result['selected_id'],'e3');self.assertEqual(self.generic.requests,[])
        self.assertEqual(result['route'],'grounded_singleton');self.assertEqual(result['judgment'],'filter')
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
        # Goal quotes text that appears only in e3's own record ("Used $80"),
        # corroborating the FakeVision pick (actions[0], e3) per fix 2.
        selection=self.f.choose(self.obs,'Inspect the "Used $80" one',candidate_ids=['e3','e6'],mode='visual')['selection']
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
    def test_window_title_filter_omits_unrelated_windows(self):
        self.assertEqual(self.f.windows('Other')['windows'],[])
        self.assertEqual(len(self.f.windows('Demo')['windows']),1)
    # --- S4.8: readings are strings; the controller interprets ---------------
    def test_read_ignores_typed_schema_and_keeps_strings(self):
        # Live CE: 'half-hour' extracted correctly five times, made unknown by a
        # duration_minutes normalizer. Tempting wrong patch: teach the normalizer
        # 'half-hour'. Types are ignored instead; the string stays known.
        self.reader.extract=lambda req,sid:{'snapshot_id':sid,'records':[{'record_id':r['id'],'fields':{'duration':'half-hour'}} for r in req['records']]}
        r=self.f.read(self.obs,'Read slots',{'duration':{'description':'Length','type':'duration_minutes'}},['e1','e4'],
                      [{'field':'duration','op':'contains','value':'hour'}],coverage_complete=True)
        self.assertEqual(r['types_ignored'],{'duration':'duration_minutes'})
        self.assertEqual(r['filter']['unknown_ids'],[]);self.assertEqual(r['filter']['eligible_ids'],['e1','e4'])

    def test_read_budget_refuses_third_read_with_the_strings(self):
        # Live CE: five reads of the same 12 records. Tempting wrong patch: no bound.
        self.reading();self.reading()
        with self.assertRaisesRegex(Gap,'read_budget.*Used'):self.reading()
        self.assertEqual(len(self.reader.requests),2)

    def test_controller_judged_subset_binds_singleton_without_chooser(self):
        r=self.f.read(self.obs,'Read condition',{'condition':{'description':'Condition'}},['e1','e4'],coverage_complete=True)
        c=self.f.choose(self.obs,'Inspect the used one',reading=r['reading'],candidate_ids=['e1'])
        self.assertEqual(c['selected_id'],'e3');self.assertEqual(c['judgment'],'controller')
        self.assertEqual(self.generic.requests,[]);self.assertEqual(self.starts,[])
        self.f.act(c['selection']);self.assertEqual(self.driver.executed[0]['element_token'],'s00000002:3')

    def test_controller_judgment_cannot_name_records_outside_the_reading(self):
        r=self.f.read(self.obs,'Read condition',{'condition':{'description':'Condition'}},['e1'],coverage_complete=True)
        with self.assertRaisesRegex(Gap,'records of this reading'):
            self.f.choose(self.obs,'Inspect',reading=r['reading'],record_actions={'e1':'e3','e4':'e6'})

    def test_controller_judgment_cannot_revive_a_record_its_predicates_excluded(self):
        r=self.reading()
        with self.assertRaisesRegex(Gap,'excluded'):
            self.f.choose(self.obs,'Inspect',reading=r['reading'],candidate_ids=['e4'])

    def test_controller_judgment_over_unknowns_is_traced(self):
        self.reader.missing=True
        r=self.f.read(self.obs,'Read condition',{'condition':{'description':'Condition'}},['e1','e4'],
                      [{'field':'condition','value':'Used'}],coverage_complete=True)
        c=self.f.choose(self.obs,'Inspect',reading=r['reading'],candidate_ids=['e1'])
        self.assertEqual(c['selected_id'],'e3');self.assertEqual(c['unknown_competitors'],['e4'])
        self.assertEqual(self.f.events[-1]['unknown_competitors'],1)

    def test_incomplete_scope_defer_shows_extracted_strings_and_forbids_reread(self):
        self.reader.extract=lambda req,sid:{'snapshot_id':sid,'records':[{'record_id':r['id'],'fields':{'n':'7'}} for r in req['records']]}
        r=self.f.read(self.obs,'Read',{'n':{'description':'N','type':'number'}},['e1','e4'],[{'field':'n','op':'contains','value':'x'}],coverage_complete=False)
        d=self.f.choose(self.obs,'Inspect',reading=r['reading'])
        self.assertEqual(d['status'],'defer');self.assertIn('Do not re-read',d['hint'])

    def test_read_path_has_no_typed_normalization(self):
        # Static guardrail (S4.8): the reading path must not call typed() or
        # mention typed kinds; an LLM cannot reintroduce normalization there.
        import ast,inspect
        tree=ast.parse(inspect.getsource(Facade))
        fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='read')
        calls={c.func.id for c in ast.walk(fn) if isinstance(c,ast.Call) and isinstance(c.func,ast.Name)}
        self.assertNotIn('typed',calls)
        consts={c.value for c in ast.walk(fn) if isinstance(c,ast.Constant) and isinstance(c.value,str)}
        self.assertFalse(consts&{'duration_minutes','time','money','number','USD'})

    # --- S4.8: revalidation scope -------------------------------------------
    def browser_window(self,memory='93.4 MB',row_value='Used $80',url='127.0.0.1:8934/booking'):
        nodes=[{'element_index':0,'role':'AXWindow','label':'demo'},
          *([{'element_index':9,'parent_index':0,'role':'AXTextField','value':url}] if url else []),
          {'element_index':1,'parent_index':0,'role':'AXTabGroup'},
          {'element_index':2,'parent_index':1,'role':'AXRadioButton','label':'Demo - Memory usage - '+memory},
          {'element_index':3,'parent_index':0,'role':'AXWebArea'},
          {'element_index':4,'parent_index':3,'role':'AXRow','label':'First product'},
          {'element_index':5,'parent_index':4,'role':'AXStaticText','value':row_value},
          {'element_index':6,'parent_index':4,'role':'AXButton','label':'Inspect first','actions':['AXPress']},
          {'element_index':7,'parent_index':3,'role':'AXRow','label':'Second product'},
          {'element_index':8,'parent_index':7,'role':'AXButton','label':'Inspect second','actions':['AXPress']}]
        return nodes

    def act_after_change(self,before=None,**after):
        seq=[self.browser_window(**(before or {})),self.browser_window(**after)];n=[0]
        def observe(*a):
            nodes=copy.deepcopy(seq[min(n[0],1)]);n[0]+=1;sid='sb%d'%n[0]
            for x in nodes:x.update(element_token=sid+':'+str(x['element_index']),enabled=True)
            return {'snapshot_id':sid,'pid':1,'window_id':2,'window_title':'Demo','elements':nodes,'_image':b'p'}
        self.driver.observe=observe
        obs=self.f.observe(1,2)['snapshot']
        sel=self.f.choose(obs,'Inspect first',mode='exact',exact_name='Inspect first',exact_role='AXButton')['selection']
        return lambda:self.f.act(sel)

    def test_act_ignores_browser_chrome_change_outside_web_area(self):
        # Live CE: Chrome's tab strip memory readout changed 93.4 MB -> 86.0 MB and
        # the click was refused. Tempting wrong patch: regex-ignore 'Memory usage'
        # or drop names from the fingerprint.
        self.act_after_change(memory='86.0 MB')()
        self.assertEqual(len(self.driver.executed),1)

    def test_act_refuses_navigation_even_when_page_tree_is_identical(self):
        # CE-FACADE-002 approved clause: the address field is bound with the page.
        # Tempting wrong patch: web area only, so a navigation to a lookalike page passes.
        with self.assertRaisesRegex(Gap,'content scope'):self.act_after_change(url='127.0.0.1:8934/orders')()
        self.assertEqual(self.driver.executed,[])

    def test_act_keeps_whole_window_revalidation_when_no_address_field_is_observed(self):
        # Review P2.3. Tempting wrong patch: scoping to the web area anyway, which
        # makes navigation unobservable and silently drops the guarantee.
        with self.assertRaisesRegex(Gap,'UI changed'):self.act_after_change(before={'url':None},url=None,memory='86.0 MB')()
        self.assertEqual(self.driver.executed,[])

    def test_read_preserves_display_strings_of_any_shape(self):
        # Review P3: behavioral guard for S4.8, stronger than the AST check.
        shapes={'e1':'1 hr 30 min','e4':'$1,250.00'}
        self.reader.extract=lambda req,sid:{'snapshot_id':sid,'records':[{'record_id':r['id'],'fields':{'v':shapes[r['id']]}} for r in req['records']]}
        r=self.f.read(self.obs,'Read',{'v':{'description':'V','type':'duration_minutes'}},['e1','e4'],
                      [{'field':'v','op':'contains','value':'1'}],coverage_complete=True)
        self.assertEqual(r['filter']['unknown_ids'],[]);self.assertEqual(r['filter']['eligible_ids'],['e1','e4'])
        self.assertEqual({x['record_id']:x['fields']['v'] for x in r['extraction']['records']},shapes)

    def test_controller_judged_pick_is_flagged_caller_preselected(self):
        r=self.f.read(self.obs,'Read condition',{'condition':{'description':'Condition'}},['e1','e4'],coverage_complete=True)
        c=self.f.choose(self.obs,'Inspect the used one',reading=r['reading'],candidate_ids=['e1'])
        self.assertTrue(c['caller_preselected']);self.assertTrue(self.f.events[-1]['caller_preselected'])
        c2=self.reading();c2=self.f.choose(self.obs,'Inspect eligible',reading=c2['reading'])
        self.assertFalse(c2['caller_preselected'])

    def test_act_refuses_content_change_inside_web_area(self):
        with self.assertRaisesRegex(Gap,'content scope'):self.act_after_change(row_value='Used $95')()
        self.assertEqual(self.driver.executed,[])
    def test_read_then_choose_filters_cached_records_and_maps_root_ids(self):
        r=self.f.read(self.obs,'Read condition',{'condition':{'type':'text','description':'Condition'}},['e1','e4'],coverage_complete=True)
        c=self.f.choose(self.obs,'Inspect used',reading=r['reading'],candidate_ids=['e1','e4'],
            record_actions={'e1':'e3','e4':'e6'},predicates=[{'field':'condition','value':'Used'}])
        self.assertEqual(c['selected_id'],'e3');self.assertEqual(self.generic.requests,[])
        self.assertEqual(len(self.reader.requests),1)
    def test_additional_filter_cannot_revive_excluded_record(self):
        r=self.reading()
        c=self.f.choose(self.obs,'Inspect new',reading=r['reading'],predicates=[{'field':'condition','value':'New'}])
        self.assertFalse(c.get('selection'))
        self.assertNotIn('e6',[a['id'] for req in self.generic.requests for a in req['actions']])
    def test_added_predicate_missing_evidence_blocks_before_chooser(self):
        self.reader.missing=True
        r=self.f.read(self.obs,'Read condition',{'condition':{'type':'text','description':'Condition'}},['e1','e4'],coverage_complete=True)
        c=self.f.choose(self.obs,'Inspect',reading=r['reading'],predicates=[{'field':'condition','value':'Used'}])
        self.assertEqual(c['status'],'defer');self.assertEqual(self.starts,[])
    def test_semantic_criteria_without_reading_cannot_be_ignored(self):
        with self.assertRaisesRegex(Gap,'reading'):
            self.f.choose(self.obs,'Inspect',candidate_ids=['e3','e6'],predicates=[{'field':'condition','value':'Used'}])
    def test_filtered_mapping_still_rejects_cross_record_target(self):
        r=self.f.read(self.obs,'Read condition',{'condition':{'type':'text','description':'Condition'}},['e1','e4'],coverage_complete=True)
        with self.assertRaisesRegex(Gap,'outside'):
            self.f.choose(self.obs,'Inspect used',reading=r['reading'],record_actions={'e1':'e3','e4':'e3'},predicates=[{'field':'condition','value':'Used'}])
    def test_filtered_disabled_control_does_not_silently_drop_record(self):
        r=self.reading()
        self.f.state(self.obs)['nodes'][3]['enabled']=False
        with self.assertRaisesRegex(Gap,'eligible record'):
            self.f.choose(self.obs,'Inspect',reading=r['reading'],record_actions={'e1':'e3'})
    def test_verify_returns_current_observation_for_next_choice(self):
        v=self.f.verify(1,2,'Visible control',mode='exact',name='Inspect first')
        self.assertEqual(v['snapshot'],v['observation']['snapshot'])
        self.assertTrue(v['observation']['elements'])
        self.assertEqual(self.f.choose(v['snapshot'],'Inspect first',mode='exact',exact_name='Inspect first')['status'],'selected')
    def test_worker_cleanup(self):
        self.reading();self.f.choose(self.obs,'Inspect',candidate_ids=['e3','e6']);self.f.close()
        self.assertTrue(self.reader.closed);self.assertTrue(self.generic.closed)
    def test_timeout_age(self):
        self.f.clock=lambda:self.f.snapshots[self.obs]['created']+121
        with self.assertRaises(Gap):self.exact()
    def test_trace_no_page_text(self):
        self.reading();self.exact()
        self.assertNotIn('$80',str(self.f.events));self.assertNotIn('Inspect first',str(self.f.events))

    # --- Fix 1: record context in candidate descriptions -------------------
    def test_record_context_never_leaks_sibling_record(self):
        self.driver.booking=True
        obs=self.f.observe(1,2)['snapshot']
        state=self.f.state(obs)
        book_ids=['e'+str(6+6*i) for i in range(12)]
        described={a['id']:a['description'] for a in self.f.actions(state,book_ids,'click',None)}
        # Tempting wrong patch: using the parent list's full text (spans all 12
        # records) or a preceding sibling's text instead of the smallest
        # disambiguating ancestor.
        self.assertIn('Provider A',described['e6'])
        self.assertIn('record:',described['e6'])
        for other in ('Provider B','Provider C','Provider L'):
            self.assertNotIn(other,described['e6'])
        self.assertIn('Provider L',described['e72'])
        for other in ('Provider A','Provider B','Provider K'):
            self.assertNotIn(other,described['e72'])

    def test_record_context_uses_table_row_not_nearest_cell(self):
        # Tempting wrong patch: the nearest unique ancestor, an actions cell that
        # holds only "Track"/"Cancel", so every Cancel looks identical.
        nodes=[{'element_index':0,'parent_index':None,'role':'AXTable','label':'Orders'}];index=1
        for order,item,status in (('#1041','Walnut desk lamp','Shipped'),('#1044','Walnut desk lamp','Processing')):
            row=index;nodes.append({'element_index':row,'parent_index':0,'role':'AXRow'});index+=1
            for text in (order,item,status):
                nodes.append({'element_index':index,'parent_index':row,'role':'AXCell'})
                nodes.append({'element_index':index+1,'parent_index':index,'role':'AXStaticText','value':text});index+=2
            cell=index;nodes.append({'element_index':cell,'parent_index':row,'role':'AXCell'});index+=1
            for label in ('Track','Cancel'):
                nodes.append({'element_index':index,'parent_index':cell,'role':'AXButton','label':label,'actions':['AXPress']});index+=1
        for n in nodes:n.update(element_token='st:'+str(n['element_index']),enabled=True)
        self.driver.observe=lambda *a:{'snapshot_id':'st','pid':1,'window_id':2,'window_title':'Orders','elements':copy.deepcopy(nodes),'_image':b'p'}
        state=self.f.state(self.f.observe(1,2)['snapshot'])
        cancels=['e'+str(n['element_index']) for n in nodes if n.get('label')=='Cancel']
        described=[a['description'] for a in self.f.actions(state,cancels,'click',None)]
        self.assertIn('#1041',described[0]);self.assertIn('Shipped',described[0]);self.assertNotIn('#1044',described[0])
        self.assertIn('#1044',described[1]);self.assertIn('Processing',described[1]);self.assertNotIn('Shipped',described[1])

    # --- Fix 2: visual choice cannot authorize alone ------------------------
    def test_visual_pick_without_corroboration_defers_and_issues_no_handle(self):
        result=self.f.choose(self.obs,'Inspect the "Used $80" one',candidate_ids=['e6','e3'],mode='visual')
        self.assertEqual(result['status'],'defer')
        self.assertEqual(result['reason'],'visual_uncorroborated')
        self.assertNotIn('selection',result)
        self.assertEqual(result['suggested_id'],'e6')

    def test_visual_pick_corroborated_by_quoted_record_text_authorizes(self):
        result=self.f.choose(self.obs,'Inspect the "Used $80" one',candidate_ids=['e3','e6'],mode='visual')
        self.assertEqual(result['status'],'selected')
        self.assertEqual(result['selected_id'],'e3')
        self.assertIn('selection',result)

    def test_visual_quoted_corroboration_ignored_for_caller_narrowed_scope(self):
        # Review P1. Tempting wrong patch: checking uniqueness only among the
        # caller's offered subset, so a singleton plus its own quote passes.
        result=self.f.choose(self.obs,'Inspect the "Used $80" one',candidate_ids=['e3'],mode='visual')
        self.assertEqual(result['reason'],'visual_uncorroborated')
        self.assertNotIn('selection',result)

    def flat_list(self,header=None,footer=None):
        # Live Chrome shape (2026-09-28 retest): <li> wrappers pruned, so every
        # field and Book button is a direct child of one AXList.
        nodes=[{'element_index':0,'parent_index':None,'role':'AXWindow','label':'Clinic'},
               {'element_index':1,'parent_index':0,'role':'AXList'}];index=2;books=[]
        def text(value):
            nonlocal index;nodes.append({'element_index':index,'parent_index':1,'role':'AXStaticText','value':value});index+=1
        if header:text(header)
        for provider,start in (('Dr. Morgan Reyes','Starts 1:30 PM'),('Morgan Lee, NP','Starts 2:00 PM'),('Dr. Kim Ortega','Starts 2:20 PM')):
            text(provider);text(start)
            nodes.append({'element_index':index,'parent_index':1,'role':'AXButton','label':'Book','actions':['AXPress']});books.append('e'+str(index));index+=1
        if footer:text(footer)
        for n in nodes:n.update(element_token='sf:'+str(n['element_index']),enabled=True)
        self.driver.observe=lambda *a:{'snapshot_id':'sf','pid':1,'window_id':2,'window_title':'Clinic','elements':copy.deepcopy(nodes),'_image':b'p'}
        return self.f.state(self.f.observe(1,2)['snapshot']),books

    def test_record_context_flat_list_uses_sibling_order(self):
        # Tempting wrong patch: the flat list's whole text (all providers), or
        # the text following each button (the next record's fields).
        state,books=self.flat_list()
        described=[a['description'] for a in self.f.actions(state,books,'click',None)]
        self.assertIn('Dr. Morgan Reyes',described[0]);self.assertIn('1:30',described[0]);self.assertNotIn('Morgan Lee',described[0])
        self.assertIn('Morgan Lee',described[1]);self.assertNotIn('Dr. Morgan Reyes',described[1]);self.assertNotIn('Ortega',described[1])
        self.assertIn('Ortega',described[2]);self.assertNotIn('Lee',described[2])

    def test_record_context_flat_list_ambiguous_orientation_gives_no_context(self):
        # Text both before the first and after the last button: which side is
        # the record cannot be decided, so give none rather than guess.
        state,books=self.flat_list(header='Available appointments',footer='Times are local')
        described=[a['description'] for a in self.f.actions(state,books,'click',None)]
        self.assertEqual(described,['Book']*3)

    def test_read_flat_list_controls_use_sibling_records_without_overlap(self):
        state,books=self.flat_list()
        self.reader.extract=lambda req,sid:(self.reader.requests.append(req),
            {'snapshot_id':sid,'records':[{'record_id':r['id'],'fields':{'condition':'New'}} for r in req['records']]})[1]
        snapshot=[h for h,v in self.f.snapshots.items() if v is state][0]
        result=self.f.read(snapshot,'Read slots',{'condition':{'description':'x','type':'text'}},books,coverage_complete=True)
        texts=[r['text'] for r in self.reader.requests[-1]['records']]
        self.assertIn('Dr. Morgan Reyes',texts[0]);self.assertNotIn('Morgan Lee',texts[0])
        self.assertIn('Morgan Lee',texts[1]);self.assertNotIn('Ortega',texts[1])
        self.assertEqual(result['record_basis'],{b:'sibling_order' for b in books})

    def test_spans_fields_must_be_described_objects(self):
        # Live retest crash: string field specs reached the dispatcher and raised
        # AttributeError; reject them with the expected shape instead.
        with self.assertRaisesRegex(Gap,'description'):
            self.f.choose(self.obs,'Pick',candidate_ids=['e3','e6'],mode='spans',fields={'provider':'clinician name'})

    def test_record_context_nested_groups_stop_at_record(self):
        # Review P3: date groups each holding several records must not make a
        # whole group (two providers) the record.
        nodes=[{'element_index':0,'parent_index':None,'role':'AXWindow','label':'Inbox'}];index=1;books=[]
        for day,people in (('Monday',('Ana','Ben')),('Tuesday',('Cy','Di'))):
            group=index;nodes.append({'element_index':group,'parent_index':0,'role':'AXGroup','label':day});index+=1
            for person in people:
                rec=index;nodes.append({'element_index':rec,'parent_index':group,'role':'AXGroup'})
                nodes.append({'element_index':rec+1,'parent_index':rec,'role':'AXStaticText','value':person})
                nodes.append({'element_index':rec+2,'parent_index':rec,'role':'AXButton','label':'Book','actions':['AXPress']})
                books.append('e'+str(rec+2));index+=3
        for n in nodes:n.update(element_token='sn:'+str(n['element_index']),enabled=True)
        self.driver.observe=lambda *a:{'snapshot_id':'sn','pid':1,'window_id':2,'window_title':'Inbox','elements':copy.deepcopy(nodes),'_image':b'p'}
        state=self.f.state(self.f.observe(1,2)['snapshot'])
        described=[a['description'] for a in self.f.actions(state,books,'click',None)]
        self.assertIn('Ana',described[0]);self.assertNotIn('Ben',described[0]);self.assertNotIn('Monday',described[0])
        self.assertIn('Di',described[3]);self.assertNotIn('Cy',described[3])

    # --- Fix 3: reject answer-leaking goals; flag caller preselection -------
    def test_goal_mentioning_observed_element_id_rejected(self):
        with self.assertRaises(Gap):
            self.f.choose(self.obs,'Click e3 since it matches',candidate_ids=['e3','e6'])

    def test_goal_stating_the_answer_rejected(self):
        with self.assertRaises(Gap):
            self.f.choose(self.obs,'The correct one is the first product',candidate_ids=['e3','e6'])

    def test_caller_preselected_flagged_for_strict_subset_without_reading(self):
        self.driver.booking=True
        obs=self.f.observe(1,2)['snapshot']
        book_ids=['e'+str(6+6*i) for i in range(12)]
        narrowed=self.f.choose(obs,'Choose the telehealth video visit slot',candidate_ids=book_ids[:3],mode='semantic')
        self.assertTrue(narrowed['caller_preselected'])
        self.assertTrue(self.f.events[-1]['caller_preselected'])
        full=self.f.choose(obs,'Choose the telehealth video visit slot',candidate_ids=book_ids,mode='semantic')
        self.assertFalse(full['caller_preselected'])

    # --- Fix 5: actionable incomplete-scope defers --------------------------
    def test_incomplete_scope_defer_includes_actionable_detail(self):
        self.reader.missing=True
        r=self.reading()
        result=self.f.choose(self.obs,'Inspect',reading=r['reading'])
        self.assertEqual(result['reason'],'unknown_or_incomplete_scope')
        self.assertEqual(set(result['unknown_ids']),{'e1','e4'})
        self.assertEqual(result['excluded_count'],0)
        self.assertEqual(result['eligible_ids'],[])
        self.assertEqual(result['missing_fields']['e1'],['condition'])
        self.assertEqual(result['missing_fields']['e4'],['condition'])
        self.assertTrue(result['hint'])

    # --- Fix 6: verification -------------------------------------------------
    def test_verify_contains_match_is_case_insensitive_substring(self):
        result=self.f.verify(1,2,'partial label visible',mode='exact',name='inspect FIRST',match='contains')
        self.assertEqual(result['status'],'satisfied')

    def test_verify_equals_match_still_requires_full_label(self):
        result=self.f.verify(1,2,'partial label visible',mode='exact',name='Inspect',match='equals')
        self.assertEqual(result['status'],'unknown')

    def test_observe_reports_window_closed_when_window_gone(self):
        self.driver.no_snapshot=True;self.driver.window_open=False
        with self.assertRaisesRegex(Gap,'window_closed'):self.f.observe(1,2)

    def test_observe_reports_driver_snapshot_unavailable_with_detail_when_window_still_listed(self):
        self.driver.no_snapshot=True
        # Tempting wrong patch: keeping the old generic 'Driver did not return a
        # bound snapshot' message here loses the still-open/degraded distinction.
        with self.assertRaisesRegex(Gap,'driver_snapshot_unavailable'):
            try:self.f.observe(1,2)
            except Gap as gap:
                self.assertIn('window_minimized',str(gap));raise

    def test_visual_verify_quoted_text_matches_ax_tree_without_calling_vision_model(self):
        called=[]
        self.visual.inspect=lambda *a,**k:(called.append(1),{'state':'ready','evidence':'x'})[1]
        result=self.f.verify(1,2,'Status shows "Inspect first"')
        self.assertEqual(result['route'],'exact_text_postcondition')
        self.assertEqual(result['status'],'satisfied')
        self.assertEqual(called,[])

    def test_visual_verify_quoted_text_with_other_constraints_still_uses_vision(self):
        # Tempting wrong patch: accept quoted text found anywhere and ignore the
        # remaining constraint about which record/view shows it.
        result=self.f.verify(1,2,'"Inspect first" appears in the details view for the Used product')
        self.assertEqual(result['route'],'systemone_vision')

    def test_visual_verify_quoted_text_repeated_across_elements_uses_vision(self):
        # Review P2. Tempting wrong patch: substring over the joined tree, so
        # text present in several records ("Inspect") counts as the outcome.
        result=self.f.verify(1,2,'The page now shows "Inspect"')
        self.assertEqual(result['route'],'systemone_vision')

    def test_visual_verify_falls_back_to_vision_when_quoted_text_absent(self):
        result=self.f.verify(1,2,'Status shows "Not anywhere in the tree"')
        self.assertEqual(result['route'],'systemone_vision')

    # --- Fix 7: Spaces/foreground refusal and minimum driver version -------
    def test_act_refuses_when_window_off_space_or_ax_unresolved(self):
        selection=self.exact()['selection']
        self.driver.background_input={'exact_window':{'status':'ax_unresolved'},
                                       'routes':{'click':{'status':'refused','reason':'off_space_or_ax_unresolved'}}}
        # Tempting wrong patch: raising/activating the window to work around
        # this instead of refusing. No click and no raw driver call may occur.
        with self.assertRaisesRegex(Gap,'needs_foreground'):
            self.f.act(selection)
        self.assertEqual(self.driver.executed,[])

    def test_act_refuses_on_driver_list_shaped_refused_routes(self):
        # Real cua-driver shape (0.28.2 trace): routes is a list. Tempting wrong
        # patch: only reading a keyed dict, so a refused route is ignored.
        selection=self.exact()['selection']
        self.driver.background_input={'exact_window':{'pid':1,'window_id':2},
            'routes':[{'route':'accessibility','status':'refused','reason':'off_space_or_ax_unresolved'}]}
        with self.assertRaisesRegex(Gap,'needs_foreground'):self.f.act(selection)
        self.assertEqual(self.driver.executed,[])

    def test_act_proceeds_when_driver_routes_available(self):
        selection=self.exact()['selection']
        self.driver.background_input={'exact_window':{'status':'matched'},
            'routes':[{'route':'accessibility','status':'available'}]}
        self.f.act(selection)
        self.assertEqual(len(self.driver.executed),1)

    def test_old_driver_version_refused_even_though_naive_string_compare_would_pass(self):
        # '0.9.0' > '0.29.1' as strings; only a tuple/numeric compare catches this.
        driver=VersionedDriver((0,9,0))
        f=Facade(driver,generic_factory=lambda:FakeChooser(),reader_factory=lambda:FakeReader(),visual_factory=lambda:FakeVision())
        with self.assertRaisesRegex(Gap,'0.29.1'):
            f.observe(1,2)

    def test_supported_driver_version_allowed_and_recorded_in_trace(self):
        driver=VersionedDriver((0,29,1))
        f=Facade(driver,generic_factory=lambda:FakeChooser(),reader_factory=lambda:FakeReader(),visual_factory=lambda:FakeVision())
        f.observe(1,2)
        self.assertEqual(f.driver_version,(0,29,1))
        self.assertEqual(f.close()['driver_version'],(0,29,1))

    def test_unparsed_driver_version_is_distinguishable_in_trace(self):
        # Review P4: an unparseable version passes (check_foreground still guards
        # act), but must not look like a version that was never probed.
        f=Facade(VersionedDriver(None),generic_factory=lambda:FakeChooser(),reader_factory=lambda:FakeReader(),visual_factory=lambda:FakeVision())
        self.assertEqual(f.close()['driver_version_state'],'unprobed')
        f.observe(1,2)
        self.assertEqual(f.close()['driver_version_state'],'unparsed')

if __name__=='__main__':unittest.main()
