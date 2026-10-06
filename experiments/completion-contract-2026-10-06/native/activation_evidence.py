import live as l,asyncio,json
async def main():
 original=l.fresh_front();out={'versions':l.preflight()};sentinel=l.m.h.Fixture();c=l.Native('evidence')
 try:
  row=await l.trial(c,'evidence','activation',-1,sentinel);out['row']=row
 finally:
  c.call('bring_to_front',pid=original);out['cleanup_restored']=l.fresh_front()==original;sentinel.close();c.close();(l.OUT/'activation-evidence.json').write_text(json.dumps(out,indent=2))
asyncio.run(main())
