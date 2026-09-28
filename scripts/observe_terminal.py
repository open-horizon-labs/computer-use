"""Read a terminal through Cua Driver and a configured visual worker; never act."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'inference/cua-decider/capability-dispatch'))
from terminal_observation import VisualTerminal, wait_for_terminal

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--pid', type=int, required=True)
parser.add_argument('--window-id', type=int, required=True)
parser.add_argument('--session', required=True)
parser.add_argument('--postcondition', required=True)
parser.add_argument('--budget', type=float, default=20)
parser.add_argument('--driver', default='cua-driver')
args = parser.parse_args()
vision = VisualTerminal()
try:
    outcome = wait_for_terminal(args.pid, args.window_id, session=args.session,
        postcondition=args.postcondition, visual=vision, budget=args.budget, driver=args.driver)
    # Avoid dumping screenshot/base64 or the whole AX tree into a console log.
    snapshot = outcome.pop('snapshot', None)
    outcome['snapshot_id'] = snapshot.get('snapshot_id') if snapshot else None
    print(json.dumps(outcome))
finally:
    vision.close()
