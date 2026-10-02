"""Real captured iOS switch ancestry; offline, no local provider starts."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import mobile
import mobile_hierarchy as hierarchy
from core import Facade
ROOTS = json.loads((Path(__file__).parent / 'fixtures/mobile/ios_developer.real.hierarchy.json').read_text())['data']['elements']

class Hierarchy(unittest.TestCase):
    def target(self, roots):
        target, problem = mobile.resolve(hierarchy.normalize_tree(roots), 'Dark Appearance', False, (lambda e: e['role'] == 'control',))
        self.assertIsNone(problem)
        return target

    def parent(self, roots):
        def walk(nodes):
            for node in nodes:
                if node.get('type') == 'Switch' and node.get('label') == 'Dark Appearance':
                    return node
                found = walk(node.get('children', []))
                if found:
                    return found
        return walk(roots)

    def test_real_child_not_label_row_center(self):
        target = self.target(ROOTS)
        self.assertEqual(target['ref'], '@e6')
        self.assertEqual(target['activation']['ref'], '@e8')
        self.assertEqual(target['activation']['bounds'], (305, 183, 63, 28))
        calls = []
        mob = mobile.Mobile(backend=object())
        mob._act = lambda *args: calls.append(args)
        mob.tap('exact-device', target)
        self.assertEqual(calls[0][1], {'device': 'exact-device', 'ref': '@e8'})

    def test_ambiguous_or_conflicting_children_refuse(self):
        for change in ('duplicate', 'state', 'ref', 'label', 'disabled', 'negative_bounds', 'contradictory_flag', 'duplicate_ref'):
            roots = copy.deepcopy(ROOTS)
            parent = self.parent(roots)
            child = parent['children'][1]
            if change == 'duplicate': parent['children'].append({**copy.deepcopy(child), 'ref':'@e9999'})
            elif change == 'state': child['value'] = '1'
            elif change == 'ref': child.pop('ref')
            elif change == 'label': child['label'] = 'Other setting'
            elif change == 'disabled': child['enabled'] = False
            elif change == 'negative_bounds': child['rect']['width'] = child['rect']['height'] = -1
            elif change == 'duplicate_ref': roots.append(copy.deepcopy(child))
            else:
                parent['value'] = child['value'] = '1'
                child['checked'] = False
            with self.subTest(change=change):
                mob = mobile.Mobile(backend=object())
                mob._act = lambda *args: self.fail('must not deliver')
                with self.assertRaisesRegex(mobile.MobileGap, 'switch_activation_ambiguous'):
                    mob.tap('exact-device', self.target(roots))

    def test_ancestry_not_flat_geometry(self):
        roots = copy.deepcopy(ROOTS)
        roots.append(self.parent(roots)['children'].pop(1))
        self.assertIn('activation_refusal', self.target(roots))

    def test_reference_churn_is_not_progress_but_bounds_change_is(self):
        original = hierarchy.normalize_tree(ROOTS)
        roots = copy.deepcopy(ROOTS)
        child = self.parent(roots)['children'][1]
        child['ref'] = '@e999'
        self.assertEqual(mobile.signature(original), mobile.signature(hierarchy.normalize_tree(roots)))
        child['ref'] = '@e8'
        child['rect']['x'] += 1
        self.assertNotEqual(mobile.signature(original), mobile.signature(hierarchy.normalize_tree(roots)))

    def test_custom_backend_never_starts_local_hierarchy(self):
        self.assertIsNone(mobile.Mobile(backend=object()).hierarchy_reader)

    def test_changed_toggle_state_refuses_flip_and_set_is_idempotent(self):
        roots = copy.deepcopy(ROOTS)
        def flat(nodes):
            out = []
            for n in nodes:
                out.append({**n, 'coordinates': n.get('rect', {})})
                out.extend(flat(n.get('children', [])))
            return out
        class Backend:
            def call(self, tool, args, **kwargs):
                if kwargs.get('mutating'):
                    raise AssertionError('stale or already-set switch must not receive input')
                return mobile.ELEMENTS_PREFIX + json.dumps(flat(roots)), False
        f = Facade(mobile=mobile.Mobile(Backend(), hierarchy_reader=lambda device: copy.deepcopy(roots)), sleep=lambda s: None)
        seen = f.look(device='owned-device')
        parent = self.parent(roots)
        parent['value'] = parent['children'][1]['value'] = '1'
        result = f.do('flip', device='owned-device', look_id=seen['look_id'], steps=[{'do':'press','control':'Dark Appearance','expect':None}])
        self.assertEqual(result['reason'], 'page_changed_since_look')
        changed = f.look(device='owned-device')
        self.assertNotEqual(seen['look_id'], changed['look_id'])
        result = f.do('set', device='owned-device', look_id=seen['look_id'], steps=[{'do':'press','control':'Dark Appearance','expect':'checked'}])
        self.assertEqual((result['status'],result['delivery']), ('done','none'))

    def test_independent_toggle_state_not_tap_ack_or_other_switch(self):
        before = hierarchy.normalize_tree(ROOTS)
        target = self.target(ROOTS)
        self.assertEqual(mobile.expect_check(before, before, 'checked', target=target)['status'], 'unknown')
        roots = copy.deepcopy(ROOTS)
        parent = self.parent(roots)
        parent['value'] = parent['children'][1]['value'] = '1'
        self.assertEqual(mobile.expect_check(hierarchy.normalize_tree(roots), before, 'checked', target=target)['status'], 'satisfied')
        parent['value'] = parent['children'][1]['value'] = ''
        self.assertEqual(mobile.expect_check(hierarchy.normalize_tree(roots), before, 'unchecked', target=target)['status'], 'unknown')

    def test_explicit_unchecked_flag_and_conflicting_value(self):
        e = mobile.normalize({'type':'Switch','checked':False}, 0)
        self.assertEqual(mobile.toggle_state(e), 'unchecked')
        e['value'] = '1'
        self.assertIsNone(mobile.toggle_state(e))

    def test_conflicting_overlapping_targets_cannot_prove_checked(self):
        target = self.target(ROOTS)
        checked = copy.deepcopy(target)
        checked['value'] = '1'
        self.assertEqual(mobile.expect_check([checked, target], None, 'checked', target=target)['status'], 'unknown')

    def test_malformed_or_excessive_tree_is_typed(self):
        roots = copy.deepcopy(ROOTS)
        self.parent(roots)['children'] = 42
        with self.assertRaisesRegex(mobile.MobileGap, 'mobile_hierarchy_unavailable'):
            hierarchy.normalize_tree(roots)
        deep = {'type':'Other'}
        for i in range(66): deep = {'type':'Other','children':[deep]}
        with self.assertRaisesRegex(mobile.MobileGap, 'mobile_hierarchy_unavailable'):
            hierarchy.normalize_tree([deep])

    def test_provider_literal_command_exact_device_and_bounded(self):
        calls = []
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return type('Result', (), {'returncode': 0, 'stdout': json.dumps({'status':'ok','data':{'elements':ROOTS}})})()
        with patch.dict('os.environ', {'CUA_MOBILECLI_COMMAND': '["worker", "$(literal)"]'}):
            self.assertEqual(hierarchy.read('exact-device', run), ROOTS)
        self.assertEqual(calls[0][0], ['worker', '$(literal)', 'dump', 'ui', '--device', 'exact-device'])
        self.assertEqual(calls[0][1]['timeout'], mobile.CALL_TIMEOUT_S)
        with patch.dict('os.environ', {'CUA_MOBILECLI_COMMAND': '"not argv"'}):
            with self.assertRaises(mobile.MobileGap):
                hierarchy.read('exact-device', lambda *a, **kw: self.fail('invalid config'))

class AndroidHierarchy(unittest.TestCase):
    def roots(self):
        return json.loads((Path(__file__).parent / 'fixtures/mobile/android_display.real.raw.json').read_text())['hierarchy']

    def target(self, roots):
        return next(e for e in hierarchy.normalize_android(roots) if e['kind']=='Switch')

    def test_real_false_is_known_and_missing_is_unknown(self):
        roots=self.roots()
        target=self.target(roots)
        self.assertEqual(mobile.toggle_state(target), 'unchecked')
        self.assertEqual(target['bounds'], (901,725,137,126))
        self.assertIsNone(target['ref'])
        def walk(nodes):
            for n in nodes:
                if n['class']=='android.widget.Switch':return n
                child=walk(n.get('children') or [])
                if child:return child
        raw=walk(roots)
        raw.pop('checked')
        unknown=self.target(roots)
        self.assertIsNone(mobile.toggle_state(unknown))
        self.assertEqual(mobile.analyze([unknown])['toggles'][0]['state'], 'unknown')
        self.assertNotEqual(mobile.look_id_for(mobile.analyze([target]), [], 'device'), mobile.look_id_for(mobile.analyze([unknown]), [], 'device'))

    def test_invalid_tree_is_typed_and_invisible_cannot_be_live(self):
        roots=self.roots()
        for change in ('children','bounds','class','overflow'):
            bad=copy.deepcopy(roots)
            if change=='children':bad[0]['children']=42
            elif change=='bounds':bad[0]['rect']['width']=-1
            elif change=='overflow':bad[0]['rect']['width']=10**500
            else:bad[0]['class']=None
            with self.subTest(change=change), self.assertRaises(mobile.MobileGap):hierarchy.normalize_android(bad)
        raw={'class':'android.widget.Switch','text':'Hidden','checkable':True,'checked':False,'visible':False,'rect':{'x':1,'y':1,'width':10,'height':10}}
        self.assertFalse(mobile.live(hierarchy.normalize_android([raw])[0]))
        raw['visible']=True
        for flag in ('visible','enabled'):
            parent={'class':'android.widget.FrameLayout','rect':{'x':0,'y':0,'width':100,'height':100},flag:False,'children':[copy.deepcopy(raw)]}
            with self.subTest(ancestor_flag=flag):
                self.assertFalse(mobile.live(hierarchy.normalize_android([parent])[0]))

    def test_custom_backend_no_provider_and_conditional_complete_replacement(self):
        self.assertIsNone(mobile.Mobile(backend=object()).android_hierarchy_reader)
        roots=self.roots()
        payload=[{'type':'android.widget.Switch','text':'old','coordinates':{'x':1,'y':1,'width':10,'height':10}}]
        class Backend:
            def call(self,*args,**kwargs):return mobile.ELEMENTS_PREFIX+json.dumps(payload),False
        calls=[]
        mob=mobile.Mobile(Backend(), android_hierarchy_reader=lambda device: calls.append(device) or roots)
        els=mob._read('exact-owned-device')
        self.assertEqual(calls,['exact-owned-device'])
        self.assertNotIn('old', [e['text'] for e in els])
        payload[0]['checked']=True
        self.assertEqual(mob._read('exact-owned-device')[0]['text'],'old')
        self.assertEqual(len(calls),1)

    def test_raw_literal_command_and_invalid_payload(self):
        roots=self.roots();calls=[]
        def run(argv,**kwargs):
            calls.append(argv)
            return type('Result',(),{'returncode':0,'stdout':json.dumps({'status':'ok','data':{'rawData':json.dumps({'hierarchy':roots})}})})()
        self.assertEqual(hierarchy.read('exact-device',run,raw=True), roots)
        self.assertEqual(calls[0][-5:],['ui','--device','exact-device','--format','raw'])
        with self.assertRaises(mobile.MobileGap):
            hierarchy.read('exact-device',lambda *a,**k:type('R',(),{'returncode':0,'stdout':'{"status":"ok","data":{}}'})(),raw=True)

if __name__ == '__main__': unittest.main()
