"""Direct Jev comparison, no training on Jev outputs or desktop actions."""
import argparse,json,os,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'inference/cua-decider'))
from decision_providers import Jev

a=argparse.ArgumentParser();a.add_argument('--input',required=True);a.add_argument('--output',required=True);args=a.parse_args()
os.environ.setdefault('TYPESAFE_CONNECT_SSH','homelab-personal-assembler')
parts=json.load(open(args.input));provider=Jev();out={}
try:
 for split,rows in parts.items():
  results=[];out[split]=results
  for row in rows:
   for removed in [False,True]:
    candidates={str(i):c for i,c in enumerate(row['candidates']) if not removed or i!=row['gold']}
    candidates.update(reobserve='Get more information; do not act',abstain='No current candidate is supported; do not act')
    state={'goal':row['query'],'observation':'Choose among the current candidate controls. Abstain or reobserve if no candidate is supported.'}
    start=time.perf_counter()
    try:
     answer=provider(state,candidates);choice=answer['choice'];accepted=choice not in ('abstain','reobserve')
     result={'id':row['id'],'target_removed':removed,'accepted':accepted,'correct':(not accepted if removed else choice==str(row['gold'])),'choice':choice,'model':answer.get('model'),'confidence':answer.get('confidence')}
    except Exception as e:result={'id':row['id'],'target_removed':removed,'accepted':False,'correct':False,'error':type(e).__name__}
    result['ms']=(time.perf_counter()-start)*1000;results.append(result)
    Path(args.output).write_text(json.dumps(out,indent=2)+'\n')
  print(split,len(results),'done',flush=True)
finally:provider.close()
