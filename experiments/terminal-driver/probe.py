#!/usr/bin/env python3
"""Opt-in live PTY/MCP qualification. No GUI, AX, GPU, credentials or external apps."""
import asyncio
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'computer_use'))
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    timings=[];scenarios=[];terminal_ids=[]
    env={**os.environ,'PYTHONPATH':str(ROOT/'computer_use')}
    async with stdio_client(StdioServerParameters(command=sys.executable,args=[str(ROOT/'computer_use/server.py')],cwd=str(ROOT),env=env)) as (reader,writer):
        async with ClientSession(reader,writer) as session:
            await session.initialize()
            async def call(tool,args):
                start=time.perf_counter()
                answer=await session.call_tool(tool,args)
                elapsed=round((time.perf_counter()-start)*1000,2)
                assert not answer.isError,answer.content
                out=answer.structuredContent or json.loads(answer.content[0].text)
                timings.append({'tool':tool,'ms':elapsed,'response_text_bytes':len(answer.content[0].text.encode()),'status':out['status']})
                return out,answer
            async def act(name,step):
                seen,_=await call('look',{'terminal':name})
                out,_=await call('do',{'goal':'Exercise synthetic terminal fixture','expect':None,'terminal':name,'look_id':seen['look_id'],'steps':[step]})
                assert out['status'] in ('done','delivered_unverified'),out
                return out
            with tempfile.TemporaryDirectory(prefix='cua-tui-evidence-') as raw:
                root=Path(raw)
                for i in range(5):
                    start=len(timings);result_file=root/f'menu-{i}.json'
                    out,_=await call('do',{'goal':'Launch fixture','expect':None,'terminal':'new','steps':[{'do':'launch','argv':[sys.executable,str(ROOT/'experiments/terminal-driver/menu.py'),str(result_file),'$(literal);not-a-shell'],'cwd':raw,'width':80,'height':24,'expect':'READY'}]})
                    assert out['status']=='done',out
                    name=out['terminal'];terminal_ids.append(name)
                    changed=await act(name,{'do':'press','control':'Down'})
                    assert changed['status']=='delivered_unverified',changed
                    # Must observe the style-only selection, not infer it from key acknowledgement.
                    for _ in range(3):
                        seen,_=await call('look',{'terminal':name})
                        if seen['styled_rows'] and seen['styled_rows'][0]['row']==2:break
                        await asyncio.sleep(.02)
                    assert seen['styled_rows'][0]['row']==2,seen
                    done,_=await call('do',{'goal':'Accept Beta','expect':None,'terminal':name,'look_id':seen['look_id'],'steps':[{'do':'press','control':'Enter','expect':'ACCEPTED Beta'}]})
                    assert done['status']=='done',done
                    truth=json.loads(result_file.read_text())
                    assert truth=={'selected':'Beta','keys':['1b4f42','0d'],'argv':['$(literal);not-a-shell']},truth
                    scenarios.append({'name':'styled_menu','trial':i+1,'calls':len(timings)-start,'wall_tool_ms':round(sum(t['ms'] for t in timings[start:]),2),'ground_truth':truth})
                    if i==0:
                        pixels,answer=await call('look',{'terminal':name,'screen':True})
                        assert pixels['status']=='ok' and any(b.type=='image' for b in answer.content),pixels
                        scenarios.append({'name':'terminal_png','status':'passed','width':pixels['image']['width'],'height':pixels['image']['height']})
                    await act(name,{'do':'close'})
                # Independently validate a real application, not only our fixture.
                outfile=root/'vim-saved.txt'
                out,_=await call('do',{'goal':'Open Vim','expect':None,'terminal':'new','steps':[{'do':'launch','argv':['/usr/bin/vim','-Nu','NONE','-n','-i','NONE',str(outfile)],'cwd':raw,'width':80,'height':24,'expect':'[New]'}]})
                assert out['status']=='done',out
                name=out['terminal'];terminal_ids.append(name)
                await act(name,{'do':'press','control':'i','expect':'-- INSERT --'})
                await act(name,{'do':'type','text':'Terminal driver qualification'})
                await act(name,{'do':'press','control':'Escape'})
                await act(name,{'do':'type','text':':w'})
                saved=await act(name,{'do':'press','control':'Enter','expect':'written'})
                assert saved['status']=='done',saved
                assert outfile.read_text()=='Terminal driver qualification\n'
                scenarios.append({'name':'vim_save','status':'passed','independent_file_contents_match':True})
                await act(name,{'do':'close'})
                inventory,_=await call('look',{'terminal':'list'})
                assert inventory['terminals']==[],inventory
    # Two real drivers must not share tu's usual per-user socket or lifecycle.
    from terminal import Terminal
    first,second=Terminal(),Terminal()
    try:
        launch_step=[{'do':'launch','argv':['/usr/bin/vim','-Nu','NONE','-n','-i','NONE'],'cwd':'/tmp','width':80,'height':24,'expect':'VIM - Vi IMproved'}]
        a=first.do('new',launch_step);b=second.do('new',launch_step)
        assert a['status']==b['status']=='done',(a,b)
        assert first.driver.directory.name!=second.driver.directory.name
        first.close()
        assert second.look(b['terminal'])['alive'] is True
        scenarios.append({'name':'private_daemon_isolation','status':'passed','closing_one_preserves_other':True})
    finally:
        first.close();second.close()
    report={'date':'2026-10-02','driver':'terminal-use 1.4.1','transport':'real MCP stdio and private PTY daemon','environment':'macOS arm64, no GUI/display/AX/model calls','limitations':'Synthetic menu and Vim only; not an agent bakeoff or general TUI accuracy/race/latency claim. Startup included in launch. PNG measured separately. Text postconditions are observations, not arbitrary semantic verification.','scenarios':scenarios,'tool_latency_ms':{'median':round(statistics.median(t['ms'] for t in timings),2),'max':max(t['ms'] for t in timings)},'calls':timings}
    report['cleanup']=f'all {len(terminal_ids)} MCP sessions closed; empty inventory verified; two independent daemons also closed'
    destination=Path(__file__).with_name('live-results.json')
    destination.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('driver','tool_latency_ms','scenarios','cleanup')},indent=2))


if __name__=='__main__':asyncio.run(main())
