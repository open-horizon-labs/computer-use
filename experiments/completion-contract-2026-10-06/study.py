"""Offline independent application fixture; no driver, GUI, input or secrets."""
import asyncio,json,time,uuid
from multiprocessing import Process,Pipe
from pathlib import Path

# Separate process owns values and final commit/reject acknowledgement.
def app(conn):
    import time
    state={'record':'A','values':{},'generation':0};pending=[];acks={};fault=None
    while True:
        now=time.monotonic()
        for item in pending[:]:
            due,tx,key,value,reject=item
            if now>=due:
                state['values'][key]='REJECTED' if reject else value
                acks[tx]={'tx':tx,'record':state['record'],'generation':state['generation'],'outcome':'rejected' if reject else 'committed','key':key,'value':state['values'][key]}
                if fault:acks[tx][fault]=-1 if fault=='generation' else '__wrong__'
                pending.remove(item)
        if not conn.poll(.001):continue
        req=conn.recv();op=req['op']
        if op=='close':conn.send(True);return
        if op=='fault':fault=req['field'];conn.send(True);continue
        if op=='observe':conn.send({**state,'values':dict(state['values']),'acks':dict(acks)});continue
        if op=='record':state['record']='B';state['generation']+=1;conn.send(True);continue
        if op=='write':
            if req['record']!=state['record'] or req['generation']!=state['generation']:
                conn.send({'refusal':'context_changed'});continue
            state['values'][req['key']]=req['value'] # Deliberately optimistic echo.
            pending.append((time.monotonic()+req['delay'],req['tx'],req['key'],req['value'],req['reject']))
            conn.send({'dispatch':'accepted','tx':req['tx']});continue

class Fixture:
    def __init__(self):
        self.conn,child=Pipe();self.proc=Process(target=app,args=(child,));self.proc.start();self.writes=0;self.lock=asyncio.Lock()
    async def call(self,**req):
        async with self.lock:
            self.conn.send(req);return await asyncio.to_thread(self.conn.recv)
    async def close(self):
        await self.call(op='close');await asyncio.to_thread(self.proc.join,2)
        if self.proc.is_alive():self.proc.terminate();self.proc.join()
        self.conn.close()

class Handoff(Exception):pass
class Supervisor:
    def __init__(self,f,horizon=.10,mutant=None):self.f=f;self.horizon=horizon;self.tasks={};self.mutant=mutant;self.enabled=True
    async def watch(self,tx,key,value,record,generation):
        end=time.monotonic()+self.horizon
        while time.monotonic()<end:
            s=await self.f.call(op='observe')
            if s['record']!=record or s['generation']!=generation:raise Handoff('context_changed')
            ack=s['acks'].get(tx)
            if ack and ack['outcome']=='rejected':raise Handoff('rejected')
            await asyncio.sleep(.003)
        s=await self.f.call(op='observe')
        if s['record']!=record or s['generation']!=generation:raise Handoff('context_changed')
        if s['values'].get(key)!=value:raise Handoff('final_value_mismatch')
        return 'horizon_observed' # Never a promise no later effects exist.
    async def dispatch(self,key,value,delay,reject=False):
        s=await self.f.call(op='observe')
        if s['record']!='A':raise Handoff('context_changed')
        tx=uuid.uuid4().hex
        r=await self.f.call(op='write',key=key,value=value,delay=delay,reject=reject,tx=tx,record=s['record'],generation=s['generation'])
        if r.get('refusal'):raise Handoff(r['refusal'])
        self.f.writes+=1
        if self.enabled:self.tasks[tx]=asyncio.create_task(self.watch(tx,key,value,s['record'],s['generation']))
        return tx
    async def fence(self):
        if self.mutant=='skip_fence':return
        group=asyncio.gather(*self.tasks.values(),return_exceptions=True)
        results=await group if self.mutant=='cancel_watchers' else await asyncio.shield(group)
        for r in results:
            if isinstance(r,Exception):raise r
    async def drain(self):await asyncio.gather(*self.tasks.values(),return_exceptions=True)

