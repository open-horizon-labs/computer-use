"""Desktop-free state machine. Providers never receive the approved-output oracle.

Controlled responses deliberately include failures. These are projection simulations,
not measurements of model quality. The live-provider mode lives in simulate_live.py.
"""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path

from dispatch import Engine, execute_bound

HERE = Path(__file__).resolve().parent


def verify_state(effects, approved_effects):
    return bool(effects) and effects == approved_effects


def action(aid, text, effect=None, operation='click'):
    return {'id': aid, 'operation': operation, 'name': text, 'role': 'button',
            'description': text, 'evidence_text': text, 'enabled': True,
            'arguments': {'target': effect or aid}}


def span(text, value, confidence=.99):
    start = text.index(value)
    return {'text': value, 'start': start, 'end': start+len(value), 'confidence': confidence}


def stock():
    req = {'snapshot_id': 's1', 'kind': 'match', 'operation': 'click', 'coverage_complete': True,
           'goal': 'Select the Morgan-owned item with the fewest units.',
           'observation': 'Inventory rows, each with its own select control.',
           'fields': {'owner': {'description': 'Owner of this item', 'type': 'text'},
                      'stock': {'description': 'Number of units', 'type': 'number'}},
           'predicates': [{'field': 'owner', 'value': 'Morgan'}],
           'order_by': [{'field': 'stock', 'direction': 'asc'}],
           'candidate_ids': ['a', 'b'],
           'actions': [action('a', 'Morgan 12'), action('b', 'Morgan 7')]}
    ev = {'evidence': {'a': {'owner': [span('Morgan 12', 'Morgan')], 'stock': [span('Morgan 12', '12')]},
                       'b': {'owner': [span('Morgan 7', 'Morgan')], 'stock': [span('Morgan 7', '7')]}}}
    return req, ev


def exact(aid='a', effect=None):
    return {'snapshot_id': 's1', 'kind': 'exact', 'operation': 'click',
            'goal': 'Activate the current named control.', 'target': {'id': aid},
            'actions': [action(aid, 'Save', effect)]}


def case(cid, request, providers, effects, routes=None, **extras):
    return {'id': cid, 'frames': [{'request': request, 'providers': providers}],
            'approved': {'effects': effects, 'routes': routes}, **extras}


