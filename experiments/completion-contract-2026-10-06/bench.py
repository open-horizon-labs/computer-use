import asyncio,json,statistics
from pathlib import Path
from study import trial
async def main():
 rows=[];modes=['serial','supervision','evidence','combined']
 for rep in range(11):
  for mode in (modes if rep%2==0 else modes[::-1]):
   r=await trial(mode);r.update(rep=rep,warmup=rep==0);rows.append(r)
   assert r['terminal']=='complete' and r['state']['values']=={'name':'Alice','email':'a@example.test'}
 summary={m:statistics.median(r['decision_ms'] for r in rows if r['mode']==m and not r['warmup']) for m in modes}
 Path(__file__).with_name('benchmark.json').write_text(json.dumps({'scope':'Offline protocol fixture, 100 ms simulated supervision horizon, 25 ms app commit delay; NOT Cua/Arc driver performance','rows':rows,'median_decision_ms':summary},indent=2));print(summary)
if __name__=='__main__':asyncio.run(main())
