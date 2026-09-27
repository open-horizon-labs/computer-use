"""Repeatable CESS gate; policy promotion and semantic review remain separate."""
import copy
import json
from pathlib import Path
import random
from unittest.mock import patch

import dispatch
import gate
import simulation
import test_dispatch
from simulation import Simulation, corpus, case, stock

HERE=Path(__file__).resolve().parent


def main():
    definitions={c['id']:c for c in corpus()}
    current=[Simulation(c).run() for c in definitions.values()]
    original=gate.run()
    variants=[]
    for seed in range(40):
        request,evidence=stock();rng=random.Random(seed)
        mapping={a['id']:f'opaque-{rng.randrange(10**9)}' for a in request['actions']}
        for a in request['actions']:a['id']=mapping[a['id']]
        request['candidate_ids']=[mapping[i] for i in request['candidate_ids']]
        evidence['evidence']={mapping[k]:v for k,v in evidence['evidence'].items()}
        rng.shuffle(request['actions']);rng.shuffle(request['candidate_ids'])
        rename={'owner':f'field-{seed}-x','stock':f'field-{seed}-y'}
        request['fields']={rename[k]:v for k,v in request['fields'].items()}
        for rule in request['predicates']+request['order_by']:rule['field']=rename[rule['field']]
        for aid,fields in evidence['evidence'].items():
            evidence['evidence'][aid]={rename[k]:v for k,v in fields.items()}
        variants.append(Simulation(case(f'variant-{seed}',request,{'gliner2':evidence},['b'],['gliner2'])).run())
    mutations={}
    def check(name,cid):
        result=Simulation(definitions[cid]).run()
        mutations[name]={'rejected':not result['passed'],'case':cid,'actual_effects':result['actual_effects'],'routes':result['routes'],'verified':result['verified']}
    with patch.object(dispatch,'compile_plan',lambda r:{'steps':[{'model':'jev','method':'choose'}],'models':['jev'],'reducer':'offered_choice'}):
        check('always_jev','SIM-005-healthy-specialist')
    def no_recovery(self,request,current):
        return {**self._decide_once(request,current),'binding_digest':dispatch.request_digest(request)}
    with patch.object(dispatch.Engine,'decide',no_recovery):check('never_recover','SIM-002-unavailable-specialist')
    with patch.object(dispatch,'valid_probability',lambda x:True):check('accept_nan','SIM-008-nan-class-score')
    def unchecked(request,selected,current,execute):
        a=next(a for a in request['actions'] if a['id']==selected['action_id'])
        return execute(a['operation'],a['arguments'])
    with patch.object(simulation,'execute_bound',unchecked):check('trust_snapshot_string_only','SIM-006-binding-mutation')
    original_reducer=dispatch.reduce_match
    with patch.object(dispatch,'reduce_match',lambda r,e,**kw:original_reducer(r,{},**kw)):
        check('discard_partial_evidence','SIM-011-partial-hybrid-failure')
    with patch.object(simulation,'verify_state',lambda *args:True):check('selection_equals_success','SIM-015-no-effect-not-success')
    with patch.object(test_dispatch,'span_schema',lambda d:{'entities':d}):
        wrong=gate.run(['test_description_wire_contract_matches_upstream_schema_builder'])
        mutations['drop_label_descriptions']={'rejected':not wrong['passed'],'test':wrong}
    historical=HERE.parents[1]/'benchmarks/cua-capability-dispatch-2026-09-27/booking-100-119.json'
    replay=[]
    for row in json.loads(historical.read_text())['results']:
        for step in row['steps']:
            request=step['model']['request'];output=step['model']['decision']['provider_outputs'][0]
            answer=dispatch.Engine({'gliner2':lambda s,r,o=output:o}).decide(request,request['snapshot_id'])
            replay.append({'seed':row['seed'],'passed':answer.get('action_id')==step['choice']})
    # Preserve the real failing extraction for the proposed policy. No oracle is
    # passed into Engine or a provider; it remains the sandbox's output compare.
    live=json.loads((HERE/'simulation/cycle-07-live-providers.json').read_text())['results'][-1]
    request=live['trace'][0]['observation']
    extracted=live['trace'][0]['selection']['provider_outputs'][0]
    proposal=case('PROPOSED-boundary',request,{'gliner2':extracted,'jev':{'choice':'b'}},['b'],['gliner2','jev'])
    pending_default=Simulation(proposal,engine_options={"boundary_recheck":False}).run()
    pending_candidate=Simulation(proposal,engine_options={'boundary_recheck':True}).run()
    no_generic=copy.deepcopy(proposal);no_generic['frames'][0]['providers'].pop('jev');no_generic['approved']={'effects':[],'routes':['gliner2']}
    no_generic_result=Simulation(no_generic,engine_options={'boundary_recheck':True}).run()
    known_bad=copy.deepcopy(proposal);known_bad['frames'][0]['request']['predicates'].append({'field':'price','op':'gt','value':20});known_bad['approved']={'effects':[],'routes':['gliner2']}
    known_bad_result=Simulation(known_bad,engine_options={'boundary_recheck':True}).run()
    internal=copy.deepcopy(proposal)
    internal['frames'][0]['request']['predicates'][0]['value']='Acm'
    internal['approved']={'effects':[],'routes':['gliner2']}
    internal_result=Simulation(internal,engine_options={'boundary_recheck':True}).run()
    proposal_checks={'word_internal_substring_stays_excluded':internal_result['passed'],
                     'default_reproduces_failure':not pending_default['passed'],
                     'candidate_passes':pending_candidate['passed'],
                     'overlap_without_generic_cannot_act':no_generic_result['passed'],
                     'other_known_constraint_still_excludes':known_bad_result['passed']}
    result={'simulation':{'passed':sum(r['passed'] for r in current),'total':len(current)},
            'original_gate':original,'metamorphic':{'passed':sum(r['passed'] for r in variants),'total':len(variants)},
            'historical_replay':{'passed':sum(r['passed'] for r in replay),'total':len(replay)},
            'mutations':mutations,'proposal_checks':proposal_checks,
            'pending_policy':'CE-SIM-006 approved by user; default enabled; former policy preserved as negative control'}
    (HERE/'simulation/GATE.json').write_text(json.dumps(result,indent=2)+'\n')
    (HERE/'simulation/metamorphic.json').write_text(json.dumps(variants,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='original_gate'},indent=2))
    assert all(r['passed'] for r in current+variants+replay) and original['passed']
    assert all(x['rejected'] for x in mutations.values()) and all(proposal_checks.values())


if __name__=='__main__':main()
