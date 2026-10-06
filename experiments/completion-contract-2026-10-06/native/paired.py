from pathlib import Path
import live as l
cua_trial=l.trial
exec(Path(__file__).with_name('arc_reference.py').read_text().rsplit('asyncio.run(main())',1)[0])
async def paired():
 versions=l.preflight();helper=l.Native('evidence');arc=Arc(helper);sentinel=l.m.h.Fixture();original=l.fresh_front();out={'versions':versions,'rows':[]}
 try:
  for rep in range(5):
   for client in ([helper,arc] if rep%2==0 else [arc,helper]):
    l.preflight();row=await (l.trial if client is arc else cua_trial)(client,'evidence','stable',rep,sentinel);row['mode']='arc_ack' if client is arc else 'cua_ack';row['warmup']=rep==0;out['rows'].append(row);print(json.dumps({k:row.get(k) for k in ('mode','decision_ms','strict_pass','foreground_preserved','error')}),flush=True)
    if not row['strict_pass'] or not row['foreground_preserved'] or row.get('competing_input_detected'):raise RuntimeError('Paired qualification/interference failure')
 finally:
  helper.call('bring_to_front',pid=original);out['cleanup_restored']=l.fresh_front()==original;sentinel.close();arc.close();helper.close();(l.OUT/'paired-results.json').write_text(json.dumps(out,indent=2))
asyncio.run(paired())
