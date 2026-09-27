"""Paired recorded-observation comparison; real inference, no desktop actions."""
import copy
import json
import os
from pathlib import Path
import statistics
import sys
import time

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from decision_providers import Jev
from dispatch import Engine
from providers import FleetGeneric, RemoteSpans
from simulation import corpus

class JevOnly:
    def __init__(self): self.client=Jev()
    def __call__(self,step,request):
        candidates={a['id']:a.get('description',a.get('evidence_text',a.get('name',''))) for a in request['actions']}
        candidates.update(reobserve='Observe again; do not act on unresolved evidence',abstain='Stop when no safe authorized choice is supported')
        context={k:request[k] for k in ('fields','predicates','order_by','candidate_ids','coverage_complete','fallback_id','specialist_context') if k in request}
        state={'goal':request.get('goal', 'Choose the unique action satisfying all caller criteria and ordering. Use the supplied fallback only when every candidate is excluded; defer on unresolved evidence or ties.')+'\nCaller criteria and existing evidence: '+json.dumps(context),'observation':request.get('observation',''),'history':request.get('history',[])}
        result=self.client(state,candidates)
        if result.get('choice') in ('reobserve','abstain'):result['action_authorized']=False
        return result
    def close(self):self.client.close()

def main():
    os.environ.setdefault('TYPESAFE_CONNECT_SSH','homelab-personal-assembler')
    selected={'SIM-001-default-jev','SIM-002-unavailable-specialist','SIM-005-healthy-specialist','SIM-021-product-prices'}
    cases=[]
    for c in corpus():
        if c['id'] in selected:cases.append((c['id'],c['frames'][0]['request'],c['approved']['effects'][0],c['id']=='SIM-002-unavailable-specialist'))
    historical=HERE.parents[1]/'benchmarks/cua-capability-dispatch-2026-09-27/booking-100-119.json'
    for row in json.loads(historical.read_text())['results']:
        for i,s in enumerate(row['steps']):cases.append((f"booking-{row['seed']}-{i}",s['model']['request'],s['choice'],False))
    start=time.perf_counter();spans=RemoteSpans();startup=(time.perf_counter()-start)*1000
    jev=JevOnly();generic=FleetGeneric();results=[]
    output=HERE/'simulation/jev-comparison.json'
    try:
        for index,(cid,req,expected,unavailable) in enumerate(cases):
            generic.close();generic=FleetGeneric() # Independent cases must not inherit unverified progress.
            row={'id':cid,'expected':expected,'arms':{}}
            for arm in (['capability','jev_only'] if index%2==0 else ['jev_only','capability']):
                request=copy.deepcopy(req)
                if arm=='jev_only':request['kind']='semantic';providers={'jev':jev}
                else:providers={'jev':generic,**({} if unavailable else {'gliner2':spans})}
                start=time.perf_counter()
                answer=Engine(providers).decide(request,request['snapshot_id'])
                row['arms'][arm]={'ms':(time.perf_counter()-start)*1000,'correct':answer.get('action_id')==expected,'decision':answer}
            results.append(row)
            output.write_text(json.dumps({'mode':'paired real inference over fixed observations; no desktop execution','extractor_startup_ms':startup,'results':results},indent=2)+'\n')
            print(json.dumps({'id':cid,**{k:{'correct':v['correct'],'ms':round(v['ms'])} for k,v in row['arms'].items()}}),flush=True)
        summary={}
        for arm in ('capability','jev_only'):
            vals=[r['arms'][arm]['ms'] for r in results]
            summary[arm]={'correct':sum(r['arms'][arm]['correct'] for r in results),'total':len(results),'median_ms':statistics.median(vals),'mean_ms':statistics.mean(vals),'total_ms':sum(vals),'first_request_ms':vals[0],'median_excluding_first_ms':statistics.median(vals[1:])}
        data=json.loads(output.read_text());data['summary']=summary;output.write_text(json.dumps(data,indent=2)+'\n');print(json.dumps(summary),flush=True)
    finally:spans.close();generic.close();jev.close()
if __name__=='__main__':main()
