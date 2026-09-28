"""Offline MCP protocol smoke. Run using the interpreter with requirements.txt installed."""
import asyncio,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
 code=("import sys;sys.path.insert(0,'facade');import server;from test_core import FakeDriver,FakeReader,FakeChooser,FakeVision;"
       "from core import Facade;d=FakeDriver();d.capture_id='cap_test';"
       "server.facade=Facade(d,reader_factory=FakeReader,generic_factory=FakeChooser,visual_factory=FakeVision);server.mcp.run()")
 async with stdio_client(StdioServerParameters(command=sys.executable,args=['-c',code],cwd=str(ROOT))) as (r,w):
  async with ClientSession(r,w) as s:
   await s.initialize();ts=(await s.list_tools()).tools
   assert ts[0].name=='cua_do' and ts[0].description.startswith('Default path.'),[t.name for t in ts]
   assert all(t.description.startswith('Advanced') for t in ts[1:]),[t.name for t in ts if not t.description.startswith('Advanced')]
   assert {'goal','title','pid','window_id','records','operation','text','expect','accept_unknown','budget_s'}<=set(ts[0].inputSchema['properties'])
   assert 'title' in next(t for t in ts if t.name=='cua_windows').inputSchema['properties']
   x=await s.call_tool('cua_windows',{'title':'Other'});assert '"windows": []' in x.content[0].text
   o=await s.call_tool('cua_observe',{'pid':1,'window_id':2});sid=o.structuredContent['snapshot']
   typed=await s.call_tool('cua_read',{'snapshot':sid,'task':'Read price','fields':{'price':{'description':'Price','type':'money'}},'record_ids':['e1']});assert not typed.isError and json.loads(typed.content[0].text)['types_ignored']=={'price':'money'}
   read=await s.call_tool('cua_read',{'snapshot':sid,'task':'Read condition','fields':{'condition':{'description':'Condition','type':'text'}},'record_ids':['e1','e4'],'coverage_complete':True})
   reading=json.loads(read.content[0].text)['reading']
   choice=await s.call_tool('cua_choose',{'snapshot':sid,'goal':'Inspect used','reading':reading,'candidate_ids':['e1','e4'],'record_actions':{'e1':'e3','e4':'e6'},'predicates':[{'field':'condition','value':'Used'}]})
   assert json.loads(choice.content[0].text)['selected_id']=='e3'
   v=await s.call_tool('cua_verify',{'pid':1,'window_id':2,'postcondition':'Inspect first visible','mode':'exact','name':'Inspect first'})
   assert v.structuredContent['observation']['snapshot']==v.structuredContent['snapshot']
   assert any(c.type=='image' for c in v.content)
   assert 'regions' in json.dumps(next(t for t in ts if t.name=='cua_choose').inputSchema)
   # Fake driver has a live capture_id but perception is not installed: regions
   # mode must name the actionable install gap, never silently return an empty
   # scope or invent a fallback.
   o2=await s.call_tool('cua_observe',{'pid':1,'window_id':2});sid2=o2.structuredContent['snapshot']
   gap=await s.call_tool('cua_choose',{'snapshot':sid2,'goal':'Pick a region','mode':'regions'})
   assert gap.isError and 'perception' in gap.content[0].text
   spec={'fields':{'condition':{'description':'Condition'}},'predicates':[{'field':'condition','value':'Used'}],'record_ids':['e1','e4'],'coverage_complete':True}
   done=await s.call_tool('cua_do',{'goal':'Inspect the used product','title':'Demo','records':spec});out=json.loads(done.content[0].text)
   assert not done.isError and out['status']=='done' and out['selected']['id']=='e3' and out['verification']['status']=='satisfied' and out['trace_summary']['follow_up_needed'] is False,done.content[0].text
   leak=await s.call_tool('cua_do',{'goal':'Inspect e3','title':'Demo'});assert json.loads(leak.content[0].text)['status']=='refused'
   fin=json.loads((await s.call_tool('cua_finish',{})).content[0].text)
   assert 'perception_version' in fin and 'perception_state' in fin
   print('Protocol checks passed: cua_do first with the default-path schema and one end-to-end call, title filter, typed read schema ignored (S4.8), cached read predicates and root mapping, fresh verification observation and screenshot, regions mode schema/gap, perception status in cua_finish.')
asyncio.run(main())
