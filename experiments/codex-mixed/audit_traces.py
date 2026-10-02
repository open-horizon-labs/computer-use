"""Content-free call audit: statuses, stage timings, payload sizes and recovery.

Native inventories and screenshots remain in the local raw files. Response bytes
are a diagnostic, never a substitute for reported token usage.
"""
import argparse
from collections import Counter
import json
from pathlib import Path


def events(path):
    for line in path.read_text().splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def durations(path):
    starts, result = {}, {}
    if path is None or not path.exists():
        return result
    for event in events(path):
        key = (event.get("run_id"), event.get("item_id"))
        if event.get("event") == "item.started":
            starts[key] = event["observed_ns"]
        elif event.get("event") == "item.completed" and key in starts:
            result[key] = (event["observed_ns"] - starts.pop(key)) / 1e9
    return result


def permission_blocked(path):
    """Use the tool refusal, never an agent's unverified explanation."""
    for event in events(path):
        item = event.get('item', {})
        if event.get('type') != 'item.completed' or item.get('type') != 'mcp_tool_call':
            continue
        for part in (item.get('result') or {}).get('content', []):
            if part.get('type') == 'text' and 'Computer Use was not approved to use' in part.get('text', ''):
                return True
        if 'Computer Use was not approved to use' in str(item.get('error') or ''):
            return True
    return False


def target_inventory_blocked(path, name):
    """Qualify a missing fixture only from an actual lookup error plus inventory."""
    invalid, missing = False, False
    for event in events(path):
        item = event.get('item', {})
        if event.get('type') != 'item.completed' or item.get('type') != 'mcp_tool_call':
            continue
        for part in (item.get('result') or {}).get('content', []):
            if part.get('type') != 'text':
                continue
            text = part.get('text', '')
            invalid |= text.strip() == 'Invalid app: ' + name
            try:
                body = json.loads(text)
            except ValueError:
                continue
            if isinstance(body, dict) and isinstance(body.get('apps'), list):
                missing |= not any(app.get('displayName') == name for app in body['apps'])
    return invalid and missing


def calls(path, timing):
    rows = []
    for event in events(path):
        item = event.get("item", {})
        if event.get("type") != "item.completed" or item.get("type") != "mcp_tool_call":
            continue
        body = item.get("result") or {}
        result = {}
        for part in body.get("content", []):
            if part.get("type") == "text":
                try:
                    parsed = json.loads(part.get("text", ""))
                    if isinstance(parsed, dict):
                        result = parsed
                        break
                except ValueError:
                    pass
        exception = next((part.get('text', '') for part in body.get('content', [])
                          if part.get('type') == 'text' and part.get('text', '').startswith('Error executing tool ')), None)
        if not result and exception:
            result = {'status': 'tool_error', 'reason': 'missing_pid' if exception.strip() == "Error executing tool look: 'pid'" else 'tool_exception'}
        args = item.get("arguments") or {}
        if isinstance(args, str):
            args = json.loads(args)
        requested_steps = args.get("steps") or []
        steps = [{k: step[k] for k in ("do", "status", "reason", "ms", "delivery", "verification") if k in step}
                 for step in result.get("steps", []) if isinstance(step, dict)]
        stages = result.get("ms_by_stage") or (result.get("trace_summary") or {}).get("ms_by_stage") or {}
        row = {"item_id": item.get("id"), "tool": item.get("tool"), "server": item.get("server"),
               "observed_call_s": timing.get((path.stem, item.get("id"))),
               "response_bytes": len(json.dumps(body).encode()), "status": result.get("status"),
               "reason": result.get("reason"), "delivery": result.get("delivery"),
               "requested_step_kinds": [s.get("do") for s in requested_steps],
               "step_results": steps, "reported_ms_by_stage": stages,
               "mcp_error": bool(item.get("error") or body.get("isError") or exception)}
        # Terminal observations are already returned by do, including a reusable look_id.
        if "terminal" in args:
            row["terminal_request"] = True
            row["returned_fresh_look_id"] = bool(result.get("look_id"))
        rows.append(row)
    return rows


def audit(source, timing_file):
    timing = durations(timing_file)
    for metric in events(source / "metrics.jsonl"):
        path = source / (metric["run_id"] + ".jsonl")
        rows = calls(path, timing) if path.exists() else []
        measured = [r["observed_call_s"] for r in rows if r["observed_call_s"] is not None]
        reasons = Counter(r["reason"] for r in rows if r["reason"])
        yield {"run_id": metric["run_id"], "task": metric["task"], "arm": metric["arm"], "rep": metric["rep"],
               "timed_completed_mcp_calls": len(measured), "completed_mcp_calls": len(rows),
               "observed_mcp_s": round(sum(measured), 3) if measured else None,
               "response_bytes": sum(r["response_bytes"] for r in rows),
               "reasons": dict(reasons), "calls": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--timing", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text("".join(json.dumps(r) + "\n" for r in audit(args.source, args.timing)))
