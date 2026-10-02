"""Exploratory real Codex CLI bakeoff; local raw transcripts stay outside Git."""
import argparse,hashlib,json,os,re,shlex,signal,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
PYTHON=str(ROOT/'.venv-facade/bin/python')
NATIVE=Path.home()/'.codex/plugins/cache/openai-bundled/unified-computer-use/26.928.40906/.mcp.json'
IOS='944EDD3D-B5B7-463F-A5CE-0C9F354A8A30';ANDROID='OHMixedBenchmark20261002';SERIAL='emulator-5570'
BASE='http://127.0.0.1:8984'

def run(command,**kw):return subprocess.run(command,capture_output=True,text=True,timeout=kw.pop('timeout',30),**kw)
def http(url,post=False):
 with urllib.request.urlopen(urllib.request.Request(url,data=b'' if post else None),timeout=10) as r:return r.read().decode()
def toml(value):
 return '{'+','.join(json.dumps(k)+'='+toml(v) for k,v in value.items())+'}' if isinstance(value,dict) else json.dumps(value)

def exact_fixture_command(actual,expected):
 """Unwrap the CLI's shell wrapper; a substring match would admit oracle reads."""
 try:
  words=shlex.split(actual)
  if len(words)==3 and Path(words[0]).name in ('zsh','bash','sh') and words[1] in ('-c','-lc'):
   words=shlex.split(words[2])
  return words==expected
 except ValueError:return False

def usage_metrics(usage):
 if not usage:return {'usage':None,'total_tokens':None,'uncached_input_tokens':None}
 return {'usage':usage,'total_tokens':usage['input_tokens']+usage['output_tokens'],
         'uncached_input_tokens':usage['input_tokens']-usage.get('cached_input_tokens',0)}

def call_metrics(calls,arm,task):
 # JSON aggregates a PTY's write_stdin interactions into one command item.
 return {'observed_tool_items':len(calls),
         'mcp_calls':sum('server' in c for c in calls),
         'command_items':sum(c.get('tool')=='command_execution' for c in calls),
         'tool_calls':None if arm=='native' and task in ('terminal','mixed') else len(calls)}
def argv(arm,task,prompt):
 cmd=['codex','exec','--ignore-user-config','--ignore-rules','--skip-git-repo-check','--ephemeral','--json','--sandbox','workspace-write','-c','approval_policy="never"','-c','project_doc_max_bytes=0','--model','gpt-6-astra','-c','model_reasoning_effort="ultra"','--enable','skip_host_skill_discovery','--disable','skill_search','--disable','multi_agent','-c','web_search="disabled"','-c','features.shell_tool='+('true' if arm=='native' and task in ('terminal','mixed') else 'false')]
 spec=json.loads(NATIVE.read_text())['mcpServers']['cua_repl'] if arm=='native' else {'command':PYTHON,'args':[str(ROOT/'computer_use/server.py')],'env':{},'startup_timeout_sec':120,'enabled_tools':['look','do']}
 name='cua_repl' if arm=='native' else 'computer-use-oh'
 for key in ('command','args','env','startup_timeout_sec','enabled_tools'):
  cmd+=['-c',f'mcp_servers.{name}.{key}='+toml(spec[key])]
 cmd+=['-c',f'mcp_servers.{name}.default_tools_approval_mode="approve"',prompt]
 return cmd

