import asyncio,os,sys,json,time,uuid,hashlib,subprocess,fcntl,threading
from pathlib import Path
# Candidate paths and provider configuration are supplied by the caller.
packet=Path(os.environ['CUA_OBSERVATION_FIXTURE_SOURCE']);sys.path.insert(0,str(packet))
import observe_matrix as m
from tree_geometry import TreeGeometryDriver
OUT=Path(__file__).resolve().parent;ROOT=Path(os.environ['CUA_PROJECTION_SOURCE']);BINARY='/tmp/cua-action-latency-target-20261006/release/examples/supervised_host'
def fresh_front():return int(subprocess.check_output([sys.executable,'-c','import AppKit;print(AppKit.NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier())'],text=True).strip())
def preflight():
 import Quartz
 if (Quartz.CGSessionCopyCurrentDictionary() or {}).get('CGSSessionScreenIsLocked'):raise RuntimeError('Locked desktop')
 latest=subprocess.check_output(['git','-C',str(ROOT),'ls-remote','origin','refs/heads/main'],text=True).split()[0]
 if latest!='5227ad637590a15976413b1a33f8693fac0e9a7e':raise RuntimeError('Upstream advanced; rebuild before comparison')
 return m.h.candidate_versions()
class Native(m.WireMCP):
 def __init__(self,mode):
  argv=[BINARY]+(['--evidence-only'] if mode=='evidence' else ['--deferred-supervision'] if mode in ('supervision','combined') else []);super().__init__(argv,'native-'+mode);self.mode=mode;self.session='native-completion-'+mode+'-'+uuid.uuid4().hex[:6];self.reader=TreeGeometryDriver(m.Driver(self))
 def call(self,name,**args):
  if 'session' in self.schemas[name].get('properties',{}):args['session']=self.session
  return super().call(name,**args)
 async def observe(self,f,w):return await self.reader.call('get_window_state',{'pid':f.pid,'window_id':w,'include_screenshot':True,'include_accessibility_tree':True,'timeout_ms':1000})
 def start(self,args):
  args={**args,'session':self.session}
  return self.request('research/start',{'name':'set_value','arguments':args})['receipt']
 def fence(self):
  r=self.request('research/fence',{})
  if any(v is None or v.get('isError') for v in r['receipts'].values()):raise RuntimeError('Action failed or uncertain')
  return r
async def ack(f,tx,field,value,w,timeout=2):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  state=f.state()
  if state.get('record')!='Record A':raise RuntimeError('context_changed')
  a=state.get('transactions',{}).get(tx,{})
  if a.get('status')!='armed' and a:
   if any(a.get(k)!=v for k,v in {'tx':tx,'field':field,'pid':f.pid,'window_id':w,'record':'Record A','generation':0}.items()):raise RuntimeError('ack_binding')
   if a['status']!='committed':raise RuntimeError('rejected')
   if a.get('value')!=value or state.get(field)!=value:raise RuntimeError('final_value_mismatch')
   return a
  await asyncio.sleep(.01)
 raise RuntimeError('ack_unavailable')
