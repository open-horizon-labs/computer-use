"""Export only synthetic task metrics, never native app/browser inventories."""
import argparse
import hashlib
import json
import re
import statistics
from pathlib import Path

import runner
import audit_traces

TASKS = ("terminal", "web", "vnc", "android", "ios", "mac", "mixed")


def clean(text):
    text = text.replace(str(runner.ROOT), "<repo>")
    return re.sub(r"/var/folders/[^\s\"']*/cua-mixed-task-[^/\s\"']+", "<task-workspace>", text)


def export(source):
    rows = []
    for line in (source / "metrics.jsonl").read_text().splitlines():
        row = json.loads(line)
        row.setdefault("oracle_outcome", row["outcome"])
        raw = source / (row["run_id"] + ".jsonl")
        command = None
        if "executable/argv " in row.get("prompt", ""):
            command = json.JSONDecoder().raw_decode(row["prompt"].split("executable/argv ", 1)[1])[0]
        if raw.exists():
            trace = runner.parse(raw, row["arm"], row["task"], command)
            row.update(runner.call_metrics(trace["calls"], row["arm"], row["task"]))
            row.update(runner.usage_metrics(trace["usage"]))
            row["violations"] = trace["violations"]
            if trace["violations"]:
                row["outcome"] = "protocol-violation"
            row['permission_blocked'] = audit_traces.permission_blocked(raw)
            if row['permission_blocked'] and row['outcome'] not in ('correct', 'protocol-violation'):
                row['outcome'] = 'permission-blocked'
            row['target_inventory_blocked'] = (row['arm'] == 'native' and row['task'] == 'mac'
                                               and audit_traces.target_inventory_blocked(raw, 'OH Benchmark'))
            if row['target_inventory_blocked'] and row['outcome'] not in ('correct', 'protocol-violation'):
                row['outcome'] = 'infrastructure-blocked'
            row["raw_sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
        # Only metric rows, controlled fixture evidence and the agent's final text.
        # Raw MCP responses (which can contain unrelated user inventory) never leave /tmp.
        rows.append(json.loads(clean(json.dumps(row))))
    return rows


def median(rows, field):
    values = [r[field] for r in rows if r.get(field) is not None]
    return statistics.median(values) if values else None


def table(rows):
    lines = ["| Task | Arm | Valid completion | All-attempt median wall (s) | Permission/setup blocks | Usage rows | All-attempt median input | All-attempt median cached input | All-attempt median output |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for task in TASKS:
        for arm in ("native", "oh"):
            cell = [r for r in rows if r["task"] == task and r["arm"] == arm]
            if not cell:
                continue
            measured = [r["usage"] for r in cell if r.get("usage")]
            def number(value):
                return "unavailable" if value is None else f"{value:,.0f}"
            wall = median(cell, "wall_s")
            lines.append("| " + " | ".join([
                task, arm, f"{sum(r['outcome'] == 'correct' for r in cell)}/{len(cell)}",
                "unavailable" if wall is None else f"{wall:.1f}", str(sum(r["outcome"] in ("permission-blocked", "infrastructure-blocked") for r in cell)), f"{len(measured)}/{len(cell)}",
                *[number(median(measured, f)) for f in ("input_tokens", "cached_input_tokens", "output_tokens")],
            ]) + " |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = export(args.source)
    args.output.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(table(rows))