async def committed(f,tx,key,value,timeout=.3,mutant=None):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        s=await f.call(op='observe')
        if s['record']!='A':raise Handoff('context_changed')
        if mutant=='trust_echo' and s['values'].get(key)==value:return
        a=s['acks'].get(tx)
        if a:
            if a['tx']!=tx or a['record']!='A' or a['generation']!=s['generation'] or a['key']!=key:raise Handoff('ack_binding')
            if a['outcome']!='committed':raise Handoff('rejected')
            if a['value']!=value or s['values'].get(key)!=value:raise Handoff('final_value_mismatch')
            return
        await asyncio.sleep(.003)
    raise Handoff('ack_unavailable')

async def trial(mode,scenario='stable',mutant=None):
    f=Fixture();sup=Supervisor(f,mutant=mutant);sup.enabled=mode!='evidence';start=time.monotonic();row={'mode':mode,'scenario':scenario};expected='complete'
    try:
        if scenario.startswith('ack_fault_'):await f.call(op='fault',field=scenario.removeprefix('ack_fault_'))
        delay=.025 if scenario=='stable' else .045
        if scenario=='late_reject':delay=.14
        if scenario=='missing_ack':delay=10
        reject=scenario in ('reject','late_reject','partial_failure','dependent')
        tx=await sup.dispatch('name','Alice',delay,reject)
        if scenario=='record_change':await f.call(op='record');expected='context_changed'
        if scenario=='dependent':
            # First value rejects; no dependent write may run before its proof.
            await committed(f,tx,'name','Alice',mutant=mutant)
            await sup.fence()
            await sup.dispatch('dependent','Submit',.01)
        elif scenario=='cancel':
            waiter=asyncio.create_task(sup.fence());await asyncio.sleep(.01);waiter.cancel()
            try:await waiter
            except asyncio.CancelledError:pass
            # Shielding at the caller boundary must preserve supervisor tasks.
            row['supervisor_alive']=all(not t.cancelled() for t in sup.tasks.values())
            if not row['supervisor_alive']:raise Handoff('supervision_cancelled')
            await sup.fence()
        elif scenario=='stable':
            if mode=='serial':await sup.fence()
            tx2=await sup.dispatch('email','a@example.test',delay)
            if mode in ('evidence','combined'):
                await committed(f,tx,'name','Alice',mutant=mutant)
                await committed(f,tx2,'email','a@example.test',mutant=mutant)
        elif scenario=='partial_failure':
            tx2=await sup.dispatch('email','a@example.test',.01)
            if mode in ('evidence','combined'):
                await committed(f,tx,'name','Alice',mutant=mutant)
                await committed(f,tx2,'email','a@example.test',mutant=mutant)
        elif mode in ('evidence','combined'):await committed(f,tx,'name','Alice',mutant=mutant)
        if mode in ('serial','supervision','combined'):await sup.fence()
        state=await f.call(op='observe')
        if scenario=='stable' and state['values']!={'name':'Alice','email':'a@example.test'}:raise Handoff('final_value_mismatch')
        row['terminal']='complete'
    except Handoff as e:row['terminal']=str(e)
    finally:
        row['decision_ms']=(time.monotonic()-start)*1000
        await sup.drain();row['elapsed_ms']=(time.monotonic()-start)*1000;row['writes']=f.writes;row['state']=await f.call(op='observe');await f.close()
    return row

async def main():
    # Fix cancellation ownership: cancelling a fence must not cancel supervisors.
    out=[]
    for scenario in ('stable','reject','late_reject','record_change','dependent','partial_failure','missing_ack','cancel'):
        for mode in ('serial','supervision','evidence','combined'):
            out.append(await trial(mode,scenario))
    Path(__file__).with_name('results.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
if __name__=='__main__':asyncio.run(main())
