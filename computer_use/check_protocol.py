"""Real stdio MCP smoke for the native-first contract; fake mobile, no desktop/model/network."""
import asyncio
import json
import os
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT=Path(__file__).resolve().parents[1]
CODE="""import sys
sys.path.insert(0,'computer_use')
import server
from test_mobile import overview_backend,facade_for
backend=overview_backend()
f=facade_for(backend)
f.driver.call=lambda *a,**kw: (_ for _ in ()).throw(AssertionError('no desktop I/O'))
server.facade=f
server.contexts.factory=lambda options:f
server.mcp.run()
"""
async def probe(advanced):
    env={**os.environ,'CUA_TASK_ADVANCED':str(advanced)}
    async with stdio_client(StdioServerParameters(command=sys.executable,args=['-c',CODE],cwd=str(ROOT),env=env)) as (r,w):
        async with ClientSession(r,w) as s:
            await s.initialize()
            tools=(await s.list_tools()).tools
            assert [t.name for t in tools]==['do','look']
            do,look=tools
            assert set(do.inputSchema['required'])=={'goal','steps'}
            assert not {'terminal','title','pid','window_id','context','fields','records','allow_foreground'} & do.inputSchema['properties'].keys()
            async def call(name,args):
                out=await s.call_tool(name,args)
                assert not out.isError,out.content
                return out.structuredContent or json.loads(out.content[0].text)
            assert (await call('look',{}))['reason']=='native_default'
            assert (await call('look',{'device':'emulator-5554'}))['reason']=='native_default'
            assert (await call('look',{'capability':'off_screen'}))['reason']=='off_screen_session_required'
            seen=await call('look',{'capability':'mobile','device':'emulator-5554'})
            assert seen['status']=='ok' and seen['look_id'].startswith(seen['context_id']+':'),seen
            blind=await call('do',{'goal':'Forget Office','capability':'mobile','context_id':seen['context_id'],'steps':[{'do':'press','where':{'lines':[{'line':'eq','value':'Office'}]},'expect':'Office forgotten'}]})
            assert blind['reason']=='look_required',blind
            done=await call('do',{'goal':'Open Networks','capability':'mobile','context_id':seen['context_id'],'look_id':seen['look_id'],'steps':[{'do':'press','control':'Networks','expect':'Saved networks'}]})
            assert done['status']=='done',done
            for step in ({'do':'press','profile':'user'},{'do':'terminal','text':'echo x'},{'do':'read_pages','urls':[]}):
                bad=await s.call_tool('do',{'goal':'Archived','capability':'off_screen','steps':[step]})
                assert bad.isError,step
            assert (await s.call_tool('windows',{})).isError
async def main():
    await probe(0);await probe(1)
    print('Native-first MCP passed: two tools, default refusal, explicit mobile binding/verification, blind-filter refusal, archived schema/tool rejection. Legacy advanced setting adds nothing.')
if __name__=='__main__':asyncio.run(main())