def corpus():
    cases = []
    req = {'snapshot_id': 's1', 'operation': 'click', 'goal': 'Open the settings page.',
           'observation': 'Navigation: Settings, Reports',
           'actions': [action('a', 'Settings'), action('b', 'Reports')]}
    cases.append(case('SIM-001-default-jev', req, {'jev': {'choice': 'a'}}, ['a'], ['jev']))
    req, ev = stock()
    cases.append(case('SIM-002-unavailable-specialist', req, {'jev': {'choice': 'b'}}, ['b'], ['jev']))
    cases.append(case('SIM-003-specialist-error', req, {'gliner2': {'raise': 'offline'}, 'jev': {'choice': 'b'}}, ['b'], ['gliner2','jev']))
    incomplete = copy.deepcopy(ev); incomplete['evidence']['b'].pop('stock')
    cases.append(case('SIM-004-incomplete-extraction', req, {'gliner2': incomplete, 'jev': {'choice': 'b'}}, ['b'], ['gliner2','jev']))
    cases.append(case('SIM-005-healthy-specialist', req, {'gliner2': ev, 'jev': {'choice': 'a'}}, ['b'], ['gliner2']))
    cases.append(case('SIM-006-binding-mutation', exact(), {}, [], [], tamper=True))
    bad = copy.deepcopy(ev)
    bad['evidence']['b']['owner'][0]['confidence'] = float('nan')
    cases.append(case('SIM-007-nan-span-score', req, {'gliner2': bad}, [], ['gliner2']))
    cls = {'snapshot_id': 's1', 'kind': 'classify', 'operation': 'click', 'goal': 'Route the billing issue.',
           'labels': {'billing': 'Invoice/payment issue'}, 'label_actions': {'billing': 'a'},
           'min_confidence': .9, 'actions': [action('a', 'Billing')]}
    cases.append(case('SIM-008-nan-class-score', cls, {'decide': {'label': 'billing', 'confidence': float('nan')}}, [], ['decide']))
    cases.append(case('SIM-009-classification-map', cls, {'decide': {'label': 'billing', 'confidence': .97}}, ['a'], ['decide']))
    rank = copy.deepcopy(req); rank['predicates'] = []; rank['goal'] = 'Select the item with fewest units, regardless of owner.'
    cases.append(case('SIM-010-ranking-only', rank, {'gliner2': ev}, ['b'], ['gliner2']))
    hybrid = copy.deepcopy(req); hybrid['fields']['urgency'] = {'labels': {'high': 'Time sensitive', 'low': 'Can wait'}, 'min_confidence': .9}
    hybrid['predicates'].append({'field': 'urgency', 'value': 'high'})
    hybrid['actions'][0]['evidence_text'] = 'Taylor 12'; hybrid['actions'][0]['description'] = 'Taylor 12'
    hev = copy.deepcopy(ev); hev['evidence']['a']['owner'] = [span('Taylor 12','Taylor')]
    cases.append(case('SIM-011-partial-hybrid-failure', hybrid,
                      {'gliner2': hev, 'decide': {'raise': 'offline'}, 'jev': {'first_offered': True}}, ['b'], ['gliner2','decide','jev']))
    cases.append(case('SIM-012-stale-request', req, {'gliner2': ev,'jev': {'choice':'b'}}, [], [], observed_snapshot='s2'))
    cases.append(case('SIM-013-stale-before-execution', exact(), {}, [], [], race=True))
    sem = {'snapshot_id':'s1','kind':'semantic','operation':'click','goal':'Open settings','actions':[action('a','Settings')]}
    cases.append(case('SIM-014-invented-jev-action', sem, {'jev':{'choice':'unoffered'}}, [], ['jev']))
    cases.append(case('SIM-015-no-effect-not-success', exact(effect='noop'), {}, [], [], expect_verified=False))
    cases.append(case('SIM-016-exact-no-model', exact(), {'jev':{'choice':'wrong'}}, ['a'], []))
    for name, shape, lang, family in [('simple-ner','spans','en','gliner'), ('records','records','en','gliner2.5'),
                                      ('relations','relations','en','gliner2.5'), ('multilingual','spans','es','gliner2.5')]:
        variant=copy.deepcopy(req); variant.update(shape=shape,language=lang)
        if family=='gliner':
            for field in variant['fields'].values(): field.pop('description')
        cases.append(case('SIM-route-'+name,variant,{family:ev},['b'],[family]))
    tie=copy.deepcopy(req);tie['order_by']=[]
    cases.append(case('SIM-017-tie-is-not-permission',tie,{'gliner2':ev,'jev':{'choice':'a'}},[],None))
    invalid=copy.deepcopy(req);invalid['predicates'][0]['op']='invented_operator'
    cases.append(case('SIM-018-malformed-contract',invalid,{'gliner2':ev,'jev':{'choice':'a'}},[],None))
    no_match=copy.deepcopy(req);no_match['predicates'][0]['value']='Casey'
    cases.append(case('SIM-019-no-revive-known-exclusion',no_match,{'gliner2':ev,'jev':{'first_offered':True}},[],None))
    # Three changing observations; effects differ from the control IDs. A changed
    # first observation does not certify the final requested state.
    frames=[]
    for i,(aid,effect) in enumerate([('initial','slot_lost'),('replacement','selected'),('confirm','confirmed')]):
        r=exact(aid,effect);r['snapshot_id']=f'flow-{i}';frames.append({'request':r,'providers':{}})
    cases.append({'id':'SIM-020-changing-state-flow','frames':frames,
                  'approved':{'effects':['slot_lost','selected','confirmed'],'routes':[]}})
    priced = copy.deepcopy(req)
    priced.update(goal='Choose the cheaper Acme product.', fields={
        'brand': {'description': 'Manufacturer or brand name', 'type': 'text'},
        'price': {'description': 'Price in US dollars', 'type': 'money', 'currency': 'USD'}},
        predicates=[{'field':'brand','value':'Acme'}],order_by=[{'field':'price','direction':'asc'}],
        actions=[action('a','Acme product: $12'),action('b','Acme product: $7')])
    pev={'evidence':{a['id']:{'brand':[span(a['evidence_text'],'Acme')],
                           'price':[span(a['evidence_text'], '$12' if a['id']=='a' else '$7')]}
                     for a in priced['actions']}}
    cases.append(case('SIM-021-product-prices',priced,{'gliner2':pev},['b'],['gliner2']))
    clock=copy.deepcopy(req)
    clock.update(fields={'start':{'description':'Start time','type':'time'}},
                 predicates=[{'field':'start','op':'gt','value':'2 PM'}],
                 order_by=[{'field':'start','direction':'asc'}],
                 actions=[action('a','Starts 2:00 PM'),action('b','Starts 2:05 PM')])
    cev={'evidence':{a['id']:{'start':[span(a['evidence_text'],a['evidence_text'][7:])]}
                     for a in clock['actions']}}
    cases.append(case('SIM-022-strict-time-boundary',clock,{'gliner2':cev},['b'],['gliner2']))
    cases.append(case('SIM-023-failed-fallback-stops',req,{'jev':{'raise':'offline'}},[],['jev']))
    cases.append(case('SIM-024-invalid-kind-no-fallback',{**req,'kind':'typo'}, {'jev':{'choice':'a'}},[],[]))
    return cases


