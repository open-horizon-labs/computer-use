import live as l,inspect,asyncio,json,time
class Disconnect(l.Native):
 def __init__(self):super().__init__('supervision');self.drained=None
 def fence(self):
  if self.drained is not None:return self.drained
  t=time.perf_counter();self.proc.stdin.close();code=self.proc.wait(timeout=5);self.drained={'exit_code':code,'disconnect_wait_ms':(time.perf_counter()-t)*1000}
  if code!=0 or self.drained['disconnect_wait_ms']<700:raise RuntimeError('Disconnect did not retain supervision')
  return self.drained
async def main():
 out={'versions':l.preflight()};original=l.fresh_front();sentinel=l.m.h.Fixture();helper=l.Native('serial');c=Disconnect()
 try:
  row=await l.trial(c,'supervision','activation',-1,sentinel);out['row']=row;print(json.dumps(row),flush=True)
 finally:
  helper.call('bring_to_front',pid=original);out['cleanup_restored']=l.fresh_front()==original;sentinel.close();c.close();helper.close();(l.OUT/'native-disconnect.json').write_text(json.dumps(out,indent=2))
asyncio.run(main())
