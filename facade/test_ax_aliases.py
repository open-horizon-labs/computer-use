import copy
import unittest
from ax_aliases import table_aliases
from core import Facade
from test_core import FakeDriver,FakeChooser


def grid():
    nodes={}
    def add(role,parent=None,label=None,frame=None):
        i=len(nodes)
        nodes[i]={'element_index':i,'element_token':f's00000001:{i}','role':role,'enabled':True,'actions':['AXPress'],'frame':frame or {'x':0,'y':0,'w':200,'h':200}}
        if parent is not None:nodes[i]['parent_index']=parent
        if label is not None:nodes[i]['label']=label
        return i
    table=add('AXTable'); cells=[]
    for r in range(2):
        row=add('AXRow',table);line=[]
        for c in range(2):
            f={'x':c*100,'y':r*100,'w':100,'h':100}
            cell=add('AXCell',row,frame=f)
            button=add('AXButton',cell,f'Item {r}-{c}',f)
            line.append((cell,button))
        cells.append(line)
    aliases={}
    for c in range(2):
        col=add('AXColumn',table)
        for r in range(2):
            cell,button=cells[r][c]
            a=add('AXCell',col,frame=nodes[cell]['frame'].copy())
            b=add('AXButton',a,nodes[button]['label'],nodes[button]['frame'].copy())
            aliases[a]=cell;aliases[b]=button
    return nodes,aliases

class AliasTests(unittest.TestCase):
    def test_complete_grid_aliases(self):
        n,a=grid();self.assertEqual(table_aliases(n),a)
    def test_equal_label_different_frame_is_not_alias(self):
        n,a=grid();n[next(iter(a))]['frame']['x']+=1
        self.assertEqual(table_aliases(n),{})
    def test_missing_cell_preserves_ambiguity(self):
        n,a=grid();del n[next(iter(a))]
        self.assertEqual(table_aliases(n),{})
    def test_changed_enabled_or_action_preserves_ambiguity(self):
        for key,value in [('enabled',False),('actions',[]),('label','Different')]:
            n,a=grid();n[next(iter(a))][key]=value
            self.assertEqual(table_aliases(n),{})
    def test_missing_or_zero_frame_preserves_ambiguity(self):
        for frame in [{},{'x':0,'y':0,'w':0,'h':10}]:
            n,a=grid();n[next(iter(a))]['frame']=frame
            self.assertEqual(table_aliases(n),{})
    def test_real_repeated_controls_remain_ambiguous(self):
        n,a=grid()
        for node in n.values():
            if node['role']=='AXButton':node['label']='Same'
        class Driver(FakeDriver):
            def observe(self,*args):return {'snapshot_id':'s00000001','pid':1,'window_id':2,'elements':list(n.values()),'_image':b'pixels'}
        f=Facade(Driver())
        try:
            o=f.observe(1,2)
            d=f.choose(o['snapshot'],'Same',mode='exact',exact_name='Same',exact_role='AXButton')
            self.assertEqual(d['status'],'defer')
        finally:f.close()
    def test_offered_aliases_are_not_duplicate_semantic_alternatives(self):
        n,a=grid()
        class Driver(FakeDriver):
            def observe(self,*args):return {'snapshot_id':'s00000001','pid':1,'window_id':2,'elements':list(n.values()),'_image':b'pixels'}
        chooser=FakeChooser();f=Facade(Driver(),generic_factory=lambda:chooser)
        try:
            o=f.observe(1,2)
            alias=next(i for i,row in a.items() if row==3)
            d=f.choose(o['snapshot'],'Pick item',candidate_ids=['e3','e'+str(alias),'e5'])
            self.assertEqual(d['offered_count'],2)
            self.assertEqual([x['id'] for x in chooser.requests[0]['actions']],['e3','e5'])
        finally:f.close()
    def test_exact_alias_resolves_to_row_control(self):
        n,a=grid()
        class Driver(FakeDriver):
            def observe(self,*args):return {'snapshot_id':'s00000001','pid':1,'window_id':2,'elements':list(n.values()),'_image':b'pixels'}
        f=Facade(Driver())
        try:
            o=f.observe(1,2)
            self.assertEqual(sum('alias_of' in x for x in o['elements']),len(a))
            d=f.choose(o['snapshot'],'Item 0-0',mode='exact',exact_name='Item 0-0',exact_role='AXButton')
            self.assertEqual(d['selected_id'],'e3')
            self.assertEqual(d['route'],'exact_observed_control')
        finally:f.close()
