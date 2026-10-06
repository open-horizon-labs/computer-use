"""Owned-window menu qualification; never creates a virtual display.

ARC_EVAL_SOURCE supplies the evaluated arc benchmarks. CUA_MENU_SETUP_DRIVER
selects the native setup client. ARC_MENU_OUTPUT overrides the JSON destination.
Only synthetic role counts are saved; run in an arc/PyObjC Python environment.
"""
import json
import os
import sys
import threading
import time
from contextlib import ExitStack
from pathlib import Path

import run
from run import Fixture, MCP, wait_for, windows

run.HERE = Path(__file__).resolve().parent / 'menu-fixture'
PHASES = ('baseline', 'commands', 'between', 'run_command', 'after')
ROLES = ('target', 'sentinel', 'other')


def trial(repetition):
    with ExitStack() as owned:
        target = Fixture()
        owned.callback(target.close)
        sentinel = Fixture()
        owned.callback(sentinel.close)
        client = MCP([sys.executable, '-m', 'arc_cua', 'mcp'], 'arc')
        owned.callback(client.close)
        setup = MCP([os.environ.get('CUA_MENU_SETUP_DRIVER', 'cua-driver'),
                     'mcp', '--direct'], 'native')
        try:
            window = wait_for(lambda: windows(sentinel.pid).get('Arc Bench Form'))
            response, error = setup.call('bring_to_front', pid=sentinel.pid, window_id=window)
            assert not error, response
        finally:
            setup.close()
        wait_for(lambda: sentinel.state().get('active'))
        time.sleep(.5)
        stop = threading.Event()
        samples = []
        phase = ['baseline']

        def watch():
            while not stop.wait(.001):
                role = ('target' if target.state().get('active') else
                        'sentinel' if sentinel.state().get('active') else 'other')
                samples.append((phase[0], role))

        thread = threading.Thread(target=watch)
        thread.start()
        try:
            time.sleep(.3)
            phase[0] = 'commands'
            commands, error = client.call('commands', pid=target.pid, query='Bench > Increment')
            assert not error, commands
            phase[0] = 'between'
            time.sleep(.3)
            before_activations = target.state()['activation_count']
            phase[0] = 'run_command'
            response, error = client.call('run_command', pid=target.pid,
                                          path='Bench > Increment', settle=True)
            assert not error, response
            wait_for(lambda: target.state().get('counter') == 1)
            phase[0] = 'after'
            time.sleep(.5)
            return {
                'rep': repetition, 'status': response.get('status'),
                'counter': target.state().get('counter'),
                'activation_notifications': target.state()['activation_count'] - before_activations,
                'front_at_end': 'sentinel' if sentinel.state().get('active') else 'other',
                'samples_by_phase': {
                    name: {role: sum(p == name and r == role for p, r in samples) for role in ROLES}
                    for name in PHASES
                },
            }
        finally:
            stop.set()
            thread.join(timeout=2)
            if thread.is_alive():
                raise RuntimeError('synthetic sampler did not stop')


if __name__ == '__main__':
    results = [trial(repetition) for repetition in range(5)]
    output = Path(os.environ.get('ARC_MENU_OUTPUT', '/tmp/arc-menu-controlled.json'))
    output.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
