"""Controlled real-renderer experiment, NOT a virtual-display or agent benchmark.

SpaceO arm calls its actual ChromiumBridge through an opt-in XCTest. OH arm calls
unchanged Facade selection/revalidation with a research CDP-backed observation/
input adapter, NOT the stock Cua Driver. Both use the same Chrome binary, viewport,
loopback fixture and independently collected server events. Initial selections are
scripted, so no model accuracy or agent-visible call advantage is inferred.
"""
import base64,glob,json,os,select,subprocess,sys,tempfile,threading,time,urllib.request
from pathlib import Path
from renderer_fixture import make_server,CASES,MUTATIONS
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'computer_use'))
from core import Facade,Gap
from agent_display import AgentDisplay

class CDP:
 def __init__(self,url):
  self.proc=subprocess.Popen(['node',str(Path(__file__).with_name('cdp_transport.mjs')),url],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1);self.seq=0
 def call(self,method,params=None):
  self.seq+=1;self.proc.stdin.write(json.dumps({'id':self.seq,'method':method,'params':params or {}})+'\n');self.proc.stdin.flush()
  ready,_,_=select.select([self.proc.stdout],[],[],15)
  if not ready:raise RuntimeError('CDP deadline')
  row=json.loads(self.proc.stdout.readline())
  if row.get('id')!=self.seq or 'error' in row:raise RuntimeError('CDP transport refusal')
  return row['result']
 def evaluate(self,expression):
  value=self.call('Runtime.evaluate',{'expression':expression,'returnByValue':True})
  if value.get('exceptionDetails'):raise RuntimeError('fixture evaluation failed')
  return value.get('result',{}).get('value')
 def navigate(self,url):
  self.call('Page.navigate',{'url':url})
  until=time.monotonic()+10
  while time.monotonic()<until:
   if self.evaluate('location.href')==url and self.evaluate('document.readyState')=='complete':return
   time.sleep(.02)
  raise RuntimeError('fixture did not load')
 def close(self):
  self.proc.stdin.close()
  try:self.proc.wait(timeout=3)
  except subprocess.TimeoutExpired:self.proc.terminate();self.proc.wait(timeout=3)

OBSERVE=r'''(() => {
 const nodes=[{element_index:0,role:'AXWebArea',label:document.title,actions:[]}];
 function visit(parent,index){for(const el of parent.children){
  if(['SCRIPT','STYLE','META','TITLE'].includes(el.tagName))continue;
  let rect=el.getBoundingClientRect();if(rect.width<2||rect.height<2)continue;
  let control=['BUTTON','INPUT','TEXTAREA'].includes(el.tagName);
  let label=control?(el.getAttribute('aria-label')||el.innerText||''):Array.from(el.childNodes).filter(n=>n.nodeType===3).map(n=>n.textContent).join(' ').trim();
  const id=nodes.length;nodes.push({element_index:id,parent_index:index,role:el.tagName==='BUTTON'?'AXButton':el.tagName==='INPUT'?'AXTextField':el.tagName==='TEXTAREA'?'AXTextArea':'AXGroup',label,value:['INPUT','TEXTAREA'].includes(el.tagName)?el.value:'',actions:control?['AXPress']:[],enabled:!el.disabled,_fixture_id:el.id||null});visit(el,id);
 }}visit(document.body,0);return {title:document.title,url:location.href,nodes};})()'''
