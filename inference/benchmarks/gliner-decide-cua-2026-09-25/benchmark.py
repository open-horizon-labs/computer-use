"""Live Cua Driver booking comparison. Oracle is read only after each task."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import queue
import threading
import sys
import time
import uuid
from urllib.request import urlopen
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'cua-booking-macos-2026-09-23'))
from fixture import start, GOAL
CLIENT = Path.home() / '.local/share/fleet-cua-decider'
sys.path.insert(0, str(CLIENT / 'cua/libs/cua-driver/examples/jev-use/python'))
from run import Driver, wait_for_window, select_tab_id
sys.path.insert(0, str(CLIENT))
from decision_providers import Jev, Qwen

class InstalledCascade:
    def __init__(self):
        self.process = subprocess.Popen([str(CLIENT/'select-fleet'), '--fast', 'jev'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    def select(self, state, candidates, feedback):
        self.process.stdin.write(json.dumps({**state, 'candidates': candidates, 'feedback': feedback})+'\n')
        self.process.stdin.flush()
        result = json.loads(self.process.stdout.readline())
        if result.get('action_authorized') is False or 'choice' not in result:
            raise RuntimeError('Installed selector failed')
        return result
    def close(self):
        self.process.stdin.close()
        try: self.process.wait(timeout=5)
        except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()

class RemoteGLiNER:
    def __init__(self):
        self.log=open(ROOT/'1b-remote-worker.log','w')
        self.process=subprocess.Popen(['ssh','-o','BatchMode=yes','root@192.168.1.225',
            'pct exec 210 -- env CUDA_VISIBLE_DEVICES=1 HF_HOME=/models/gliner-hf HF_HUB_DISABLE_XET=1 HF_HUB_DISABLE_PROGRESS_BARS=1 /opt/gliner-decide-bench/.venv/bin/python /opt/gliner-decide-bench/remote_selector.py fastino/GLiNER2.5-Decide-1B'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True)
        self.ready=json.loads(self.process.stdout.readline())
        if not self.ready.get('ready'):raise RuntimeError('Remote model not ready')
    def __call__(self,state,candidates):
        self.process.stdin.write(json.dumps({'state':state,'candidates':candidates})+'\n');self.process.stdin.flush()
        answer=json.loads(self.process.stdout.readline())
        if 'choice' not in answer:raise RuntimeError('Remote model failed')
        return answer
    def close(self):
        self.process.stdin.close()
        try:self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.log.close()

class RemoteWebLinxGLiNER:
    """GLiNER2.5-Decide base or trained LoRA adapter on the Columbus GPU."""
    def __init__(self, use_adapter):
        self.log=open(ROOT/'weblinx-remote-worker.log','w')
        command=['ssh','-o','BatchMode=yes','root@9950x-columbus.tail434280.ts.net',
            'pct exec 210 -- env CUDA_VISIBLE_DEVICES=1 HF_HOME=/models/gliner-hf HF_HUB_OFFLINE=1 /opt/gliner-decide-bench/.venv/bin/python /opt/gliner-decide-bench/weblinx_selector.py --model fastino/GLiNER2.5-Decide']
        if use_adapter: command[-1]+=' --adapter /tmp/gliner-weblinx-adapter'
        self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True)
        self.ready=json.loads(self.process.stdout.readline())
        if not self.ready.get('ready'):raise RuntimeError('WebLINX-format GLiNER worker failed to load')
    def __call__(self,state,candidates):
        self.process.stdin.write(json.dumps({'state':state,'candidates':candidates})+'\n');self.process.stdin.flush()
        answer=json.loads(self.process.stdout.readline())
        if 'choice' not in answer:raise RuntimeError('WebLINX-format GLiNER returned no choice')
        return answer
    def close(self):
        self.process.stdin.close()
        try:self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.log.close()

class Interactive:
    def __call__(self,state,candidates):
        print(json.dumps({'decision_request':True,'state':state,'candidates':candidates}),flush=True)
        choice=input().strip()
        return {'choice':choice,'confidence':None,'provider':'current-session'}

class AppServerLuna:
    """One ephemeral App Server thread and one schema-bound model turn per choice."""
    def __init__(self):
        self.process=subprocess.Popen(['codex','app-server','--stdio'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
        self.events=queue.Queue();self.seq=0
        self.reader=threading.Thread(target=self._read,daemon=True);self.reader.start()
        ready=self._response(self._send({'method':'initialize','params':{'clientInfo':{'name':'cua-choice-benchmark','title':'Cua choice benchmark','version':'1.0'}}}))
        if 'error' in ready:raise RuntimeError('App Server initialize failed')
        self._send({'method':'initialized'})
        listed=self._response(self._send({'method':'model/list','params':{'limit':100,'includeHidden':False}}))
        self.models=listed.get('result',{}).get('data',[])
        self.model=next((m for m in self.models if m.get('id')=='gpt-6-luna' or m.get('model')=='gpt-6-luna'),None)
        if not self.model:raise RuntimeError('App Server does not list gpt-6-luna')
        self.calls=0
    def _send(self,body):
        if body.get('method')!='initialized':
            self.seq+=1;body['id']=self.seq
        self.process.stdin.write(json.dumps(body)+'\n');self.process.stdin.flush();return body.get('id')
    def _read(self):
        for line in self.process.stdout:
            try:self.events.put(json.loads(line))
            except Exception:pass
    def _response(self,expected_id):
        while True:
            event=self.events.get(timeout=180)
            if expected_id is not None and event.get('id')==expected_id:return event
    def __call__(self,state,candidates):
        began=time.perf_counter()
        prompt={'goal':state['goal'],'observation':state['observation'],'history':state.get('history',[]),'candidates':candidates}
        started=self._response(self._send({'method':'thread/start','params':{'model':'gpt-6-luna','allowProviderModelFallback':False,'ephemeral':True,'cwd':str(Path.cwd()),'approvalPolicy':'never','sandbox':'read-only','developerInstructions':'You are a bounded action selector. Choose the single next action that best advances the user goal using only the supplied current observation and candidates. Return the exact choice ID in the required JSON schema. Never call tools or claim an action was executed.','baseInstructions':'You select an action only. Do not use tools. Do not explain. Return only the required structured output.'}}))
        if 'error' in started:raise RuntimeError('App Server thread/start failed: '+str(started['error'].get('code')))
        thread=started.get('result',{}).get('thread',{}).get('id')
        if not thread:raise RuntimeError('App Server omitted thread ID')
        schema={'type':'object','properties':{'choice':{'type':'string','enum':list(candidates)}},'required':['choice'],'additionalProperties':False}
        turn_sent=time.perf_counter()
        turn_response=self._response(self._send({'method':'turn/start','params':{'threadId':thread,'model':'gpt-6-luna','effort':'low','summary':'none','input':[{'type':'text','text':json.dumps(prompt)}],'outputSchema':schema}}))
        if 'error' in turn_response:raise RuntimeError('App Server turn/start failed: '+str(turn_response['error'].get('code')))
        turn_id=turn_response.get('result',{}).get('turn',{}).get('id')
        final_text=None;completed=None
        while True:
            event=self.events.get(timeout=180)
            if event.get('method')=='item/completed' and event.get('params',{}).get('threadId')==thread:
                item=event['params'].get('item',{})
                if item.get('type')=='agentMessage':final_text=item.get('text')
            if event.get('method')=='turn/completed' and event.get('params',{}).get('threadId')==thread:
                completed=event['params'].get('turn',{});break
        if completed and completed.get('status')!='completed':raise RuntimeError('App Server turn ended '+str(completed.get('status')))
        try:answer=json.loads(final_text or '')
        except Exception:raise RuntimeError('App Server returned no structured choice') from None
        if answer.get('choice') not in candidates:raise RuntimeError('App Server returned an unknown choice ID')
        self.calls+=1
        return {'choice':answer['choice'],'confidence':None,'provider':'codex-app-server','model':'gpt-6-luna','turn_ms':(time.perf_counter()-turn_sent)*1000,'selection_ms':(time.perf_counter()-began)*1000,'turn_id':turn_id}
    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()

async def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--provider', choices=['340m','1b','jev','qwen','jev-qwen','1b-remote','340m-weblinx-remote','340m-weblinx-adapter-remote','interactive','app-server-luna'], required=True)
    ap.add_argument('--device',default='mps')
    ap.add_argument('--count',type=int,default=20)
    ap.add_argument('--start',type=int,default=0)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    os.environ.setdefault('TYPESAFE_CONNECT_SSH','homelab-personal-assembler')
    os.environ.setdefault('QWEN_SECRET_SSH','homelab-personal-stock')
    metadata={'provider':args.provider,'device':args.device,'count':args.count,'start':args.start}
    if args.provider == 'interactive':
        provider=Interactive()
        metadata.update(model_label='Luna Light (user-reported current session)', timing='Includes assistant/tool orchestration; not direct inference latency')
    elif args.provider == 'app-server-luna':
        provider=AppServerLuna()
        metadata['app_server_model']={k:provider.model.get(k) for k in ('id','slug','displayName','supportedReasoningEfforts')}
        metadata.pop('device',None)
        metadata['app_server_cli_version']=subprocess.run(['codex','--version'],capture_output=True,text=True,timeout=10).stdout.strip()
        metadata['timing']='Per-call turn_ms includes App Server and model service; selection_ms also includes ephemeral thread creation.'
    elif args.provider == '1b-remote':
        provider=RemoteGLiNER()
        metadata['remote']=provider.ready
    elif args.provider in ('340m-weblinx-remote','340m-weblinx-adapter-remote'):
        provider=RemoteWebLinxGLiNER(args.provider.endswith('adapter-remote'))
        metadata.pop('device',None)
        metadata.update(remote=provider.ready,device='cuda:3060ti',model_revision='7ee5da4c2415e32259bcdc0b1a7367c32ce8d6f6',input_format='weblinx-option-labels',adapter=bool(args.provider.endswith('adapter-remote')))
        if args.provider.endswith('adapter-remote'):
            metadata.update(adapter_sha256='4c0457ab0ed36bf763bfa00af5e48019b02ce1c8aae3df87a0fa3a4a561727ca',training_run='GLiNER2.5-Decide-WebLINX-v1-20260926')
    elif args.provider in ('340m','1b'):
        from gliner_provider import GLiNER
        provider=GLiNER('fastino/GLiNER2.5-Decide'+('-1B' if args.provider=='1b' else ''),args.device)
        metadata['load_seconds']=provider.load_seconds
        # Identical unscored warmup, unrelated to the booking scenarios.
        provider({'goal':'Click Save.','observation':'Buttons: Save, Cancel.'},{'save':'Click Save','cancel':'Click Cancel','reobserve':'Observe again','abstain':'Stop'})
    else: provider=Jev() if args.provider=='jev' else Qwen()
    server=start();results=[];label='gliner-bench-'+uuid.uuid4().hex[:8]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    async with stdio_client(StdioServerParameters(command=str(Path.home()/'.local/bin/cua-driver'),args=['mcp'])) as (read,write):
      async with ClientSession(read,write) as session:
        await session.initialize();d=Driver(session,label)
        p=await d.call('browser_prepare',{'allow_launch':True,'profile':{'mode':'isolated_new'}})
        pid=p['prepared_pid'];w=await wait_for_window(d,pid)
        b=await d.call('get_browser_state',{'pid':pid,'window_id':w['window_id']})
        target={'target_id':b['target_id'],'tab_id':select_tab_id(b['tabs'])}
        try:
          for seed in range(args.start,args.start+args.count):
            router=InstalledCascade() if args.provider=='jev-qwen' else None
            url=f'http://127.0.0.1:{server.server_port}/{label}-{seed}?seed={seed}'
            await d.call('browser_navigate',{**target,'url':url});await asyncio.sleep(.3)
            began=time.perf_counter();steps=[];history=[];error=None;previous=None;previous_choice=None
            try:
              for turn in range(6):
                t=time.perf_counter()
                snap=await d.call('get_browser_state',{**target,'snapshot_format':'semantic_v2'})
                visible=snap.get('outline',snap.get('tree',snap.get('text','')))
                if not visible:visible=[{k:v for k,v in r.items() if k in ('name','role','value')} for r in snap.get('refs',[])]
                observation_ms=(time.perf_counter()-t)*1000
                if 'Task complete' in json.dumps(visible):break
                buttons=[(r.get('name',''),{'ref':r['ref']}) for r in snap.get('refs',[]) if r.get('role')=='button']
                if not buttons:raise RuntimeError('No buttons extracted')
                candidates={f'a{i}':f'Click {name}' for i,(name,_) in enumerate(buttons)}
                candidates.update(reobserve='Observe the page again without acting',abstain='Stop because no safe action can accomplish the goal')
                state={'goal':GOAL,'observation':visible,'history':history.copy()}
                # UI evidence only: confirmation proves stage progress; a lost slot is a failed attempt.
                serialized=json.dumps(visible)
                feedback=None
                if previous is not None:
                    feedback='verified_progress' if previous!=serialized and 'Confirm booking' in serialized and previous_choice not in ('reobserve','abstain') else 'no_progress'
                t=time.perf_counter()
                answer=await asyncio.to_thread(router.select,state,candidates,feedback) if router else await asyncio.to_thread(provider,state,candidates)
                selected=answer['choice'];decision_ms=(time.perf_counter()-t)*1000
                if selected not in candidates:raise RuntimeError('Invalid choice')
                step={'state':state,'candidates':candidates,'choice':selected,'description':candidates[selected],'model':answer,'feedback':feedback,'decision_ms':decision_ms,'observation_ms':observation_ms}
                steps.append(step)
                if selected=='abstain':break
                t=time.perf_counter()
                if selected!='reobserve':await d.call('browser_click',{**target,**buttons[int(selected[1:])][1],'input_route':'dom_event'})
                step['action_ms']=(time.perf_counter()-t)*1000
                previous=serialized;previous_choice=selected;history.append({'action':candidates[selected]})
              with urlopen(url.split('?')[0]+'/oracle') as response:oracle=json.load(response)
            except Exception as exc:
              error=type(exc).__name__;oracle={'correct':False}
            finally:
              if router:router.close()
            result={'seed':seed,'elapsed_ms':(time.perf_counter()-began)*1000,'steps':steps,'oracle':oracle,'error':error}
            results.append(result)
            args.output.write_text(json.dumps({'metadata':metadata,'results':results},indent=2)+'\n')
            print(json.dumps({k:result[k] for k in ('seed','elapsed_ms','oracle','error')}),flush=True)
        finally:
            await d.call('end_session',{});server.shutdown()
            if hasattr(provider,'close'):provider.close()

if __name__=='__main__':asyncio.run(main())
