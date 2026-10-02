# Progressive Spaces access — 2026-10-02

## Solution Space

### Solution Space Analysis

**Problem:** Make isolated computer use available without advertising the entire Spaces administration surface to every task. **Key constraint:** Native computer use remains the default; OH has no measured automatic win. **Working story:** Spaces supplies isolation and Driver execution; task-specific discovery supplies only the needed schema. **Success signal:** Small initial metadata, bounded discovery, correct verified execution, and lower total task cost on a fair comparison. **Decision criteria:** Initial schema size, total discovery/output cost, correctness, maintenance and client portability. **Critical assumptions:** Filtered discovery stays small; the client can use the returned schemas; reducing tools does not imply reducing underlying execution authority.

### Candidates Considered

| Option | Level | Approach | Main trade-off |
|---|---|---|---|
| A | Status quo | Full Spaces MCP and client lazy loading | Client-dependent; 138 tools are still registered |
| B | Local optimum | Exact existing permission grants; three discovery/execution tools | Extra schema discovery and generic JSON arguments |
| C | Reframe | Skill plus CLI/SDK commands; no Spaces MCP registration | No standing schema, but shell instructions and setup may cost more |
| D | Redesign | Add Spaces behind OH look/do | Convenient contract, but new adapter, binding, lifecycle and verification maintenance |

### Interpretive Variety Check

A assumes the client solves tool overload. B tests whether upstream configuration already solves it. C removes the standing MCP surface entirely. D assumes a custom facade earns its maintenance cost. If B has lower initial metadata but worse total task cost, schema count was the wrong optimization target; compare C before building D.

### Risk Retirement Plan

| Risk / assumption | Planned disposition | Tempting patch this must fail | Evidence or rationale | Stop/pivot if |
|---|---|---|---|---|
| Permission groups remain too broad | Retired by evidence | Use spaces:all and call it slim | Real MCP tools/list: exact three-action grant exposes only three tools | A new release expands this exact grant |
| Discovery emits the entire Driver catalog | Triggered | Fetch all schemas once after hiding top-level tools | Next live run must filter list_tools by task-relevant names and count cumulative bytes | Full catalog is needed for the simple form |
| Smaller metadata worsens execution or total tokens | Triggered | Declare victory from tool count alone | Repeat the same form with the narrow grant; compare total calls, outputs, model tokens and receipt correctness | Total task cost rises or execution fails |
| Generic call_tool retains broad authority | Accepted with rationale | Treat tool hiding as a security boundary | Small surface is discovery optimization; guest ownership and upstream Driver permissions still govern execution | Tasks require a narrower authority policy |
| Another custom facade becomes a maintenance sink | Accepted with rationale | Immediately wire Spaces into OH | No adapter now; first use existing exact grants | Narrow upstream flow fails repeatable tasks |

### Recommendation

**Selected:** B, existing exact grants with progressive Driver schema discovery. **Level:** Local optimum. Keep native default and the current explicitly selected OH mobile/off-screen supplement installed. Do not install the full Spaces MCP surface by default. Spaces remains a separate explicit isolation option; no new OH route is being enabled by this recommendation.

For an existing selected Space:

```sh
cua mcp --permissions spaces:list_spaces,spaces:list_tools,spaces:call_tool
```

Discover the exact Space, request Driver schemas by name, bind a fresh target, execute through call_tool, and independently verify effects. Keep learned schemas within the task. Do not replace the three-tool catalog with a giant instruction blob. Lifecycle can remain CLI setup; if it must be agent-visible, add spaces:create_space and spaces:delete_space to a separate opt-in profile. Filter by explicit names; do not rely on unprefixed tool names as permissions.

**Accepted trade-offs:** A discovery round trip; generic arguments; lifecycle separate from routine work. No claims of faster or cheaper execution until measured.

### S&T Selection

No Problem Weave or existing S&T IDs applies. Selected scope is installation refresh and configuration evidence; a Spaces adapter and automatic preference are deferred.

### Execution Handoff

Preserve native default, fresh exact binding, independent verification and no blind coordinates. Next verify the three-tool profile on the already-qualified form with bounded schema retrieval; compare initial plus cumulative metadata, total calls, wall time and model token usage. A receipt mismatch or unbounded discovery invalidates the selected flow. Human verification is needed for logged-in teleport and locked-host claims; neither is required for this narrow configuration recommendation.

## Accuracy report

Counts below are direct real MCP tools/list results on installed Cua 0.2.0, without launching a Space or touching the desktop. Byte totals serialize tool model data compactly with null values omitted. They are metadata bytes, not prompt tokens. The earlier 106,083-byte full-surface figure used a different serialization that retained null fields; it should not be presented as a directly normalized savings percentage.

