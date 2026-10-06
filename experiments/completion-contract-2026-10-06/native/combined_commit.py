from pathlib import Path
import live as l,inspect
original=inspect.getsource(l.trial)
exec(Path(__file__).with_name('arc_reference.py').read_text().rsplit('asyncio.run(main())',1)[0])
insert='''  if mode=='combined':
   proof=await c.observe(f,w)
   if not m.evidence(proof,f.pid,w)['record_a_visible'] or f.state().get('record')!='Record A':raise RuntimeError('context_changed')
   if any(m.h.find(c,proof,{'name':'Full name','email':'Email'}[field]).get('value')!=value for _,field,value in txs):raise RuntimeError('commit_proof_failed')
   row['committed_ms']=(time.perf_counter()-start)*1000
   row['supervision_at_commit']='pending_owned'
'''
exec(original.replace("  if mode in ('supervision','combined'):row['fence']=c.fence()",insert+"  if mode in ('supervision','combined'):row['fence']=c.fence()"),l.__dict__)
cua_trial=l.trial
async def main():
 versions=l.preflight();helper=l.Native('combined');arc=Arc(helper);sentinel=l.m.h.Fixture();original_front=l.fresh_front();out={'versions':versions,'rows':[]}
 try:
  for rep in range(5):
   for client in ([helper,arc] if rep%2==0 else [arc,helper]):
    l.preflight()
    if client is arc:
     exec(source,l.__dict__);row=await l.trial(client,'evidence','stable',rep,sentinel)
    else:row=await cua_trial(client,'combined','stable',rep,sentinel)
    row['mode']='arc_ack' if client is arc else 'combined';row['warmup']=rep==0;out['rows'].append(row);print(json.dumps({k:row.get(k) for k in ('mode','committed_ms','decision_ms','strict_pass','foreground_preserved','error')}),flush=True)
    if not row['strict_pass'] or not row['foreground_preserved'] or row.get('competing_input_detected'):raise RuntimeError('Combined qualification/interference failure')
 finally:
  helper.call('bring_to_front',pid=original_front);out['cleanup_restored']=l.fresh_front()==original_front;sentinel.close();arc.close();helper.close();(l.OUT/'combined-commit.json').write_text(json.dumps(out,indent=2))
asyncio.run(main())
