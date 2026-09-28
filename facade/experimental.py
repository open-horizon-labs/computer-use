"""Experimental tools, registered only behind CUA_TASK_EXPERIMENTAL_AGENT=1 (see docs/AGENT-D.md). Never in the default surface."""
import os

FLAG = 'CUA_TASK_EXPERIMENTAL_AGENT'


def enabled():
    return os.environ.get(FLAG) == '1'


def register(mcp, facade):
    """`facade` may be a Facade or a zero-argument callable returning the current one."""
    from mcp.types import ToolAnnotations
    get = facade if callable(facade) else (lambda: facade)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True))
    def cua_agent(goal: str, title: str, expect: str, text: str | None = None, confirm: str | None = None,
                  max_steps: int = 8, budget_s: float = 60) -> dict:
        """Experimental (option D, off by default). A fast server-side agent runs the WHOLE multi-step loop (observe, candidates, fast-model choice, bound click, progress check) and returns done, or escalated with evidence and no further clicks. State the goal in criteria (never element IDs), the exact window title, and expect: text that is ABSENT before and must appear in exactly one element when the goal is met. confirm is the exact label of a dialog control it may press once. Returns status done|escalated|failed with steps, evidence, escalation {reason, hint, observation} and cost."""
        f = get()
        return f.agent_run(goal, title, expect, text, confirm, max_steps, budget_s)

    return cua_agent
