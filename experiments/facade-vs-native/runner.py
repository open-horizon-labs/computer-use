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

Isolated runs let the selected arm own its browser lifecycle. OBO runs
explicitly authorize foreground delivery to a dedicated fixture window.
"""
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from tasks import load_tasks

HERE = Path(__file__).resolve().parent
TASKS = load_tasks()

# Neutral user intent only (tasks.json `prompt`): never name the answer or enumerate decoys, or the
# comparison measures prompt hints instead of the tools.
PROMPT_FRAME = ('A Google Chrome window whose title begins with {title!r} is open on this Mac. {goal} '
                'Use only the computer-use tools available to you. Do not open, navigate, or act on any other '
                'window or tab. When finished, report exactly what you did and how you verified the result.')

# arm -> server family. `facade` is the legacy name for `stack`.
ARM_SERVER = {'native': 'cua-driver', 'native-skill': 'cua-driver', 'stack': 'computer-use-oh', 'stack-advanced': 'computer-use-oh', 'stack-agent': 'computer-use-oh', 'facade': 'computer-use-oh'}
ARMS = list(ARM_SERVER)
ALLOWED_TOOLS = {arm: ['mcp__' + server] + (['Skill'] if arm == 'native-skill' else []) for arm, server in ARM_SERVER.items()}
# Exploratory arm (option D, PR 17): ONLY the experimental server-side agent tool is allowed, so the driving LLM cannot fall back to do.
ALLOWED_TOOLS['stack-agent'] = ['mcp__computer-use-oh__agent']
# Tool-choice hint per arm: it names the toolset the arm is defined by, never the answer or a decoy (the prompt lint checks this).
ARM_HINT = {'stack-agent': ' Use the agent tool: state the goal, and in `expect` the text that will appear on the page when it has succeeded.'}
# File and shell tools are off for every arm: an agent that can Read would load repo
# context and stop being a clean tool-set comparison. Native additionally has no Skill (unless the
# `native-skill` arm), since the installed skill would reintroduce facade guidance.
_BASE_DENY = ['Bash', 'Edit', 'Write', 'NotebookEdit', 'Read', 'Glob', 'Grep', 'WebFetch', 'WebSearch', 'Agent', 'Task']
DISALLOWED_TOOLS = {arm: _BASE_DENY + ([] if arm in ('native-skill',) or ARM_SERVER[arm] == 'computer-use-oh' else ['Skill'])
                    for arm in ARM_SERVER}


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
    py = os.environ.get('CUA_FACADE_PYTHON') or str(root / '.venv-facade/bin/python')
    stack = {'command': py, 'args': [str(root / 'computer_use/server.py')]}
    if arm == 'stack-advanced':
        stack['env'] = {'CUA_TASK_ADVANCED': '1'}
    if arm == 'stack-agent':
        stack['env'] = {'CUA_TASK_EXPERIMENTAL_AGENT': '1'}
    servers = {'computer-use-oh': stack, 'cua-driver': {'command': str(Path.home() / '.local/bin/cua-driver'), 'args': ['mcp']}}
    server = ARM_SERVER[arm]
    path = Path(out_dir).resolve() / f'mcp-config.{arm}.json'  # absolute: the agent runs from a scratch cwd
    path.write_text(json.dumps({'mcpServers': {server: servers[server]}}, indent=2))
    return path



def runtime_digest():
    """Content identity of runtime sources; never inspect user configs or secrets."""
    root=HERE.parents[1]
    digest=hashlib.sha256()
    for path in sorted((root/'computer_use').glob('*.py')):
        digest.update(path.name.encode());digest.update(path.read_bytes())
    return digest.hexdigest()

def run_agent(arm, task, title, out_path, model, max_turns=80, timeout=600, session_mode=None, url=None, client='claude'):
    prompt = PROMPT_FRAME.format(title=title, goal=TASKS[task]['prompt']) + ARM_HINT.get(arm, '')
    if session_mode == 'obo':
        prompt += ' This is delegated work in my existing Chrome session. Use context={"session":"user"} on your first facade call and resume its context thereafter. Foreground delivery is authorized for this fixture.' if ARM_SERVER[arm] == 'computer-use-oh' else ' This is delegated work in my existing Chrome session. Foreground delivery is authorized for this fixture.'
    elif session_mode == 'isolated':
        prompt = ('Open the fixture URL ' + str(url) + ' in your own isolated browser, then ' + TASKS[task]['prompt'] + ' Use only this fixture and computer-use tools. Verify the visible result independently. ')
        prompt += 'Use context={"session":"isolated"} on your first facade call, then resume its context.' if ARM_SERVER[arm] == 'computer-use-oh' else 'Use browser_prepare with an isolated_new profile and allow_launch=true. Do not attach to the user browser.'
    cmd = ['claude', '-p', prompt, '--model', model, '--max-turns', str(max_turns),
           '--strict-mcp-config', '--mcp-config', str(mcp_config(arm, out_path.parent)),
           '--allowedTools', ','.join(ALLOWED_TOOLS[arm]),
           '--disallowedTools', ','.join(DISALLOWED_TOOLS[arm]),
           '--tools', 'Skill' if arm == 'native-skill' else '', '--output-format', 'stream-json', '--verbose']
    if client == 'codex':
        config = json.loads(mcp_config(arm, out_path.parent).read_text())['mcpServers']
        cmd = ['codex', 'exec', '--ignore-user-config', '--skip-git-repo-check', '--ephemeral', '--json']
        if model != 'codex-default':cmd += ['--model', model]
        for name, spec in config.items():
            for key, value in spec.items():
                cmd += ['-c', 'mcp_servers.' + name + '.' + key + '=' + json.dumps(value)]
        # The user authorized these fixture operations; approve this arm's tools only.
        for name in config:
            cmd += ['-c', 'mcp_servers.' + name + '.default_tools_approval_mode="approve"']
        cmd += [prompt + ' Do not use shell, file, web, or other tools; use only the configured MCP server.']
    source_digest=runtime_digest()
    began = time.monotonic()
    with out_path.open('w') as out:
        try:
            result = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, timeout=timeout, cwd=tempfile.mkdtemp(prefix='cua-ab-'))  # outside the repo: no AGENTS.md/memory contamination
        except subprocess.TimeoutExpired:
            return {'wall_s': time.monotonic() - began, 'returncode': 'timeout'}
    # A successful CLI exit does not prove the configured tool server connected.
    # Classify a missing arm server as launcher infrastructure failure, before scoring task accuracy.
    if client == 'codex':
        return {'wall_s': time.monotonic() - began, 'returncode': result.returncode, 'client':client, 'session_mode':session_mode, 'runtime_digest':source_digest}
    expected_server = ARM_SERVER[arm]
    init = None
    for line in out_path.read_text().splitlines():
        try:row = json.loads(line)
        except json.JSONDecodeError:continue
        if isinstance(row,dict) and row.get('subtype') == 'init':
            init = row
            break
    connected = init is not None and any(x.get('name') == expected_server and x.get('status') == 'connected' for x in init.get('mcp_servers', []))
    return {'wall_s': time.monotonic() - began, 'returncode': result.returncode if connected else 'mcp-unavailable',
            'mcp_connected': connected, 'session_mode': session_mode, 'runtime_digest':source_digest}


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
    parser.add_argument('--arms', nargs='+', default=['stack', 'native'], choices=ARMS)
    parser.add_argument('--tasks', nargs='+', default=['booking', 'orders'], choices=list(TASKS))
    parser.add_argument('--model', default='claude-opus-5-5')
    parser.add_argument('--max-turns', type=int, default=80)
    parser.add_argument('--agent-timeout', type=int, default=600, help='seconds per run')
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
                url = f'{args.base_url}{TASKS[task]["route"]}?run={run_id}'
                title = TASKS[task]['title'].format(run=run_id)
                transcript = out_dir / f'{run_id}.jsonl'
                print(f'== {arm}/{task} run={run_id} ==')
                window_id = open_page(url)
                time.sleep(1)  # let the tab actually load before the agent starts
                try:
                    outcome = run_agent(arm, task, title, transcript, args.model, args.max_turns, args.agent_timeout)
                finally:
                    close_window(window_id)
                manifest.append({'arm': arm, 'task': task, 'run_id': run_id,
                                  'title': title, 'transcript': str(transcript), **outcome})
    (out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(f'Wrote {len(manifest)} run(s) to {out_dir}. Ground truth: {args.events}')
    print('Score with: python3 score.py --events', args.events, '--manifest', out_dir / 'manifest.json')


if __name__ == '__main__':
    main()