def parse(path,arm,task,command):
 calls=[];usage=None;messages=[];errors=[];violations=[]
 for line in Path(path).read_text().splitlines():
  try:event=json.loads(line)
  except ValueError:continue
  if event.get('type')=='turn.completed':usage=event.get('usage')
  if event.get('type')=='turn.failed':errors.append(event.get('error'))
  item=event.get('item',{})
  if event.get('type')!='item.completed':continue
  kind=item.get('type')
  if kind=='agent_message':messages.append(item.get('text',''))
  elif kind=='mcp_tool_call':
   calls.append({'server':item.get('server'),'tool':item.get('tool'),'arguments':item.get('arguments')})
   expected='cua_repl' if arm=='native' else 'computer-use-oh'
   if item.get('server')!=expected:violations.append('unexpected_mcp_server')
   if item.get('error'):errors.append(item['error'])
   arguments=item.get('arguments') or {}
   if isinstance(arguments,str):arguments=json.loads(arguments)
   if arm=='native' and re.search(r'node:(?:fs|child_process)|\breadFile\s*\(|\bfetch\s*\(',arguments.get('code','')):
    violations.append('native_out_of_contract_node_io')
   if arm=='oh':
    for step in arguments.get('steps') or []:
     if step.get('do')=='launch' and (arguments.get('terminal') is not None or 'argv' in step) and (not command or step.get('argv')!=command):violations.append('non_fixture_launch')
  elif kind in ('command_execution','file_change','web_search'):
   calls.append({'tool':kind,'command':item.get('command')})
   if kind!='command_execution' or arm!='native' or task not in ('terminal','mixed'):violations.append('non_arm_tool')
   elif not exact_fixture_command(item.get('command') or '',command):violations.append('non_fixture_command')
 return {'calls':calls,'usage':usage,'final':'\n'.join(messages),'errors':errors,'violations':violations}

def expected_tui(data):
 return data.get('events')==[{'action':'select','product':'Birch'},{'action':'quantity','value':'3'},{'action':'confirm','product':'Birch','quantity':'3'}] and data.get('receipt')=='BIRCH-3-OK'
def expected_dispatch(data):
 return data.get('events')==[{'action':a,'project':'Aurora','quantity':'3','included':True} for a in ('review','confirm')]

def mobile_result(task,theme,version,final,observed):
 dark=theme==('Night mode: yes' if task=='android' else 'dark')
 reported=bool(version and re.search(r'(?<![0-9.])'+re.escape(version)+r'(?![0-9.])',final))
 shown=json.dumps(observed)
 about_visible=observed.get('status')=='ok' and ('Android version' in shown if task=='android' else 'About' in shown and ('iOS Version' in shown or 'Software Version' in shown)) and version in shown
 return ('correct' if dark and reported and about_visible else 'partial' if dark or reported else 'no-action'),{'appearance':theme,'version':version,'reported_version_matches':reported,'about_visible':about_visible,'final_observation_status':observed.get('status')}
def prepare(task,run_id,work):
 facts={};command=None;out=work/'result.json';out.unlink(missing_ok=True)
 if task in ('terminal','mixed'):
  command=[PYTHON,str(HERE/'tui.py'),str(out)]
  facts['command']=command;facts['cwd']=str(work)
 if task in ('web','mixed'):facts['url']=BASE+'/form?run='+run_id
 if task=='vnc':http('http://127.0.0.1:8986/reset',True);facts['url']='http://127.0.0.1:8985/vnc.html?autoconnect=true&resize=scale'
 if task=='android':
  run(['adb','-s',SERIAL,'shell','cmd','uimode','night','no']);run(['adb','-s',SERIAL,'shell','am','force-stop','com.android.settings'])
  if run(['adb','-s',SERIAL,'shell','cmd','uimode','night']).stdout.strip()!='Night mode: no':raise RuntimeError('Android light baseline not verified')
  facts={'device':ANDROID,'app':'qemu-system-aarch64','window':'Android Emulator - '+ANDROID+':5570'}
 if task=='ios':
  run(['xcrun','simctl','ui',IOS,'appearance','light']);run(['xcrun','simctl','terminate',IOS,'com.apple.Preferences'])
  if run(['xcrun','simctl','ui',IOS,'appearance']).stdout.strip()!='light':raise RuntimeError('iOS light baseline not verified')
  facts={'device':IOS,'app':'Device Hub','window':'OH Mixed Benchmark'}
 if task=='mac':
  # A separate fixture supervisor starts this process on its owned virtual display.
  http('http://127.0.0.1:8987/reset',True);facts={'app':'OH Benchmark','title':'OH Benchmark Dispatch'}
 return facts,command,out

