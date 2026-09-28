"""First-class local MCP tools for the configured computer-use stack."""
from contextlib import asynccontextmanager
import atexit
import base64
import os
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

ADVANCED=os.environ.get('CUA_TASK_ADVANCED')=='1'  # the primitives are opt-in: with eight tools visible the LLM mediates every hop itself
mcp=FastMCP('CUA task tools', instructions='Call cua_do once with the goal and expect (the text that will appear). For lists add records: the fields to read and predicates to match; add control (the exact button label) when each record has several. It observes, reads, matches, chooses, acts and verifies for you. When it returns deferred, the response holds everything needed to call cua_do again (control labels, unknown records with their extracted strings, dialog control labels, the exact label to pass as confirm); repeat the call with that refinement.',lifespan=lifespan)
READ=ToolAnnotations(readOnlyHint=True,openWorldHint=True)
ACT=ToolAnnotations(readOnlyHint=False,destructiveHint=True,idempotentHint=False,openWorldHint=True)

class ReadField(BaseModel):
    model_config = ConfigDict(extra='forbid')
    description: str = Field(min_length=1, description='Meaning of the source field, without expected answers')
    type: str | None = Field(default=None, description='Ignored: readings are the displayed strings (S4.8). '
                             'Interpret durations, times and prices yourself; a supplied type is reported as types_ignored.')
    currency: str | None = Field(default=None, description='Ignored; prices are returned as displayed')


class Predicate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    field: str = Field(min_length=1)
    op: Literal['eq','neq','ne','gt','gte','lt','lte','contains','not_contains'] = Field(
        default='eq', description="'ne' aliases 'neq'; contains/not_contains are case-insensitive, "
                                   'whitespace-normalized substring checks and apply only to text fields')
    value: Any


class DoPredicate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    field: str = Field(min_length=1)
    op: Literal['eq','neq','contains','not_contains'] = Field(default='eq', description='Case-insensitive, whitespace-normalized checks on the displayed strings')
    value: Any


