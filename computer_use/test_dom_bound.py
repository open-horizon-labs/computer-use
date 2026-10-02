"""Captured Driver DOM evidence must never bind duplicates by guessed order."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock
import dom_bound
from core import Facade, Gap
from test_core import FakeDriver, FakeVision, FakeChooser, FakeReader

FIX=Path(__file__).parent/'fixtures'
FULL=json.loads((FIX/'live_booking_dom.json').read_text())
SCOPE=json.loads((FIX/'live_booking_dom_scope.json').read_text())

class Driver(FakeDriver):
    def __init__(self):
        super().__init__();self.sent=[];self.scope=copy.deepcopy(SCOPE);self.clicked=False
    def observe(self,*args):
        raw=super().observe(*args);raw['elements']=[]
        raw['background_input']={'exact_window':{'status':'ax_unresolved'}}
        return raw
    def call(self,tool,args,timeout=20):
        self.sent.append((tool,copy.deepcopy(args)))
        if tool=='get_browser_state':
            if 'target_id' not in args:
                return {'target_id':'bt_fixture','binding_quality':'exact','mutation_allowed':True,
                        'tabs':[{'tab_id':'tab_fixture','active':True}],'native_title':'Demo'}
            if args.get('scope_ref'):return copy.deepcopy(self.scope)
            x=copy.deepcopy(FULL)
            if self.clicked:
                x.update(outline='- status\n  - statictext "Booked: Dr. Morgan Reyes, half-hour, 3:00 PM"',refs=[],content_refs=[])
            return x
        if tool=='browser_click':self.clicked=True;return {'effect':'confirmed'}
        return super().call(tool,args,timeout)

class BoundDomTests(unittest.TestCase):
    def test_identical_content_in_another_tab_or_url_invalidates_look_and_selection(self):
        full=json.loads((FIX/'live_settings_dom.json').read_text())
        for changed in ({'target_id':'other-target'}, {'tab_id':'other-tab'}, {'page':{**full['page'],'url':'https://different.example/'}}):
            f=self.facade();source=copy.deepcopy(full);original=f.driver.call
            def call(tool,args,timeout=20):
                value=original(tool,args,timeout)
                if tool=='get_browser_state':
                    if 'target_id' not in args:
                        value['tabs'][0]['tab_id']=source['tab_id'];value['target_id']=source['target_id']
                    else:value=copy.deepcopy(source)
                return value
            f.driver.call=call
            seen=f.look(title='Demo');state=next(reversed(f.snapshots.values()))
            snapshot=f.latest[(1,2)]
            selected=f.choose(snapshot,'Update Street',mode='exact',exact_name='Street',exact_role='AXTextField',operation='type_text',text='New street')
            self.assertIn('selection',selected,selected)
            source.update(changed)
            fresh=f.state(f.observe(1,2)['snapshot'])
            self.assertNotEqual(state['fingerprint'],fresh['fingerprint'])
            self.assertNotEqual(f.scope_digest(state,0),f.scope_digest(fresh,0))
            with self.assertRaises(Gap):f.act(selected['selection'])
            out=f.do(goal='Save shipping address',title='Demo',expect=None,look_id=seen['look_id'],steps=[{
                'do':'press','control':'Save','where':{'lines':[{'line':'contains','value':'Shipping address'}]},'expect':'Saved'}])
            self.assertEqual(out['reason'],'page_changed_since_look',out)
            self.assertFalse(f.driver.clicked)
            f.close()
    def test_captured_settings_scopes_preserve_fields_without_inventing_shadow_ancestry(self):
        full=json.loads((FIX/'live_settings_dom.json').read_text())
        scope=json.loads((FIX/'live_settings_dom_scope.json').read_text())
        f=self.facade()
        raw=dom_bound.project(full,1,2)
        data=raw['_dom']
        chosen=next(i for i,b in data['bindings'].items() if not b.get('direct') and
                    data['parsed'][b['anchor']]['text']==['Shipping address'])
        state={'raw':raw}
        f.node=Mock(return_value={'element_index':chosen})
        f.driver.scope=scope
        tool,args=dom_bound.action(f,state,'observed-save','click')
        self.assertEqual(tool,'browser_click')
        self.assertEqual(args['ref'],next(r['ref'] for r in scope['refs'] if r['name']=='Save'))
        # Real field changes still refuse; anonymous shadow nodes cannot hide them.
        f.driver.scope=copy.deepcopy(scope)
        f.driver.scope['outline']=scope['outline'].replace('textbox "City": Springfield','textbox "City": Boston')
        with self.assertRaises(Gap):dom_bound.action(f,state,'observed-save','click')
        f.driver.scope=copy.deepcopy(scope)
        f.driver.scope['outline']+='\nnot an outline node'
        with self.assertRaises(Gap):dom_bound.action(f,state,'observed-save','click')
        self.assertFalse(f.driver.clicked)
        f.close()
    def test_missing_parent_tail_cannot_hide_later_real_field_changes(self):
        full=json.loads((FIX/'live_settings_dom.json').read_text())
        scope=json.loads((FIX/'live_settings_dom_scope.json').read_text())
        # A detached shadow node between proper children must not end the record.
        city='    - paragraph\n      - labeltext\n        - statictext "City"'
        for value in (full,scope):
            self.assertIn(city,value['outline'])
            value['outline']=value['outline'].replace(city,'              - generic [editable="plaintext"]\n'+city)
        f=self.facade();raw=dom_bound.project(full,1,2);data=raw['_dom']
        chosen=next(i for i,b in data['bindings'].items() if not b.get('direct') and data['parsed'][b['anchor']]['text']==['Shipping address'])
        f.node=Mock(return_value={'element_index':chosen});f.driver.scope=scope
        self.assertEqual(dom_bound.action(f,{'raw':raw},'save','click')[0],'browser_click')
        scope['outline']=scope['outline'].replace('textbox "City": Springfield','textbox "City": Boston')
        with self.assertRaises(Gap):dom_bound.action(f,{'raw':raw},'save','click')
        f.close()
    def facade(self):
        return Facade(Driver(),reader_factory=FakeReader,generic_factory=FakeChooser,visual_factory=FakeVision,sleep=lambda _:None)
    def test_booking_two_calls_uses_scoped_driver_ref_and_independent_dom_verification(self):
        f=self.facade();seen=f.look(title='Demo')
        self.assertEqual(seen['status'],'ok',seen)
        self.assertEqual(len(seen['records']),12)
        self.assertFalse(seen['sources']['ax'])
        result=f.do(goal='Book the Telehealth visit with Dr. Morgan Reyes at 3:00 PM',title='Demo',expect=None,look_id=seen['look_id'],steps=[{
            'do':'press','control':'Book','where':{'lines':[{'line':'eq','value':'Dr. Morgan Reyes'},
                {'line':'eq','value':'Telehealth'},{'line':'contains','value':'3:00 PM'}]},'expect':'Booked:'}])
        self.assertEqual(result['status'],'done',result)
        self.assertEqual(result['steps'][0]['verification']['route'],'dom_expect_contains')
        clicks=[a for t,a in f.driver.sent if t=='browser_click']
        self.assertEqual(len(clicks),1)
        self.assertEqual(clicks[0]['ref'],SCOPE['refs'][0]['ref'])
        self.assertEqual(clicks[0]['input_route'],'dom_event')
        self.assertNotIn('element_token',clicks[0])
        self.assertEqual(f.first_do['calls'],2)
        f.close()
    def test_partial_and_omitted_competitors_refuse(self):
        for change in ({'complete':False},{'omitted':{'budget':1}},{'omitted':{'offscreen':1}}):
            x=copy.deepcopy(FULL);x['snapshot'].update(change)
            with self.assertRaises(Gap):dom_bound.project(x,1,2)
    def test_changed_scoped_record_and_duplicate_control_refuse(self):
        for mutate in (lambda x:x.update(outline=x['outline'].replace('3:00 PM','4:00 PM')),
                       lambda x:x['refs'].append({**x['refs'][0],'ref':'p99:99'}),
                       lambda x:x.update(tab_id='another-tab')):
            f=self.facade();seen=f.observe(1,2);state=f.state(seen['snapshot'])
            index=next(i for i,b in state['raw']['_dom']['bindings'].items() if b['anchor']==next(j for j,n in enumerate(state['raw']['_dom']['parsed']) if n['text']==['Slot s10']))
            mutate(f.driver.scope)
            with self.assertRaises(Gap):dom_bound.action(f,state,'e'+str(index),'click')
            self.assertFalse(f.driver.clicked);f.close()
    def test_duplicate_ancestor_labels_do_not_bind_by_position(self):
        x=copy.deepcopy(FULL)
        x['outline']=x['outline'].replace('Slot s10','Slot s09')
        for r in x['content_refs']:
            if r.get('name')=='Slot s10':r['name']='Slot s09'
        raw=dom_bound.project(x,1,2)
        parsed=raw['_dom']['parsed']
        roots=[i for i,n in enumerate(parsed) if n['text']==['Slot s09']]
        for root in roots:
            ids=dom_bound.members(parsed,root)
            for i in ids:
                if parsed[i]['role']=='button':
                    f=self.facade();f.driver.scope=x
                    state={'raw':raw,'nodes':{n['element_index']:n for n in raw['elements']}}
                    with self.assertRaises(Gap):dom_bound.action(f,state,'e'+str(i+1),'click')
                    self.assertFalse(f.driver.clicked);f.close()
    def test_unprepared_or_heuristic_browser_is_never_prepared_by_observation(self):
        f=self.facade();f.driver.call=Mock(return_value={'binding_quality':'heuristic','mutation_allowed':True})
        with self.assertRaises(Gap):dom_bound.observe(f,1,2)
        self.assertEqual(f.driver.call.call_args.args[0],'get_browser_state')
        self.assertEqual(f.driver.call.call_count,1);f.close()

class UnlabeledRows(unittest.TestCase):
    def test_captured_orders_exposes_cell_lines_and_searches_by_content(self):
        full=json.loads((FIX/'live_orders_dom.json').read_text())
        parsed=dom_bound.parse(full['outline'])
        wanted=next(i for i,n in enumerate(parsed) if n['role']=='row' and any(parsed[j]['text']==['#1044'] for j in dom_bound.members(parsed,i)))
        # Deliberately return the target from a different candidate ordinal. Only its content may bind.
        calls=[]
        f=Facade(Driver(),reader_factory=FakeReader,generic_factory=FakeChooser,visual_factory=FakeVision,sleep=lambda _:None)
        def call(tool,args,timeout=20):
            calls.append((tool,args))
            if tool=='get_browser_state':
                if 'target_id' not in args:return {'target_id':'bt_fixture','binding_quality':'exact','mutation_allowed':True,'tabs':[{'tab_id':'tab_fixture','active':True}],'native_title':'Demo'}
                if args.get('scope_ref'):
                    ordinal=sum(1 for t,a in calls if a.get('scope_ref'))
                    root=wanted if ordinal==2 else next(i for i,n in enumerate(parsed) if n['role']=='row')
                    outline='\n'.join('  '*(parsed[j]['depth']-parsed[root]['depth'])+'- '+parsed[j]['role']+(' '+json.dumps(parsed[j]['text'][0]) if parsed[j]['text'] else '') for j in dom_bound.members(parsed,root))
                    return {**full,'outline':outline,'snapshot':{**full['snapshot'],'id':'p_scoped'},'refs':[{'role':'button','name':'Cancel','ref':'p_scoped:chosen','actions':['click'],'visibility':'in_viewport'}]}
                return copy.deepcopy(full)
            return Driver.call(f.driver,tool,args,timeout)
        f.driver.call=call
        seen=f.look(title='Demo')
        self.assertEqual(seen['records'][3]['lines'][:3],['#1044','Walnut desk lamp','Processing'])
        state=f.state(f.latest[(1,2)])
        control=next(i for i,b in state['raw']['_dom']['bindings'].items() if b['anchor']==wanted and b['key']==('button',('Cancel',)))
        operation,args=dom_bound.action(f,state,'e'+str(control),'click')
        self.assertEqual(operation,'browser_click')
        self.assertEqual(args['ref'],'p_scoped:chosen')
        self.assertEqual(sum(1 for t,a in calls if a.get('scope_ref')),2)
        f.close()

class DialogDispatch(unittest.TestCase):
    def test_only_selected_dialog_action_is_rebound_from_multiple_candidates(self):
        full=json.loads((FIX/'live_orders_dom_dialog.json').read_text())
        driver=Driver()
        original=driver.call
        def call(tool,args,timeout=20):
            if tool=='get_browser_state' and 'target_id' in args:return copy.deepcopy(full)
            return original(tool,args,timeout)
        driver.call=call
        f=Facade(driver,reader_factory=FakeReader,generic_factory=FakeChooser,visual_factory=FakeVision,sleep=lambda _:None)
        seen=f.observe(1,2)
        pick=f.choose(seen['snapshot'],'Confirm cancellation',mode='exact',exact_name='Keep order')
        item=f.selections[pick['selection']]
        self.assertGreater(len(item['request']['actions']),1)
        try:result=f.act(pick['selection'])
        except ValueError as error:self.fail('The selected offered control must retain its valid operation and binding: '+str(error))
        self.assertEqual(result['status'],'delivered')
        click=[a for t,a in driver.sent if t=='browser_click']
        self.assertEqual(len(click),1)
        want=next(r['ref'] for r in full['refs'] if r['name']=='Keep order')
        self.assertEqual(click[0]['ref'],want)
        f.close()
