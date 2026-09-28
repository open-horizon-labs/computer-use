"""First-class local MCP tools for the configured computer-use stack."""
from contextlib import asynccontextmanager
import atexit
import base64
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations, CallToolResult, TextContent, ImageContent
from core import Facade

facade=Facade()
atexit.register(facade.close)

@asynccontextmanager
async def lifespan(server):
    try:yield {}
    finally:facade.close()

mcp=FastMCP('CUA task tools', instructions='Use cua_windows then cua_observe. Read observed record roots with cua_read (NuExtract); choose contextual actions with cua_choose (configured Jev/Julia), spans with GLiNER2, or real unique named controls with exact mode. Execute only selection handles with cua_act, then cua_verify. Do not invent control IDs or write ad hoc shell wrappers. Preserve the user\'s ordered prerequisites; choose the next unmet step and verify its visible outcome before advancing. Call cua_finish to release workers.',lifespan=lifespan)
READ=ToolAnnotations(readOnlyHint=True,openWorldHint=True)
ACT=ToolAnnotations(readOnlyHint=False,destructiveHint=True,idempotentHint=False,openWorldHint=True)

class ReadField(BaseModel):
    model_config = ConfigDict(extra='forbid')
    description: str = Field(min_length=1, description='Meaning of the source field, without expected answers')
    type: Literal['text','string','number','money','time','duration_minutes'] = 'text'
    currency: Literal['USD'] | None = Field(default=None, description='Required for money; use text for other currencies')

    @model_validator(mode='after')
    def money_requires_currency(self):
        if self.type == 'money' and self.currency is None:
            raise ValueError('Money fields require currency: USD; use text for unparsed prices')
        return self


def with_screenshot(result):
    content=[TextContent(type='text',text=json.dumps(result))]
    pixels=facade.state(result['snapshot'])['image']
    if pixels:content.append(ImageContent(type='image',data=base64.b64encode(pixels).decode(),mimeType='image/png'))
    return CallToolResult(content=content,structuredContent=result)

@mcp.tool(annotations=READ)
def cua_windows(title:str|None=None) -> dict:
    """Discover available Mac windows through local Cua Driver; returns app, title, pid and window_id. Supply an exact title to omit unrelated windows."""
    with facade.lock:return facade.windows(title)

@mcp.tool(annotations=READ)
def cua_observe(pid:int,window_id:int) -> CallToolResult:
    """Fresh Driver screenshot plus AX observation. Returns opaque snapshot and observed element IDs/parents, with alias_of for equivalent complete table projections. These IDs are the only inputs allowed for reading and selection. No inference; no UI action."""
    with facade.lock:
        return with_screenshot(facade.observe(pid,window_id))

@mcp.tool(annotations=READ)
def cua_read(snapshot:str,task:str,fields:dict[str,ReadField],record_ids:list[str],predicates:list[dict]|None=None,coverage_complete:bool=False) -> dict:
    """Use NuExtract3 to read requested fields from observed record subtrees. fields maps names to {description,type}; predicates use {field,op,value}. Choose one nonoverlapping observed root per logical record; never whole-page roots spanning several listings. Types use text (string accepted), number, money, or the dispatcher types. Money requires currency: USD; otherwise use text. Missing values stay unknown. Returns reading handle and record-bound fields/filter."""
    with facade.lock:return facade.read(snapshot,task,{k:v.model_dump(exclude_none=True) for k,v in fields.items()},record_ids,predicates,coverage_complete)

@mcp.tool(annotations=READ)
def cua_choose(snapshot:str,goal:str,candidate_ids:list[str]|None=None,mode:Literal['exact','semantic','visual','spans']='semantic',exact_name:str|None=None,exact_role:str|None=None,operation:Literal['click','type_text']='click',text:str|None=None,reading:str|None=None,fields:dict|None=None,predicates:list[dict]|None=None,order_by:list[dict]|None=None,coverage_complete:bool=False,record_actions:dict[str,str]|None=None) -> dict:
    """Select, don't execute. Default semantic mode invokes the configured Jev/Julia chooser on observed alternatives; a singleton requires a complete filtered reading, not a caller-preselected winner. Exact mode requires a genuinely unique observed name/role, and checks the full observed scope after verified row/column table projections are represented once. Visual mode invokes SystemOne; spans invokes qualified GLiNER2. With a reading handle, additional predicates filter its cached evidence without rereading. Unknown/incomplete scopes defer. Schemas belong on cua_read; order_by belongs to spans. candidate_ids may name all eligible record roots or their mapped controls; omit it when using record_actions. If a record contains multiple controls, record_actions maps each eligible record root to its observed descendant control. Returns opaque selection handle; never accepts Driver arguments or caller-created action IDs."""
    with facade.lock:return facade.choose(snapshot,goal,candidate_ids,mode,exact_name,exact_role,operation,text,reading,fields,predicates,order_by,coverage_complete,record_actions)

@mcp.tool(annotations=ACT)
def cua_act(selection:str) -> dict:
    """Execute one server-held selection through Cua Driver after a fresh unchanged-state check. Refuses stale, changed or replayed selections. Delivery is not success: call cua_verify afterward. Does not accept commands, coordinates or edited action arguments."""
    with facade.lock:return facade.act(selection)

@mcp.tool(annotations=READ)
def cua_verify(pid:int,window_id:int,postcondition:str,mode:Literal['exact','visual']='visual',name:str|None=None,role:str|None=None,value:str|None=None) -> CallToolResult:
    """Independently reobserve and check the declared postcondition. Visual uses SystemOne/Qwen screenshots. Exact checks an observed label/role and optional value. Returns that fresh screenshot and observation for reconciliation and the next choice. Missing AX text or unchanged pixels never means success or a stall. Describe visible outcomes, not an assumed screen layout."""
    with facade.lock:return with_screenshot(facade.verify(pid,window_id,postcondition,mode,name,role,value))

@mcp.tool(annotations=READ)
def cua_trace() -> dict:
    """Return content-free actual routes, provider starts, timing, bypass reasons and verification outcomes for this task."""
    with facade.lock:return {'events':list(facade.events)}

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,idempotentHint=True))
def cua_finish() -> dict:
    """Release this facade's task-scoped model workers and invalidate handles, without stopping Cua Driver or other tasks."""
    with facade.lock:return facade.close()

if __name__=='__main__':mcp.run()