| Claim | Status | Evidence | Recommended edit |
|---|---|---|---|
| Default exposed 138 tools | Verified | Prior live qualification, docs/CUA-SPACES-QUALIFICATION-2026-10-02.md | Specify version and observed connection |
| All 106 KB necessarily enters the prompt | Unsupported | No client prompt/token trace | Say exposed metadata, not consumed tokens |
| spaces:all exposes 86 tools / 70,606 bytes | Verified | Real MCP permission probe, 2026-10-02 | State serialization and version |
| spaces:readonly exposes 28 tools / 17,686 bytes | Verified | Same probe; call_tool absent | Cannot execute Driver actions with this grant |
| Exact three-action grant exposes 3 tools / 3,085 bytes | Verified | Same probe: list_spaces, list_tools, call_tool | Existing Spaces only; lifecycle separate |
| Add create/delete: 5 tools / 9,549 bytes | Verified | Same probe | Opt-in lifecycle profile |
| Unprefixed list_spaces,list_tools,call_tool works | Incorrect | Warnings and zero registered tools | Prefix each with spaces: |
| Upstream supports filtered Driver schema discovery | Verified | Captured list_tools schema and previous browser-name discovery; official agent guide | Still measure cumulative discovery bytes |
| Narrow profile is faster/cheaper overall | Unsupported | No matched live profile comparison or model usage trace | Treat as next experiment |

**High-risk unresolved claims:** None asserted; execution authority is not inferred from surface size. **Expert review:** None needed for observed schema counts. **Source gaps:** Client prompt construction, total model usage, narrow-profile live execution. **Corrections:** Replace prompt-overhead certainty with potential overhead; distinguish disk usage/content size; avoid claims that OH opt-ins are proven better than native.

Official sources inspected: [MCP permissions](https://cua.ai/docs/cua-cli/guides/mcp-server) and [Spaces agent integration](https://cua.ai/docs/spaces/guides/use-from-an-agent). Local runnable evidence takes precedence over the agent guide's older count of 33 Spaces tools.

## Installation result

Claude and Codex MCP registrations already point at this checkout's Python server and are enabled. Refreshed installed skill copies in ~/.claude/skills, ~/.agents/skills and ~/.codex/skills from the reduced bundled skill; their SKILL.md hashes match. Protocol and call-budget checks passed: look/do only; capability-free calls return native_default; legacy advanced settings do not expose archived tools. Reconnect clients to load refreshed instructions. No Spaces MCP registration was added; the downloaded Spaces image remains retained.

## Execute — narrow profile installed and qualified

Installed separate cua-spaces registrations for Claude and Codex with the exact three-action grant, embedded mode, automatic cache GC disabled and telemetry disabled. Updated the bundled/installed computer-use guidance with the task-scoped discovery reference. Native remains default; no OH route or runtime policy changed. Independent review approved installation with concrete guest ownership, fresh bindings, filtered discovery and independent verification; those conditions are in the guide.

A live repeat of the same five-action form passed through the three-tool profile. Independent CLI receipt read matched recipient Birch, message Spaces smoke and manifest true. The successful scripted run exposed 3,085 initial metadata bytes, fetched six exact Driver schemas (16,488 response bytes), made 22 MCP calls, and received 45,840 total response bytes in 3.486 seconds. This measures harness execution without LLM deliberation, lifecycle setup or receipt CLI read; it is not an agent benchmark. Model token usage is unavailable because this harness has no model invocation. Initial plus discovery metadata is approximately 19.6 KB; discovery did not secretly reload the full catalog.

Two initial harness runs stopped on incorrect assumptions about Driver response shapes: list_windows has no status field; delivered browser_type can return effect=unverifiable. Neither acknowledgement counts as completion; fresh observations are the assertions. A subsequent attempt encountered a real CDP navigation timeout after 20 seconds. No uncertain input was replayed. Cleaning up Chromium processes inside this exclusively test-owned guest and starting a fresh run succeeded. This provenance prevents reporting unqualified general reliability.

Risk gate: broad catalog risk retired by real tools/list; unbounded discovery risk retired for this task by exact-name/count assertions and cumulative bytes; incorrect form execution risk retired by fresh UI checks and independent saved receipt. Faster/cheaper total agent execution remains unestablished: there was no matched controlling-model run, so no efficiency promotion is authorized. The timeout is a live reliability limitation, not hidden in successful-run timing. Broader authority behind call_tool remains an accepted limitation, explicitly described in the installed guide. No custom facade was built.

Call-budget/static checks and whitespace checks passed after the guidance change. Earlier protocol and 200 mutation checks passed; guidance did not alter runtime code. Deleted the disposable qualification Space, retained the downloaded image. Reconnect Claude/Codex to load the new registration and instructions.
