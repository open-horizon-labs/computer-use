"""Start an isolated loopback fixture, run the real Driver, verify HTTP state."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.request import urlopen
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    root = Path(os.environ["CUA_JEV_USE_DIR"]).resolve()
    sys.path.insert(0, str(root))
    from fixture_server import FixtureServer

    token = "decider-" + uuid.uuid4().hex[:12]
    server = FixtureServer(("127.0.0.1", 0))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}"
    summary = {
        "complete": False,
        "token": token,
        "provider": os.environ.get("DECIDER_URL", "http://192.168.1.104:8010"),
    }
    try:
        with urlopen(
            summary["provider"].rstrip("/") + "/health", timeout=10
        ) as response:
            health = json.load(response)
        if health.get("ok") is not True:
            raise RuntimeError("Decider is not ready")
        summary["health"] = health
        command = [
            sys.executable,
            str(Path(__file__).with_name("run_fixture.py")),
            "--fixture-url",
            url,
            "--token",
            token,
            "--log",
            str(args.output_dir / "events.jsonl"),
        ]
        with (args.output_dir / "runner.log").open("w") as log:
            result = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT, timeout=args.timeout
            )
        with urlopen(url + "/state", timeout=5) as response:
            state = json.load(response)
        events_path = args.output_dir / "events.jsonl"
        events = (
            [json.loads(s) for s in events_path.read_text().splitlines()]
            if events_path.exists()
            else []
        )
        summary.update(returncode=result.returncode, state=state)
        summary["complete"] = (
            result.returncode == 0
            and state.get("submitted") == token
            and any(e.get("outcome") == "verified" for e in events)
        )
    except Exception as exc:
        summary["error"] = str(exc)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        (args.output_dir / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )
    print(json.dumps(summary, indent=2))
    return 0 if summary["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
