"""Facade-vs-native A/B runner. OPERATES THE DESKTOP -- see README.md for the
required consent before running this.

For each (arm, task, run_id):
  1. Creates a dedicated Chrome window via AppleScript `make new window`
     (no `activate`), so Chrome is not brought forward and no user window
     gains a tab. Never `open <url>` (adds a tab to the user's front window)
     or `open -n` (spawns a second Chrome).
  2. Runs a headless `claude -p` agent restricted to exactly that arm's MCP
     server (config generated with absolute paths), with --strict-mcp-config,
     a neutral task prompt, and a pinned model.
  3. Closes only that window, by the id returned in step 1.

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

# Neutral user intent only: never name the answer or enumerate decoys, or the
# comparison measures prompt hints instead of the tools.
PROMPTS = {
    'booking': 'Book the earliest 30-minute appointment with Dr. Morgan Reyes that starts at or after 2:00 PM. Book exactly one appointment.',
    'orders': 'Cancel my walnut desk lamp order that has not shipped yet. Do not cancel or change any other order.',
}
PROMPT_FRAME = ('A Google Chrome window whose title begins with {title!r} is open on this Mac. {goal} '
                'Use only the computer-use tools available to you. Do not open, navigate, or act on any other '
                'window or tab. When finished, report exactly what you did and how you verified the result.')

TITLES = {'booking': 'Clinic Slots {run}', 'orders': 'Orders {run}'}

ALLOWED_TOOLS = {
    'facade': ['mcp__cua-task'],
    'native': ['mcp__cua-driver'],
}
DISALLOWED_TOOLS = {
    'facade': ['Bash', 'Edit', 'Write', 'WebFetch', 'WebSearch', 'Agent'],
    'native': ['Bash', 'Edit', 'Write', 'WebFetch', 'WebSearch', 'Agent', 'Skill'],
}


def chrome(script):
    return subprocess.run(['osascript', '-e', f'tell application "Google Chrome" to {script}'],
                          capture_output=True, text=True, check=True).stdout.strip()


def open_page(url):
    # A dedicated window, created without `activate`, so Chrome is not brought
    # forward and no existing user window gains a tab. `open -g <url>` would add
    # a tab to the user's front window, and `open -n` spawns a second Chrome.
    window_id = chrome('id of (make new window)')
    chrome(f'set URL of active tab of window id {window_id} to "{url}"')
    return window_id


def close_window(window_id):
    # Close only the window this run created, by id; never by title, which could
    # match a user window whose active tab happens to share it.
    subprocess.run(['osascript', '-e', f'tell application "Google Chrome" to close window id {window_id}'], check=False)


def mcp_config(arm, out_dir):
    root = HERE.parents[1]
    servers = {'facade': {'cua-task': {'command': str(root / '.venv-facade/bin/python'), 'args': [str(root / 'facade/server.py')]}},
               'native': {'cua-driver': {'command': str(Path.home() / '.local/bin/cua-driver'), 'args': ['mcp']}}}
    path = out_dir / f'mcp-config.{arm}.json'
    path.write_text(json.dumps({'mcpServers': servers[arm]}, indent=2))
    return path


def run_agent(arm, task, title, out_path, model):
    prompt = PROMPT_FRAME.format(title=title, goal=PROMPTS[task])
    cmd = ['claude', '-p', prompt, '--model', model, '--max-turns', '80',
           '--strict-mcp-config', '--mcp-config', str(mcp_config(arm, out_path.parent)),
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
    parser.add_argument('--model', default='claude-opus-5-5')
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
                window_id = open_page(url)
                time.sleep(1)  # let the tab actually load before the agent starts
                try:
                    outcome = run_agent(arm, task, title, transcript, args.model)
                finally:
                    close_window(window_id)
                manifest.append({'arm': arm, 'task': task, 'run_id': run_id,
                                  'title': title, 'transcript': str(transcript), **outcome})
    (out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(f'Wrote {len(manifest)} run(s) to {out_dir}. Ground truth: {args.events}')
    print('Score with: python3 score.py --events', args.events, '--manifest', out_dir / 'manifest.json')


if __name__ == '__main__':
    main()