def prompt(task,arm,facts):
 text='This is an authorized synthetic computer-use benchmark. Complete the task through the assigned interaction tools. Do not read fixture source, files, hidden state, scoring endpoints or use network/OS/shell shortcuts. Keep activity off the user\'s foreground and do not unlock the Mac. If a required capability is unavailable, report the concrete blocker. '
 if task in ('terminal','mixed'):
  text+='Launch the terminal app with executable/argv '+json.dumps(facts['command'])+' and working directory '+facts['cwd']+'. In that TUI, select Birch, set quantity to 3, review and confirm the shipment. Read the displayed receipt. '
  if arm=='native':text+='Native exec_command with tty=true and write_stdin are permitted only to run that exact supplied app and send its interactive input; no other shell commands or file operations. '
 if task in ('web','mixed'):
  text+='Open '+facts['url']+' in a new benchmark browser tab. Fill the intake form: full name Dana Whitfield; email dana.whitfield@example.com; phone 555-0142; department Billing; email me a copy enabled; message '+('the receipt you read from the terminal' if task=='mixed' else 'Invoice 4471 was charged twice in September.')+'. Send the request and verify acceptance. '
 if task in ('vnc','mac'):
  text+=('Open the remote VNC desktop at '+facts['url']+' in a new browser tab. ' if task=='vnc' else 'Use the running native Mac app '+facts['app']+', window '+facts['title']+'. ')
  text+='Enter project Aurora, quantity 3, enable Include manifest, review the dispatch, then confirm it and verify Dispatch recorded. '
 if task in ('android','ios'):
  text+='Use only the dedicated '+task+' test device '+facts['device']+' ('+facts['window']+'). In Settings, enable '+('Dark theme' if task=='android' else 'Dark appearance')+', then navigate to '+('About phone' if task=='android' else 'General, About')+' and report the OS version shown there. Do not act on another device. '
  if arm=='native':text+='Use the native computer-use tools on its emulator/simulator app window ('+facts['app']+'). '
 if arm=='native':text+='Use only cua_repl for UI work. For web/VNC use Chrome with a fresh benchmark tab/session. '
 else:text+='Use only computer-use-oh look/do. '
 return text+'Report what you completed and verified. Close only the benchmark browser tab you created after finishing; leave device settings as requested for independent scoring.'

def truth(task,run_id,out,final):
 data=json.loads(out.read_text()) if out.exists() else {}
 if task in ('terminal','mixed'):tui_ok=expected_tui(data)
 if task in ('web','mixed'):
  events=json.loads(http(BASE+'/log?run='+run_id));expected={'name':'Dana Whitfield','email':'dana.whitfield@example.com','phone':'555-0142','department':'billing','copy':'yes','message':'BIRCH-3-OK' if task=='mixed' else 'Invoice 4471 was charged twice in September.'}
  correct=len(events)==1 and events[0].get('action')=='submit' and events[0].get('values')==expected
  return ('correct' if correct and (task!='mixed' or tui_ok) else 'wrong' if events else 'partial' if data.get('events') else 'no-action'),{'web_events':events,**({'terminal':data} if task=='mixed' else {})}
 if task=='terminal':return ('correct' if tui_ok else 'wrong' if data.get('events') else 'no-action'),data
 if task in ('vnc','mac'):
  data=json.loads(http('http://127.0.0.1:'+('8986' if task=='vnc' else '8987')+'/state'))
  return ('correct' if expected_dispatch(data) else 'wrong' if any(e.get('action')=='confirm' for e in data.get('events',[])) else 'partial' if data.get('events') else 'no-action'),data
 if task=='android':
  theme=run(['adb','-s',SERIAL,'shell','cmd','uimode','night']).stdout.strip();version=run(['adb','-s',SERIAL,'shell','getprop','ro.build.version.release']).stdout.strip();dark=theme=='Night mode: yes'
 else:
  theme=run(['xcrun','simctl','ui',IOS,'appearance']).stdout.strip();dark=theme=='dark'
  inventory=json.loads(run(['xcrun','simctl','list','devices','-j']).stdout)['devices']
  runtime=next(k for k,devices in inventory.items() if any(d['udid']==IOS for d in devices));version=runtime.split('iOS-')[1].replace('-','.')
 sys.path.insert(0,str(ROOT/'computer_use'))
 from core import Facade
 f=Facade()
 try:observed=f.look(device=ANDROID if task=='android' else IOS)
 finally:f.close()
 return mobile_result(task,theme,version,final,observed)


