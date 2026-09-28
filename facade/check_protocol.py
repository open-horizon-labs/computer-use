"""Offline MCP protocol smoke. Run using the interpreter with requirements.txt installed."""
import asyncio,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
 code="import sys;sys.path.insert(0,'facade');import server;from test_core import FakeDriver,FakeReader,FakeChooser,FakeVision;from core import Facade;server.facade=Facade(FakeDriver(),reader_factory=FakeReader,generic_factory=FakeChooser,visual_factory=FakeVision);server.mcp.run()"
 async with stdio_client(StdioServerParameters(command=sys.executable,args=['-c',code],cwd=str(ROOT))) as (r,w):
  async with ClientSession(r,w) as s:
   await s.initialize();ts=(await s.list_tools()).tools
   assert 'title' in next(t for t in ts if t.name=='cua_windows').inputSchema['properties']
   x=await s.call_tool('cua_windows',{'title':'Other'});assert '"windows": []' in x.content[0].text
   o=await s.call_tool('cua_observe',{'pid':1,'window_id':2});sid=o.structuredContent['snapshot']
   bad=await s.call_tool('cua_read',{'snapshot':sid,'task':'Read price','fields':{'price':{'description':'Price','type':'money'}},'record_ids':['e1']});assert bad.isError and 'currency' in bad.content[0].text
   read=await s.call_tool('cua_read',{'snapshot':sid,'task':'Read condition','fields':{'condition':{'description':'Condition','type':'text'}},'record_ids':['e1','e4'],'coverage_complete':True})
   reading=json.loads(read.content[0].text)['reading']
   choice=await s.call_tool('cua_choose',{'snapshot':sid,'goal':'Inspect used','reading':reading,'candidate_ids':['e1','e4'],'record_actions':{'e1':'e3','e4':'e6'},'predicates':[{'field':'condition','value':'Used'}]})
   assert json.loads(choice.content[0].text)['selected_id']=='e3'
   v=await s.call_tool('cua_verify',{'pid':1,'window_id':2,'postcondition':'Inspect first visible','mode':'exact','name':'Inspect first'})
   assert v.structuredContent['observation']['snapshot']==v.structuredContent['snapshot']
   assert any(c.type=='image' for c in v.content)
   await s.call_tool('cua_finish',{})
   print('Protocol checks passed: title filter, money schema, cached read predicates and root mapping, fresh verification observation and screenshot.')
asyncio.run(main())
