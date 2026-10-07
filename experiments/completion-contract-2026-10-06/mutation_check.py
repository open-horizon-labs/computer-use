import asyncio,json
from pathlib import Path
from study import trial
async def main():
 receipts=[]
 for mode,scenario,mutant in [('evidence','late_reject','trust_echo'),('supervision','reject','skip_fence'),('combined','cancel','cancel_watchers')]:
  row=await trial(mode,scenario,mutant)
  try:
   if scenario=='cancel':assert row['supervisor_alive'], 'caller cancellation killed supervisors'
   else:assert row['terminal']=='rejected', 'keeper expected exact rejected outcome'
  except AssertionError as e:receipts.append({'mutant':mutant,'keeper_failed':True,'reason':str(e),'observed_terminal':row['terminal']})
  else:raise RuntimeError('Mutant survived its keeper: '+mutant)
 Path(__file__).with_name('mutation-check.json').write_text(json.dumps(receipts,indent=2))
if __name__=='__main__':asyncio.run(main())