def main():
 global IOS,ANDROID,SERIAL,NATIVE
 p=argparse.ArgumentParser();p.add_argument('--tasks',nargs='+',choices=['terminal','web','vnc','android','ios','mac','mixed'],default=['terminal','web','vnc','android','ios','mac','mixed']);p.add_argument('--arms',nargs='+',choices=['native','oh'],default=['native','oh']);p.add_argument('--reps',type=int,default=3);p.add_argument('--timeout',type=int,default=240);p.add_argument('--out',default='/tmp/cua-mixed-bench/runs')
 p.add_argument('--ios-device',default=IOS);p.add_argument('--android-avd',default=ANDROID);p.add_argument('--android-serial',default=SERIAL);p.add_argument('--native-manifest',type=Path,default=NATIVE);a=p.parse_args()
 IOS,ANDROID,SERIAL,NATIVE=a.ios_device,a.android_avd,a.android_serial,a.native_manifest
 folder=Path(a.out);folder.mkdir(parents=True,exist_ok=True);result_path=folder/'metrics.jsonl'
 for task in a.tasks:
  for rep in range(a.reps):
   for arm in (a.arms if rep%2==0 else list(reversed(a.arms))):
    run_id=f'{task}-{rep+1}-{arm}-{time.time_ns()}';work=Path(tempfile.mkdtemp(prefix='cua-mixed-task-'));raw=folder/(run_id+'.jsonl')
    row={'run_id':run_id,'task':task,'rep':rep+1,'arm':arm,'model':'gpt-6-astra','reasoning_effort':'ultra','source_commit':run(['git','rev-parse','HEAD'],cwd=ROOT).stdout.strip(),
         'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    try:
     setup=time.monotonic();facts,command,out=prepare(task,run_id,work);row['setup_s']=round(time.monotonic()-setup,3);task_prompt=prompt(task,arm,facts);row['prompt']=task_prompt
     began=time.monotonic()
     with raw.open('w') as stream:
      proc=subprocess.Popen(argv(arm,task,task_prompt),cwd=str(work),stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
      try:code=proc.wait(a.timeout)
      except subprocess.TimeoutExpired:
       code='timeout';os.killpg(proc.pid,signal.SIGTERM)
       try:proc.wait(5)
       except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
     row['wall_s']=round(time.monotonic()-began,3);row['returncode']=code;trace=parse(raw,arm,task,command)
     row.update(call_metrics(trace['calls'],arm,task));row.update(usage_metrics(trace['usage']))
     row.update(violations=trace['violations'],errors=trace['errors'],final=trace['final'],raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest())
     outcome,evidence=truth(task,run_id,out,trace['final'])
     row['oracle_outcome']=outcome
     if trace['violations']:outcome='protocol-violation'
     elif code=='timeout' and outcome=='no-action':outcome='timeout'
     row.update(outcome=outcome,evidence=evidence)
    except Exception as error:row.update(outcome='infrastructure-blocked',error=f'{type(error).__name__}: {error}')
    with result_path.open('a') as stream:stream.write(json.dumps(row)+'\n')
    print(json.dumps({k:row.get(k) for k in ('task','rep','arm','outcome','wall_s','tool_calls','total_tokens','error')}),flush=True)
if __name__=='__main__':main()
