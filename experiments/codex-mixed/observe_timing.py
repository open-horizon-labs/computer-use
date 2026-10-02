"""Content-free timestamp sidecar for an already-running JSONL benchmark.

Observations have polling uncertainty; pre-existing lines are deliberately not
backdated. This never reads tool arguments/results into the sidecar.
"""
import argparse
import json
import time
from pathlib import Path


def watch(folder, destination, interval=0.1):
    positions = {p: p.stat().st_size for p in folder.glob("*.jsonl")}
    pending = {}
    with destination.open("a") as output:
        output.write(json.dumps({"observer_started_ns": time.time_ns(), "poll_interval_s": interval,
                                 "skipped_existing_files": [p.name for p in positions]}) + "\n")
        output.flush()
        while True:
            for path in folder.glob("*.jsonl"):
                if path.name == "metrics.jsonl" or path == destination:
                    continue
                offset = positions.get(path, 0)
                if path.stat().st_size <= offset:
                    continue
                with path.open("rb") as source:
                    source.seek(offset)
                    data = source.read()
                    positions[path] = source.tell()
                lines = (pending.get(path, b"") + data).split(b"\n")
                pending[path] = lines.pop()
                now = time.time_ns()
                for line in lines:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    item = event.get("item", {})
                    output.write(json.dumps({"run_id": path.stem, "observed_ns": now,
                        "event": event.get("type"), "item_id": item.get("id"),
                        "item_type": item.get("type"), "tool": item.get("tool"),
                        "server": item.get("server")}) + "\n")
                output.flush()
            time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    watch(args.folder, args.destination)