class Simulation:
    def __init__(self, definition, providers_override=None, engine_options=None):
        self.definition=copy.deepcopy(definition)
        self.effects=[];self.calls=[];self.trace=[]
        self.providers_override=providers_override or {}
        self.engine_options=engine_options or {}

    def run(self):
        for index,frame in enumerate(self.definition['frames'][:6]):
            request=copy.deepcopy(frame['request'])
            current=self.definition.get('observed_snapshot',request['snapshot_id'])
            def make_provider(family,response):
                def call(step,provider_request):
                    if 'approved' in provider_request or 'expected' in provider_request:
                        raise AssertionError('oracle leaked into provider request')
                    self.calls.append({'family':family,'step':copy.deepcopy(step),'request':copy.deepcopy(provider_request)})
                    if callable(response):return response(step,provider_request)
                    if 'raise' in response:raise RuntimeError('injected_provider_failure')
                    if response.get('first_offered'):
                        return {'choice':provider_request['actions'][0]['id']}
                    return copy.deepcopy(response)
                return call
            providers={f:make_provider(f,self.providers_override.get(f,r)) for f,r in frame['providers'].items()}
            selected=Engine(providers,**self.engine_options).decide(request,current)
            if self.definition.get('tamper'):
                request['actions'][0]['arguments']['target']='forbidden_effect'
            if self.definition.get('race'):current='changed-after-selection'
            event={'frame':index,'observation':copy.deepcopy(frame['request']), 'selection':selected}
            if selected.get('action_authorized'):
                def apply(operation,args):
                    # Sandboxed world state, no Driver or OS effects.
                    target=args['target']
                    if target!='noop':self.effects.append(target)
                    return {'observed_effects':list(self.effects),'scene_revision':index+1}
                try:
                    event['execution']=execute_bound(request,selected,current,apply)
                except (ValueError,KeyError,StopIteration) as exc:
                    event['execution_rejected']=type(exc).__name__
            self.trace.append(event)
            if not selected.get('action_authorized') or 'execution_rejected' in event:
                break
        actual_routes=[call['family'] for call in self.calls]
        approved=self.definition['approved']
        effects_ok=self.effects==approved['effects']
        # Postcondition depends on independently observed state, not returned choice.
        verified=verify_state(self.effects, approved['effects'])
        options = approved['routes']
        if options is not None and (not options or isinstance(options[0],str)):
            options = [options]
        routes_ok=(options is None or any(
            sorted(actual_routes)==sorted(option) and ('jev' not in option or actual_routes[-1]=='jev')
            for option in options))
        verified_ok=verified==self.definition.get('expect_verified',bool(approved['effects']))
        return {'id':self.definition['id'],'passed':effects_ok and routes_ok and verified_ok,
                'approved':approved,'actual_effects':self.effects,'routes':actual_routes,
                'verified':verified,'trace':self.trace,'provider_calls':self.calls}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--case',action='append');args=parser.parse_args()
    cases=[c for c in corpus() if not args.case or c['id'] in args.case]
    results=[Simulation(case).run() for case in cases]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'mode':'controlled-provider state simulation; no computer use',
                                      'results':results},indent=2)+'\n')
    print(json.dumps({'passed':sum(r['passed'] for r in results),'total':len(results),
                      'failures':[r['id'] for r in results if not r['passed']]}))


if __name__=='__main__':main()