class RendererDriver:
 def __init__(self,cdp):self.cdp=cdp;self.seq=0;self.bindings={};self.calls=0
 def call(self,tool,args,timeout=20):
  self.calls+=1
  if tool=='list_windows':return {'windows':[{'pid':1,'window_id':2,'title':'Controlled renderer trial','app_name':'Renderer research adapter'}]}
  if tool in ('start_session','end_session'):return {}
  if tool=='get_browser_state':return {}
  if tool in ('click','type_text'):
   token=args['element_token'];ident=self.bindings.get(token)
   if not ident:raise Gap('research binding missing')
   point=self.cdp.evaluate("(()=>{const el=document.getElementById("+json.dumps(ident)+");if(!el||el.disabled)return null;const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
   if not point:raise Gap('research target absent or disabled')
   self.cdp.call('Input.dispatchMouseEvent',{'type':'mousePressed','button':'left','clickCount':1,**point})
   self.cdp.call('Input.dispatchMouseEvent',{'type':'mouseReleased','button':'left','clickCount':1,**point})
   if tool=='type_text':self.cdp.call('Input.insertText',{'text':args['text']})
   return {'effect':'unverifiable'}
  raise Gap('unsupported research transport tool '+tool)
 def observe(self,*args):
  self.calls+=1;data=self.cdp.evaluate(OBSERVE);self.seq+=1;sid='renderer'+str(self.seq);self.bindings={}
  for n in data['nodes']:
   n['element_token']=sid+':'+str(n['element_index'])
   if n.get('_fixture_id'):self.bindings[n['element_token']]=n['_fixture_id']
  return {'snapshot_id':sid,'pid':1,'window_id':2,'window_title':data['title'],'elements':data['nodes'],'_image':b'','_research_document_url':data['url']}

def event_score(case,events):
 if any(r['meaning']=='decoy' for r in events):return 'wrong_effect'
 if case=='form':return 'correct' if len(events)==1 and events[0]['meaning']=='submit' and events[0]['values']=={'name':'Ada Lovelace','note':'Synthetic intake'} else 'no_effect'
 if case in ('static','duplicate_context'):return 'correct' if len(events)==1 and events[0]['meaning']=='target' else 'no_effect'
 return 'safe_no_effect' if not events else 'stale_effect'

def main():
 os.umask(0o077)
 out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
 spaceo=Path('/tmp/spaceo-trial-a858236')
 events=[];server=make_server(events);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 base='http://127.0.0.1:'+str(server.server_port)
 chrome=glob.glob(str(Path.home()/'.cache/computer-use/browsers/chrome/*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'))[-1]
 profile=Path(tempfile.mkdtemp(prefix='spaceo-oh-renderer-'))
 log=(out/'chrome.log').open('w')
 proc=subprocess.Popen([chrome,'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-default-apps','--remote-debugging-port=0','--user-data-dir='+str(profile),'--window-size=1280,800','about:blank'],stdout=log,stderr=log,start_new_session=True)
 cdp=None
 try:
  deadline=time.monotonic()+15
  while not (profile/'DevToolsActivePort').exists() and time.monotonic()<deadline:time.sleep(.05)
  port=int((profile/'DevToolsActivePort').read_text().splitlines()[0]);targets=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list',timeout=3));target=next(t for t in targets if t['type']=='page')
  cdp=CDP(target['webSocketDebuggerUrl'])
  cdp.call('Emulation.setDeviceMetricsOverride',{'width':1280,'height':800,'deviceScaleFactor':1,'mobile':False})
  cases=[{'name':case,'run':f'spaceo-{repeat}-{case}','url':base+'/?case='+case+'&run='+f'spaceo-{repeat}-{case}','mutation':MUTATIONS.get(case),'index':1 if case=='duplicate_context' else 0} for repeat in range(3) for case in CASES]
  source=out/'cases.json';source.write_text(json.dumps(cases))
  result=out/'spaceo-renderer.json';env=dict(os.environ,SPACEO_BROWSER_RESEARCH='1',SPACEO_BROWSER_RESEARCH_PORT=str(port),SPACEO_BROWSER_RESEARCH_CASES=str(source),SPACEO_BROWSER_RESEARCH_RESULTS=str(result))
  xctest=subprocess.run(['xcrun','--find','xctest'],capture_output=True,text=True,check=True).stdout.strip();bundle=next((spaceo/'.build/out/Products/Debug').glob('*.xctest'))
  with (out/'spaceo-renderer-xctest.log').open('w') as log:
   run=subprocess.run([xctest,'-XCTest','SpaceOKitTests.BrowserContractResearchTests/testMeasuredBridgeAgainstControlledRenderer',str(bundle)],env=env,stdout=log,stderr=log,timeout=180)
  if run.returncode:raise RuntimeError('actual SpaceO renderer experiment failed; inspect private log')
  rows=json.loads(result.read_text())
  for repeat in range(3):
   for case in CASES:
    rid=f'oh-{repeat}-{case}';url=base+'/?case='+case+'&run='+rid;cdp.navigate(url)
    driver=RendererDriver(cdp);f=Facade(driver=driver,agent_display=AgentDisplay(mode='off'))
    started=time.monotonic();status='sent';reason=None
    try:
     if case=='form':
      for ident,text in [('name','Ada Lovelace'),('note','Synthetic intake')]:
       observed=f.observe(1,2);state=f.state(observed['snapshot']);node=next(n for n in state['nodes'].values() if n.get('_fixture_id')==ident)
       picked=f.choose(observed['snapshot'],'Enter synthetic field',candidate_ids=['e'+str(node['element_index'])],mode='exact',exact_name=node['label'],exact_role=node['role'],operation='type_text',text=text)
       f.act(picked['selection'])
      observed=f.observe(1,2);state=f.state(observed['snapshot']);node=next(n for n in state['nodes'].values() if n.get('_fixture_id')=='submit');f.act(f.bind_press(observed['snapshot'],'e'+str(node['element_index']),'Submit synthetic intake'))
     else:
      observed=f.observe(1,2);state=f.state(observed['snapshot']);node=next(n for n in state['nodes'].values() if n.get('_fixture_id')=='target');selection=f.bind_press(observed['snapshot'],'e'+str(node['element_index']),'Reserve intended appointment')
      if case=='navigation':cdp.navigate(url+'&doc=other')
      elif case in MUTATIONS:cdp.evaluate(MUTATIONS[case])
      f.act(selection)
    except Gap as e:status='refused';reason=str(e).split(':',1)[0]
    time.sleep(.1)
    rows.append({'arm':'OH Facade + research renderer adapter','case':case,'run':rid,'status':status,'reason':reason,'actionMilliseconds':(time.monotonic()-started)*1000,'researchDriverCalls':driver.calls})
  png=base64.b64decode(cdp.call('Page.captureScreenshot',{'format':'png'})['data']);(out/'oh-renderer.png').write_bytes(png)
  for row in rows:
   actual=[e for e in events if e['run']==row['run']];row['events']=actual;row['outcome']=event_score(row['case'],actual)
  (out/'renderer-results.json').write_text(json.dumps({'kind':'controlled real-renderer contract experiment','virtualDisplayQualified':False,'stockDriverQualified':False,'scriptedInitialSelections':True,'repeats':3,'rows':rows},indent=2))
  summary={}
  for row in rows:summary.setdefault(row['arm'],{}).setdefault(row['outcome'],0);summary[row['arm']][row['outcome']]+=1
  print(json.dumps(summary))
 finally:
  if cdp:cdp.close()
  server.shutdown();server.server_close()
  proc.terminate()
  try:proc.wait(timeout=5)
  except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
  log.close()
  import shutil;shutil.rmtree(profile)

if __name__=='__main__':main()