class DoRecords(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fields: dict[str,ReadField] = Field(description='Field name -> {description}; values are the strings the page displays (S4.8)')
    predicates: list[DoPredicate]|None = Field(default=None, description='Same-record criteria, conjunctive; you state what you want, the specialists read and match')
    record_ids: list[str]|None = Field(default=None, description='Optional observed record roots; omit to auto-discover one record per repeated control')
    coverage_complete: bool = Field(default=False, description='Only with record_ids: true when they are every record in scope')
    identity: list[str]|None = Field(default=None, description='Field names that identify a record when a confirm dialog shows it (e.g. ["order"]); default: the fields your eq predicates constrain, else all fields')


def with_screenshot(result):
    content=[TextContent(type='text',text=json.dumps(result))]
    pixels=facade.state(result['snapshot'])['image']
    if pixels:content.append(ImageContent(type='image',data=base64.b64encode(pixels).decode(),mimeType='image/png'))
    return CallToolResult(content=content,structuredContent=result)

@mcp.tool(annotations=ACT)
def cua_do(goal:str,expect:str|None,title:str|None=None,pid:int|None=None,window_id:int|None=None,records:DoRecords|None=None,control:str|None=None,operation:Literal['click','type_text','verify']='click',text:str|None=None,accept_unknown:list[str]|None=None,budget_s:float=20,confirm:str|None=None,treat_as_match:list[str]|None=None,near:str|None=None) -> dict:
    """Default path. One call does the whole observe→read→match→choose→act→verify chain server-side; describe the goal and, for lists, the fields/predicates. Use the other cua_* tools only for escape hatches.

    Required: goal (what you want, in words: criteria, never element IDs or "the correct one is ...") and expect (the text that will be visible once it worked, e.g. "Booked:" or "Order #1044 cancelled"). expect is how the call proves the result independently; pass null only if nothing observable can confirm it, and then the call ends delivered_unverified, never done. Give the exact window title in title (or pid+window_id); no other call is needed first.

    For a list pass records={fields:{name:{description}}, predicates:[{field,op,value}]}: records are discovered from the repeated actionable control (a button, not repeated text), read once, filtered same-record, and only if several remain is ONE chooser called over those alone. If each record has several buttons (Track, Cancel) pass control=the exact label to press (control matches a label exactly, else as a whole-word prefix: "Book" matches "Book Dr. B"). Records need not share a label: per-record labels and a single record work. If a confirm dialog may follow, pass confirm=the exact label of its control (and records.identity when your eq predicates are not the fields it displays); without confirm a dialog is never pressed. Without records, a quoted goal label that names one control resolves exactly, or control does. operation='verify' with expect only re-checks the window, never clicks, and answers observed (text is visible now, presence only, never done). expect is matched against page text, never a button label.

    Predicates are compared as displayed strings; a record whose value cannot be compared (a digit-bearing predicate against "half-hour", or an outlier of the field's shape) is UNKNOWN, never excluded, and the call defers with the strings: repeat with accept_unknown=<ids> (they do NOT match) or treat_as_match=<ids> (you judge they DO match). evidence.excluded_values shows what the predicates threw away. On a pixel-only page (canvas) with Perception, control=<exact drawn text> is resolved against on-screen text uniquely; if the text is drawn more than once pass near=<the text just above or left of the one you mean>. Recovery (stale UI, transient failures, an unknown field, verification escalation) happens inside the call within budget_s (hard cap 3x). Returns status done|deferred|refused|failed|delivered_unverified|observed with stage, selected, judgment, verification, evidence, a small observation summary, and trace_summary (follow_up_needed is true unless done). deferred means guessing would be worse and the response carries what you need to call cua_do again: control labels (control_needed), unknown records with their extracted strings (repeat with accept_unknown naming exactly the ones you judge ineligible), the dialog's control labels (dialog.controls), or found candidates. dead_end: true means nothing you can pass will move forward: stop and tell the user (report_to_user), do not retry. After a deferral with delivery delivered the click is done: never repeat the goal; re-check with operation='verify'."""
    with facade.lock:return facade.do(goal,title,pid,window_id,records.model_dump(exclude_none=True) if records else None,operation,text,expect,accept_unknown,budget_s,confirm,control,treat_as_match,near)

def register_advanced():
    """The eight primitives, registered only when CUA_TASK_ADVANCED=1 (documented in docs/FACADE.md)."""
    @mcp.tool(annotations=READ)
    def cua_windows(title:str|None=None) -> dict:
        """Advanced: use only if cua_do defers and you need finer control. Discover available Mac windows through local Cua Driver; returns app, title, pid and window_id. Supply an exact title to omit unrelated windows."""
        with facade.lock:return facade.windows(title)

    @mcp.tool(annotations=READ)
    def cua_observe(pid:int,window_id:int) -> CallToolResult:
        """Advanced: use only if cua_do defers and you need finer control. Fresh Driver screenshot plus AX observation. Returns opaque snapshot and observed element IDs/parents, with alias_of for equivalent complete table projections. These IDs are the only inputs allowed for reading and selection. No inference; no UI action."""
        with facade.lock:
            return with_screenshot(facade.observe(pid,window_id))

    @mcp.tool(annotations=READ)
    def cua_read(snapshot:str,task:str,fields:dict[str,ReadField],record_ids:list[str],predicates:list[Predicate]|None=None,coverage_complete:bool=False) -> dict:
        """Advanced: use only if cua_do defers and you need finer control. Use NuExtract3 to read requested fields from observed record subtrees. fields maps names to {description,type}; predicates use {field,op,value}, op one of eq, neq (alias ne), contains, not_contains on the displayed strings (default eq). Readings are strings (S4.8): any supplied type is ignored and echoed as types_ignored; you interpret durations, times and prices yourself. Choose one nonoverlapping observed root per logical record; never whole-page roots spanning several listings. Missing values stay unknown. At most two readings of the same records per observation: judge the strings instead of re-reading. Returns reading handle and record-bound fields/filter; an incomplete/unknown scope's defer lists unknown_ids, eligible_ids, excluded_count and the missing field per unknown record."""
        with facade.lock:return facade.read(snapshot,task,{k:v.model_dump(exclude_none=True) for k,v in fields.items()},record_ids,[p.model_dump() for p in predicates] if predicates else None,coverage_complete)

    @mcp.tool(annotations=READ)
    def cua_choose(snapshot:str,goal:str,candidate_ids:list[str]|None=None,mode:Literal['exact','semantic','visual','spans','regions']='semantic',exact_name:str|None=None,exact_role:str|None=None,operation:Literal['click','type_text']='click',text:str|None=None,reading:str|None=None,fields:dict|None=None,predicates:list[Predicate]|None=None,order_by:list[dict]|None=None,coverage_complete:bool=False,record_actions:dict[str,str]|None=None,accept_unknown:list[str]|None=None) -> dict:
        """Advanced: use only if cua_do defers and you need finer control. Select, don't execute. Default semantic mode invokes the configured Jev/Julia chooser on observed alternatives; a singleton requires a complete filtered reading, not a caller-preselected winner. Exact mode requires a genuinely unique observed name/role, and checks the full observed scope after verified row/column table projections are represented once. Visual mode invokes SystemOne, and its pick only authorizes a selection when corroborated: either by a complete filtered reading (candidates are already the reading's mapped controls), or deterministically, by the goal's own quoted text appearing in that candidate's record context and no other's; otherwise it defers with reason visual_uncorroborated and a non-executable suggested_id. Spans invokes qualified GLiNER2. Regions mode offers Cua Perception's parsed screenshot regions (text/icon, canvas/pixel-only targets with no AX control) from THIS observation's live Driver capture as candidates, under the same answer-leak and quoted-text corroboration rules as visual mode; requires cua-perception healthy and a live capture_id, and cua_act delivers it only via the Driver's capture-bound click (never rebound to a later capture). Describe selection criteria in goal, never the answer: do not name an observed element ID (e.g. e12) or say things like 'the correct one is ...' -- that is rejected. A candidate_ids scope narrower than all observed same-kind controls, with no reading, is marked caller_preselected in the result and trace so it is not counted as chooser accuracy. With a reading handle, pass the records YOU judged eligible from its strings as candidate_ids (record IDs) or record_actions; they must be that reading's records, stated text predicates can only narrow them, and a single judged or filter-unique record binds directly with no chooser call (route grounded_singleton). If your verdict skips a record the reading left unknown, the call defers (unknown_competitors_unacknowledged, with their extracted strings) until you name exactly those IDs in accept_unknown. Additional predicates filter cached evidence without rereading (op: eq, neq/ne, contains, not_contains). Unknown/incomplete scopes defer with unknown_ids, eligible_ids, excluded_count and the missing field per unknown record. Schemas belong on cua_read; order_by belongs to spans. candidate_ids may name all eligible record roots or their mapped controls; omit it when using record_actions. If a record contains multiple controls, record_actions maps each eligible record root to its observed descendant control. Returns opaque selection handle; never accepts Driver arguments or caller-created action IDs."""
        with facade.lock:return facade.choose(snapshot,goal,candidate_ids,mode,exact_name,exact_role,operation,text,reading,fields,[p.model_dump() for p in predicates] if predicates else None,order_by,coverage_complete,record_actions,accept_unknown)

    @mcp.tool(annotations=ACT)
    def cua_act(selection:str) -> dict:
        """Advanced: use only if cua_do defers and you need finer control. Execute one server-held selection through Cua Driver after a fresh unchanged-state check. Refuses stale, changed or replayed selections, and refuses with needs_foreground if the window is on another Space or AX-unresolved (the facade never activates, raises or moves windows). Delivery is not success: call cua_verify afterward. Does not accept commands, coordinates or edited action arguments."""
        with facade.lock:return facade.act(selection)

    @mcp.tool(annotations=READ)
    def cua_verify(pid:int,window_id:int,postcondition:str,mode:Literal['exact','visual']='visual',name:str|None=None,role:str|None=None,value:str|None=None,match:Literal['equals','contains']='equals') -> CallToolResult:
        """Advanced: use only if cua_do defers and you need finer control. Independently reobserve and check the declared postcondition. match controls exact-mode label/value comparison (equals, or contains for a case-insensitive substring); visual mode first checks any "quoted" postcondition text deterministically against the fresh AX tree (route exact_text_postcondition) and only calls SystemOne/Qwen when that text isn't found there. Returns that fresh screenshot and observation for reconciliation and the next choice. Missing AX text or unchanged pixels never means success or a stall. Describe visible outcomes, not an assumed screen layout."""
        with facade.lock:return with_screenshot(facade.verify(pid,window_id,postcondition,mode,name,role,value,match))

    @mcp.tool(annotations=READ)
    def cua_trace() -> dict:
        """Advanced: use only if cua_do defers and you need finer control. Return content-free actual routes, provider starts, timing, bypass reasons, caller_preselected flags, the detected driver_version/perception_version/perception_state and verification outcomes for this task."""
        with facade.lock:return {'events':list(facade.events),'driver_version':facade.driver_version,'driver_version_state':facade.driver_version_state,
                                 'perception_version':facade.perception_version,'perception_state':facade.perception_state}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,idempotentHint=True))
    def cua_finish() -> dict:
        """Advanced: use only if cua_do defers and you need finer control. Release this facade's task-scoped model workers and invalidate handles, without stopping Cua Driver or other tasks."""
        with facade.lock:return facade.close()

if ADVANCED:register_advanced()

if __name__=='__main__':mcp.run()
