"""Offline MCP protocol smoke, both surfaces. Run using the interpreter with requirements.txt installed.

Default mode: cua_do is the ONLY visible tool. CUA_TASK_ADVANCED=1 mode: the eight primitives appear too, all documented Advanced.
"""
import asyncio,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
CODE=("import sys;sys.path.insert(0,'facade');import server;from test_core import FakeDriver,FakeReader,FakeChooser,FakeVision;"
      "from core import Facade;d=FakeDriver();d.capture_id='cap_test';"
      "server.facade=Facade(d,reader_factory=FakeReader,generic_factory=FakeChooser,visual_factory=FakeVision);server.mcp.run()")
SPEC={'fields':{'condition':{'description':'Condition'}},'predicates':[{'field':'condition','value':'Used'}],'record_ids':['e1','e4'],'coverage_complete':True}
async def default_mode():
 async with stdio_client(StdioServerParameters(command=sys.executable,args=['-c',CODE],cwd=str(ROOT))) as (r,w):
  async with ClientSession(r,w) as s:
   await s.initialize();ts=(await s.list_tools()).tools
   assert [t.name for t in ts]==['cua_do'],[t.name for t in ts]
   do=ts[0];assert do.description.startswith('Default path.')
   assert {'goal','expect'}<=set(do.inputSchema['required']),do.inputSchema['required']
   assert {'goal','expect','title','pid','window_id','records','control','operation','text','accept_unknown','budget_s','confirm'}<=set(do.inputSchema['properties'])
   missing=await s.call_tool('cua_do',{'goal':'Inspect the used product','title':'Demo','records':SPEC});assert missing.isError,'expect is required in the schema'
   first=await s.call_tool('cua_do',{'goal':'Inspect the used product','title':'Demo','records':SPEC,'expect':None});out=json.loads(first.content[0].text)
   assert not first.isError and out['status']=='delivered_unverified' and out['selected']['id']=='e3' and out['trace_summary']['follow_up_needed'] is True,first.content[0].text
   check=await s.call_tool('cua_do',{'goal':'Check the page','title':'Demo','operation':'verify','expect':'Used $80'});assert json.loads(check.content[0].text)['status']=='observed'
   label=await s.call_tool('cua_do',{'goal':'Check the page','title':'Demo','operation':'verify','expect':'Inspect first'});assert json.loads(label.content[0].text)['status']=='deferred','a control label never proves an expect'
   leak=await s.call_tool('cua_do',{'goal':'Inspect e3','title':'Demo','expect':None});assert json.loads(leak.content[0].text)['status']=='refused'
   gone=await s.call_tool('cua_observe',{'pid':1,'window_id':2});assert gone.isError,'primitives must not be callable by default'
async def advanced_mode():
 async with stdio_client(StdioServerParameters(command=sys.executable,args=['-c',CODE],cwd=str(ROOT),env={'CUA_TASK_ADVANCED':'1'})) as (r,w):
  async with ClientSession(r,w) as s:
   await s.initialize();ts=(await s.list_tools()).tools
   assert ts[0].name=='cua_do' and ts[0].description.startswith('Default path.'),[t.name for t in ts]
   assert len(ts)==9 and all(t.description.startswith('Advanced') for t in ts[1:]),[t.name for t in ts if not t.description.startswith('Advanced')]
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
   done=await s.call_tool('cua_do',{'goal':'Inspect the used product','title':'Demo','records':SPEC,'expect':None});assert json.loads(done.content[0].text)['selected']['id']=='e3'
   fin=json.loads((await s.call_tool('cua_finish',{})).content[0].text)
   assert 'perception_version' in fin and 'perception_state' in fin
async def main():
 await default_mode();await advanced_mode()
 print('Protocol checks passed in both modes. Default: cua_do is the only tool, expect is required, delivered_unverified/verify/leak paths, primitives not callable. CUA_TASK_ADVANCED=1: nine tools all Advanced but cua_do, title filter, typed read schema ignored (S4.8), cached read predicates and root mapping, fresh verification observation and screenshot, regions mode schema/gap, perception status in cua_finish.')
asyncio.run(main())
