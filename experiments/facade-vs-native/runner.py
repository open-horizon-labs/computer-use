"""Facade-vs-native A/B runner. OPERATES THE DESKTOP -- see README.md for the
required consent before running this.

For each (arm, task, run_id):
  1. Opens the fixture page in the background with `open -g -a "Google Chrome"
     <url>` -- never without -g, never `open -n` (which would spawn a second
     Chrome process instead of a tab in the existing one).
  2. Runs a headless `claude -p` agent restricted to exactly that arm's MCP
     server, with --strict-mcp-config so no other server or Skill leaks in.
  3. Closes only the window it opened, by exact title, via
     `osascript -e 'tell application "Google Chrome" to close (every window
     whose name is "<title>")'` -- closing by title never activates/raises
     the app or any other window.

Nothing here ever activates, raises, or foregrounds a window; that mirrors
the facade's own "never move the user's windows" policy (fix 7).
"""
import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path

from fixtures import BOOKING_EXPECTED_ID, ORDERS_EXPECTED_ID

HERE = Path(__file__).resolve().parent

PROMPTS = {
    'booking': (
        'On the Clinic Slots page, book the appointment that is with Dr. Morgan Reyes, '
        'is a Telehealth visit, lasts half an hour, and starts at 3:00 PM. '
        'There is a similarly-named decoy slot at a different time and duration; '
        'do not book that one. Click Book only once, for the one matching slot.'
    ),
    'orders': (
        'On the Orders page, cancel the order that is a "Walnut desk lamp" (not a floor '
        'lamp, not brass, not the desk organizer, not the lamp shade replacement) and is '
        'still "Processing" (not Shipped and not Delivered). Click Cancel, then confirm '
        'the cancellation in the dialog that appears. Do not cancel or click on any other order.'
    ),
}

TITLES = {'booking': 'Clinic Slots {run}', 'orders': 'Orders {run}'}

ALLOWED_TOOLS = {
    'facade': ['mcp__cua-task__*'],
    'native': ['mcp__cua-driver__*'],
}
DISALLOWED_TOOLS = {
    'facade': ['Bash', 'Edit', 'Write', 'WebFetch', 'WebSearch', 'Agent'],
    'native': ['Bash', 'Edit', 'Write', 'WebFetch', 'WebSearch', 'Agent', 'Skill'],
}
MCP_CONFIG = {'facade': HERE / 'mcp-config.facade.json', 'native': HERE / 'mcp-config.native.json'}


def open_page(url):
    # -g: open in the background, never bring Chrome or the new tab forward.
    # Never -n: that spawns a second Chrome process instead of a new tab.
    subprocess.run(['open', '-g', '-a', 'Google Chrome', url], check=True)


def close_window(title):
    script = f'tell application "Google Chrome" to close (every window whose name is "{title}")'
    subprocess.run(['osascript', '-e', script], check=False)


def run_agent(arm, task, out_path):
    cmd = ['claude', '-p', PROMPTS[task],
           '--strict-mcp-config', '--mcp-config', str(MCP_CONFIG[arm]),
           '--allowedTools', ','.join(ALLOWED_TOOLS[arm]),
           '--disallowedTools', ','.join(DISALLOWED_TOOLS[arm]),
           '--output-format', 'stream-json', '--verbose']
    began = time.monotonic()
    with out_path.open('w') as out:
        result = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, timeout=600, cwd=str(HERE))
    return {'wall_s': time.monotonic() - began, 'returncode': result.returncode}


def wait_for_server(base_url, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(base_url + '/booking?run=healthcheck', timeout=1).read()
            return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f'fixture server not reachable at {base_url}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8934')
    parser.add_argument('--arms', nargs='+', default=['facade', 'native'], choices=['facade', 'native'])
    parser.add_argument('--tasks', nargs='+', default=['booking', 'orders'], choices=['booking', 'orders'])
    parser.add_argument('--runs', type=int, default=1, help='runs per (arm, task) pair')
    parser.add_argument('--out-dir', default=str(HERE / 'runs'))
    parser.add_argument('--events', default=str(HERE / 'events.jsonl'))
    parser.add_argument('--i-have-consent', action='store_true',
                         help='required: confirms the user consented to this session operating the desktop')
    args = parser.parse_args()
    if not args.i_have_consent:
        raise SystemExit('Refusing to run: pass --i-have-consent after getting the user\'s explicit '
                          'consent to operate their desktop/browser for this comparison (see README.md).')

    wait_for_server(args.base_url)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for arm in args.arms:
        for task in args.tasks:
            for run_index in range(args.runs):
                run_id = f'{arm}-{task}-{run_index}-{int(time.time())}'
                url = f'{args.base_url}/{task}?run={run_id}'
                title = TITLES[task].format(run=run_id)
                transcript = out_dir / f'{run_id}.jsonl'
                print(f'== {arm}/{task} run={run_id} ==')
                open_page(url)
                time.sleep(1)  # let the tab actually load before the agent starts
                try:
                    outcome = run_agent(arm, task, transcript)
                finally:
                    close_window(title)
                manifest.append({'arm': arm, 'task': task, 'run_id': run_id,
                                  'title': title, 'transcript': str(transcript), **outcome})
    (out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(f'Wrote {len(manifest)} run(s) to {out_dir}. Ground truth: {args.events}')
    print('Score with: python3 score.py --events', args.events, '--manifest', out_dir / 'manifest.json')


if __name__ == '__main__':
    main()
