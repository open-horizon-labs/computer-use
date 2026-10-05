import importlib.util,sys,os,json,statistics,uuid
from pathlib import Path
p=Path(os.environ.get('ARC_COMPARISON_HARNESS','/tmp/computer-use-arc-review-20261005/experiments/arc-cua-comparison-2026-10-05'))/'run.py'
spec=importlib.util.spec_from_file_location('comparison',p); r=importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
versions=r.candidate_versions()
arc=r.MCP([sys.executable,'-m','arc_cua','mcp'],'arc')
native=r.MCP(['cua-driver','mcp','--socket',str(Path.home()/'Library/Caches/cua-driver/cua-driver.sock')],'native')
r.verify_servers(versions,arc,native)
original=native.call
session='oh-cursor-web-ablation-'+uuid.uuid4().hex[:10]
def call(name,**args):
    if 'session' in native.schemas[name].get('properties',{}): args['session']=session
    return original(name,**args)
native.call=call
sys.path.insert(0,str(p.parent))
import web_run as web
out={**versions,'results':[],'settings':[]}
try:
    for rep in range(3):
        modes=['enabled','disabled','arc'] if rep%2==0 else ['arc','disabled','enabled']
        for mode in modes:
            client=arc if mode=='arc' else native
            if mode!='arc':
                setting,error=native.call('set_agent_cursor_enabled',enabled=mode=='enabled')
                if error: raise RuntimeError(setting)
                state,state_error=native.call('get_agent_cursor_state')
                if state_error or state.get('enabled')!=(mode=='enabled'): raise RuntimeError('cursor state mismatch')
                out['settings'].append({'mode':mode,'response':setting,'state':state})
            row=web.trial(client,rep);row['mode']=mode
            out['results'].append(row)
            Path('/tmp/cua-cursor-performance-20261005/web-results.json').write_text(json.dumps(out,indent=2))
            print(json.dumps({k:row.get(k) for k in ('mode','rep','passed','tool_ms','error')}),flush=True)
finally:
    try: native.call('set_agent_cursor_enabled',enabled=True)
    finally: native.close();arc.close()
