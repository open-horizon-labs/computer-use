"""First-class local MCP tools for the configured computer-use stack."""
from contextlib import asynccontextmanager
import atexit
import base64
import json
from typing import Any, Literal
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


class Predicate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    field: str = Field(min_length=1)
    op: Literal['eq','neq','ne','gt','gte','lt','lte','contains','not_contains'] = Field(
        default='eq', description="'ne' aliases 'neq'; contains/not_contains are case-insensitive, "
                                   'whitespace-normalized substring checks and apply only to text fields')
    value: Any


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
def cua_read(snapshot:str,task:str,fields:dict[str,ReadField],record_ids:list[str],predicates:list[Predicate]|None=None,coverage_complete:bool=False) -> dict:
    """Use NuExtract3 to read requested fields from observed record subtrees. fields maps names to {description,type}; predicates use {field,op,value}, op one of eq, neq (alias ne), gt, gte, lt, lte, contains, not_contains (contains/not_contains are text-only substring checks; default eq). Choose one nonoverlapping observed root per logical record; never whole-page roots spanning several listings. Types use text (string accepted), number, money, or the dispatcher types. Money requires currency: USD; otherwise use text. Missing values stay unknown. Returns reading handle and record-bound fields/filter; an incomplete/unknown scope's defer lists unknown_ids, eligible_ids, excluded_count and the missing field per unknown record."""
    with facade.lock:return facade.read(snapshot,task,{k:v.model_dump(exclude_none=True) for k,v in fields.items()},record_ids,[p.model_dump() for p in predicates] if predicates else None,coverage_complete)

@mcp.tool(annotations=READ)
def cua_choose(snapshot:str,goal:str,candidate_ids:list[str]|None=None,mode:Literal['exact','semantic','visual','spans','regions']='semantic',exact_name:str|None=None,exact_role:str|None=None,operation:Literal['click','type_text']='click',text:str|None=None,reading:str|None=None,fields:dict|None=None,predicates:list[Predicate]|None=None,order_by:list[dict]|None=None,coverage_complete:bool=False,record_actions:dict[str,str]|None=None) -> dict:
    """Select, don't execute. Default semantic mode invokes the configured Jev/Julia chooser on observed alternatives; a singleton requires a complete filtered reading, not a caller-preselected winner. Exact mode requires a genuinely unique observed name/role, and checks the full observed scope after verified row/column table projections are represented once. Visual mode invokes SystemOne, and its pick only authorizes a selection when corroborated: either by a complete filtered reading (candidates are already the reading's mapped controls), or deterministically, by the goal's own quoted text appearing in that candidate's record context and no other's; otherwise it defers with reason visual_uncorroborated and a non-executable suggested_id. Spans invokes qualified GLiNER2. Regions mode offers Cua Perception's parsed screenshot regions (text/icon, canvas/pixel-only targets with no AX control) from THIS observation's live Driver capture as candidates, under the same answer-leak and quoted-text corroboration rules as visual mode; requires cua-perception healthy and a live capture_id, and cua_act delivers it only via the Driver's capture-bound click (never rebound to a later capture). Describe selection criteria in goal, never the answer: do not name an observed element ID (e.g. e12) or say things like 'the correct one is ...' -- that is rejected. A candidate_ids scope narrower than all observed same-kind controls, with no reading, is marked caller_preselected in the result and trace so it is not counted as chooser accuracy. With a reading handle, additional predicates filter its cached evidence without rereading (predicates: op one of eq, neq/ne, gt, gte, lt, lte, contains, not_contains). Unknown/incomplete scopes defer with unknown_ids, eligible_ids, excluded_count and the missing field per unknown record. Schemas belong on cua_read; order_by belongs to spans. candidate_ids may name all eligible record roots or their mapped controls; omit it when using record_actions. If a record contains multiple controls, record_actions maps each eligible record root to its observed descendant control. Returns opaque selection handle; never accepts Driver arguments or caller-created action IDs."""
    with facade.lock:return facade.choose(snapshot,goal,candidate_ids,mode,exact_name,exact_role,operation,text,reading,fields,[p.model_dump() for p in predicates] if predicates else None,order_by,coverage_complete,record_actions)

@mcp.tool(annotations=ACT)
def cua_act(selection:str) -> dict:
    """Execute one server-held selection through Cua Driver after a fresh unchanged-state check. Refuses stale, changed or replayed selections, and refuses with needs_foreground if the window is on another Space or AX-unresolved (the facade never activates, raises or moves windows). Delivery is not success: call cua_verify afterward. Does not accept commands, coordinates or edited action arguments."""
    with facade.lock:return facade.act(selection)

@mcp.tool(annotations=READ)
def cua_verify(pid:int,window_id:int,postcondition:str,mode:Literal['exact','visual']='visual',name:str|None=None,role:str|None=None,value:str|None=None,match:Literal['equals','contains']='equals') -> CallToolResult:
    """Independently reobserve and check the declared postcondition. match controls exact-mode label/value comparison (equals, or contains for a case-insensitive substring); visual mode first checks any "quoted" postcondition text deterministically against the fresh AX tree (route exact_text_postcondition) and only calls SystemOne/Qwen when that text isn't found there. Returns that fresh screenshot and observation for reconciliation and the next choice. Missing AX text or unchanged pixels never means success or a stall. Describe visible outcomes, not an assumed screen layout."""
    with facade.lock:return with_screenshot(facade.verify(pid,window_id,postcondition,mode,name,role,value,match))

@mcp.tool(annotations=READ)
def cua_trace() -> dict:
    """Return content-free actual routes, provider starts, timing, bypass reasons, caller_preselected flags, the detected driver_version/perception_version/perception_state and verification outcomes for this task."""
    with facade.lock:return {'events':list(facade.events),'driver_version':facade.driver_version,'driver_version_state':facade.driver_version_state,
                             'perception_version':facade.perception_version,'perception_state':facade.perception_state}

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,idempotentHint=True))
def cua_finish() -> dict:
    """Release this facade's task-scoped model workers and invalidate handles, without stopping Cua Driver or other tasks."""
    with facade.lock:return facade.close()

if __name__=='__main__':mcp.run()