async def trial(c,mode,scenario,rep,sentinel):
 saved=m.h.HERE;m.h.HERE=OUT/'fixture';f=m.h.Fixture();m.h.HERE=saved
 row={'mode':mode,'scenario':scenario,'rep':rep,'terminal':'handoff','strict_pass':False,'writes':0};receipt_ids=[];txs=[]
 try:
  w=await m.window_ready(c,f)
  _,err=c.call('bring_to_front',pid=sentinel.pid)
  if err:raise RuntimeError('sentinel_activation_failed')
  await asyncio.to_thread(m.h.wait_for,lambda:sentinel.state().get('active'),3)
  if fresh_front()!=sentinel.pid:raise RuntimeError('sentinel_not_foreground')
  sw=await asyncio.to_thread(m.h.wait_for,lambda:m.h.windows(sentinel.pid).get('Reference Bench Form'))
  row['foreground_binding']=c.request('research/restore_target',{'pid':sentinel.pid,'window_id':sw})
  if not all(row['foreground_binding'].get(k) is True for k in ('registered','cocoa_front_matches','native_front_matches')):raise RuntimeError('foreground_binding_failed')
  observed_active=False;interfered=False;stop=threading.Event()
  def monitor():
   nonlocal observed_active,interfered
   import Quartz
   while not stop.wait(.005):
    observed_active|=bool(f.state().get('active'))
    interfered|=min(Quartz.CGEventSourceSecondsSinceLastEventType(Quartz.kCGEventSourceStateHIDSystemState,k) for k in (Quartz.kCGEventKeyDown,Quartz.kCGEventLeftMouseDown,Quartz.kCGEventMouseMoved))<.005
  watcher=threading.Thread(target=monitor,daemon=True);watcher.start();start=time.perf_counter()
  for label,field,value in [('Full name','name','Native Person'),('Email','email','native@example.invalid')]:
   if scenario!='stable' and field=='email':break
   a=await c.observe(f,w);first=m.h.find(c,a,label)
   b=await c.observe(f,w);el=m.h.find(c,b,label)
   if not m.evidence(b,f.pid,w)['record_a_visible'] or f.state()['record']!='Record A' or first.get('value')!=el.get('value'):raise RuntimeError('context_changed')
   tx=uuid.uuid4().hex;delay=.04 if scenario=='stable' else .45
   if scenario=='late_reject':delay=1.4
   req={'tx':tx,'field':field,'value':value,'delay':delay,'reject':scenario in ('reject','late_reject'),'missing':scenario=='missing_ack','activate':scenario=='activation'}
   f.path.with_suffix('.txn').write_text(json.dumps(req));await asyncio.to_thread(m.h.wait_for,lambda:tx in f.state().get('transactions',{}),3)
   args={'pid':f.pid,'window_id':w,'element_token':el['element_token'],'value':value}
   if mode in ('supervision','combined'):receipt_ids.append(c.start(args))
   else:
    _,err=c.call('set_value',**args)
    if err:raise RuntimeError('action_failed')
   row['writes']+=1;txs.append((tx,field,value))
   if mode in ('evidence','combined'):await ack(f,tx,field,value,w)
   else:await asyncio.to_thread(m.h.wait_for,lambda:f.state().get(field)==value,3)
  if mode in ('supervision','combined'):row['fence']=c.fence()
  final=await c.observe(f,w);values={label:m.h.find(c,final,label).get('value') for label in ('Full name','Email')}
  if any(values[{'name':'Full name','email':'Email'}[field]]!=value for _,field,value in txs):raise RuntimeError('final_value_mismatch')
  row['decision_ms']=(time.perf_counter()-start)*1000;row['terminal']='verified_complete';row['strict_pass']=True;row['final_values']=values
 except Exception as e:row['error']=str(e);row['terminal']='handoff'
 finally:
  if mode in ('supervision','combined'):
   try:c.fence()
   except Exception as e:row['drain_error']=str(e)
  if 'watcher' in locals():stop.set();watcher.join(1);row['target_ever_active']=observed_active;row['competing_input_detected']=interfered
  row['oracle']=f.state();row['foreground_preserved']=fresh_front()==sentinel.pid and bool(sentinel.state().get('active')) and not f.state().get('active')
  f.close();m.h.HERE=saved
 return row
async def main():
 lock=open('/tmp/cua-native-completion-study.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 versions=preflight();original=fresh_front();clients={};sentinel=m.h.Fixture();out={'versions':versions,'base':'5227ad637590a15976413b1a33f8693fac0e9a7e','binary_sha256':hashlib.sha256(Path(BINARY).read_bytes()).hexdigest(),'rows':[],'servers':{}}
 try:
  for mode in ('serial','supervision','evidence','combined'):
   c=Native(mode);clients[mode]=c
   if c.backend_metadata['driver_version']!=versions['native_version']:raise RuntimeError('Actual server outdated')
   out['servers'][mode]=c.backend_metadata
  # Positive native callback/focus gate before performance trials.
  row=await trial(clients['combined'],'combined','activation',-1,sentinel);out['rows'].append(row);(OUT/'live-results.json').write_text(json.dumps(out,indent=2));print(json.dumps(row),flush=True)
  if not row['strict_pass'] or not row['foreground_preserved'] or row['oracle'].get('activation_requests')!=1:raise RuntimeError('Native focus qualification failed; stop live trials')
  for rep in range(4):
   modes=['serial','supervision','evidence','combined'];modes=modes if rep%2==0 else modes[::-1]
   for mode in modes:
    preflight();row=await trial(clients[mode],mode,'stable',rep,sentinel);row['warmup']=rep==0;out['rows'].append(row);(OUT/'live-results.json').write_text(json.dumps(out,indent=2));print(json.dumps({k:row.get(k) for k in ('mode','decision_ms','strict_pass','error','foreground_preserved')}),flush=True)
    if not row['strict_pass'] or not row['foreground_preserved'] or row.get('competing_input_detected'):raise RuntimeError('Safety/effect or competing-input failure; stop')
  for scenario in ('reject','late_reject','missing_ack'):
   for mode in ('supervision','evidence','combined'):
    row=await trial(clients[mode],mode,scenario,-1,sentinel);out['rows'].append(row);(OUT/'live-results.json').write_text(json.dumps(out,indent=2))
 finally:
  try:
   if clients:
    c=next(iter(clients.values()));c.call('bring_to_front',pid=original);out['cleanup_restored']=fresh_front()==original
  finally:
   sentinel.close()
   for c in clients.values():c.close()
   (OUT/'live-results.json').write_text(json.dumps(out,indent=2));lock.close()
if __name__=='__main__':asyncio.run(main())
