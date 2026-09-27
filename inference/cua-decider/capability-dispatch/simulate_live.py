"""Same sandboxed simulation, actual GLiNER2 and installed Jev/Qwen inference."""
import argparse
import json
from pathlib import Path

from providers import FleetGeneric, RemoteSpans
from simulation import corpus, Simulation
from dispatch import Engine


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--candidate-boundaries',action='store_true',default=True, help='Approved boundary recheck (enabled by default)')
    args=parser.parse_args()
    selected={'SIM-001-default-jev','SIM-002-unavailable-specialist','SIM-005-healthy-specialist','SIM-021-product-prices'}
    results=[]
    spans=RemoteSpans()
    try:
        for definition in corpus():
            if definition['id'] not in selected:continue
            if 'gliner2' in definition['frames'][0]['providers']:
                # The scripted case assumes its fixed extraction tape succeeds.
                # Actual inference may legitimately require S4.3 recovery.
                definition['approved']['routes']=[['gliner2'],['gliner2','jev']]
                definition['frames'][0]['providers']['jev']={}
            generic=FleetGeneric()
            try:
                result=Simulation(definition,{'gliner2':spans,'jev':generic},
                                  {'boundary_recheck':args.candidate_boundaries}).run()
                results.append(result)
                args.output.parent.mkdir(parents=True,exist_ok=True)
                args.output.write_text(json.dumps({'mode':'real provider inference, simulated state; no computer use',
                                                   'proposed_boundary_policy':args.candidate_boundaries,'results':results},indent=2)+'\n')
                print(json.dumps({'id':result['id'],'passed':result['passed'],'routes':result['routes'],'effects':result['actual_effects']}),flush=True)
            finally:generic.close()
        historical=Path(__file__).resolve().parents[2]/'benchmarks/cua-capability-dispatch-2026-09-27/booking-100-119.json'
        replay=[]
        for row in json.loads(historical.read_text())['results']:
            for index,step in enumerate(row['steps']):
                request=step['model']['request']
                answer=Engine({'gliner2':spans}).decide(request,request['snapshot_id'])
                replay.append({'seed':row['seed'],'turn':index,'expected':step['choice'],
                               'actual':answer.get('action_id'),'passed':answer.get('action_id')==step['choice'],
                               'decision':answer})
        args.output.with_name(args.output.stem+'-booking-replay.json').write_text(json.dumps(replay,indent=2)+'\n')
        print(json.dumps({'fresh_inference_on_historical_booking_requests':sum(r['passed'] for r in replay),'total':len(replay)}),flush=True)
    finally:spans.close()


if __name__=='__main__':main()
