"""Cua Driver terminal observations: pixels and AX are independent evidence.

No application actions are executed here. The caller builds stored bindings and
uses execute_bound, then observes again to check its declared postcondition.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from worker_transport import JsonWorker
from runtime_config import load_runtime_config


def observe_terminal(pid, window_id, *, session, timeout=5, previous=None,
                     driver='cua-driver'):
    began = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='cua-terminal-') as directory:
        path = Path(directory) / 'snapshot.png'
        args = {'pid': pid, 'window_id': window_id, 'session': session,
                'max_elements': 15000, 'screenshot_out_file': str(path)}
        result = subprocess.run([driver, 'call', 'get_window_state', '--json', json.dumps(args)],
                                capture_output=True, text=True, timeout=timeout, check=True)
        snapshot = json.loads(result.stdout)
        if not snapshot.get('snapshot_id'):
            raise ValueError('Driver returned no snapshot identity')
        pixels = path.read_bytes() if path.is_file() else b''
    tree = snapshot.get('tree_markdown') or ''
    digest = hashlib.sha256(pixels).hexdigest() if pixels else None
    old = (previous or {}).get('observation_quality', {})
    quality = {
        'ax_text_available': bool(tree.strip()),
        'terminal_text_coverage': 'unknown',
        'ax_changed': None if previous is None else tree != previous.get('tree_markdown', ''),
        'screenshot_available': bool(pixels),
        'screenshot_sha256': digest,
        # Encoded image changes are evidence only; cursor blink can change pixels.
        'screenshot_changed': None if not digest or not old.get('screenshot_sha256') else
                              digest != old['screenshot_sha256'],
        'requires_visual_interpretation': True,
        'progress': 'unknown',
    }
    return {**snapshot, 'observation_quality': quality,
            'screenshot_data_url': 'data:image/png;base64,' + base64.b64encode(pixels).decode() if pixels else None,
            'driver_ms': (time.monotonic() - began) * 1000}


class VisualTerminal:
    """Screenshot-capable worker; must not be backed by text-only Julia/Jev."""
    def __init__(self, command=None):
        load_runtime_config()
        self.worker = JsonWorker(command if command is not None else
                                 json.loads(os.environ.get('CUA_VISUAL_COMMAND', '[]')))

    def inspect(self, snapshot, postcondition, timeout):
        if not snapshot.get('screenshot_data_url'):
            return {'state': 'unknown', 'reason': 'screenshot_unavailable'}
        result = self.worker.exchange({'method': 'inspect', 'snapshot_id': snapshot['snapshot_id'],
            'image': snapshot['screenshot_data_url'], 'ax_text': snapshot.get('tree_markdown', ''),
            'postcondition': postcondition}, timeout)
        if result.get('snapshot_id') != snapshot['snapshot_id'] or result.get('state') not in ('ready', 'waiting', 'unknown'):
            raise ValueError('invalid visual inspection response')
        if result['state'] == 'ready' and not (isinstance(result.get('evidence'), str) and result['evidence'].strip()):
            raise ValueError('ready assessment requires visible supporting evidence')
        return result

    def __call__(self, step, request):
        if step['method'] != 'choose' or not request.get('screenshot_data_url'):
            raise ValueError('visual choice requires current screenshot and offered actions')
        candidates = {a['id']: a.get('description', a.get('name', '')) for a in request['actions']}
        if len(candidates) != len(request['actions']) or set(candidates) & {'abstain', 'reobserve'}:
            raise ValueError('duplicate or reserved action ID')
        candidates.update(abstain='No supported action', reobserve='Need more evidence')
        result = self.worker.exchange({'method': 'choose', 'snapshot_id': request['snapshot_id'],
            'image': request['screenshot_data_url'], 'goal': request.get('goal', ''),
            'ax_text': request.get('observation', ''), 'candidates': candidates,
            'constraints': {k: request[k] for k in ('fields', 'predicates', 'order_by', 'candidate_ids',
                'coverage_complete', 'fallback_id', 'specialist_context', 'history', 'feedback') if k in request}}, 20)
        if result.get('snapshot_id') != request['snapshot_id'] or result.get('choice') not in candidates:
            raise ValueError('unbound or unoffered visual choice')
        return {**result, 'route': 'visual', 'calibrated': False, 'requires_verification': True,
                'action_authorized': result['choice'] not in ('abstain', 'reobserve')}

    def close(self):
        self.worker.close()


def wait_for_terminal(pid, window_id, *, session, postcondition, visual,
                      budget=20, driver='cua-driver'):
    """Observe AND interpret immediately; reserve time for a final inspection.

    Budget covers Driver, model calls and sleeps together, not each poll. No
    automatic retries or Ctrl+C. Expiration is uncertainty, not an app failure.
    A caller can retry once after reconciling state, with a new invocation.
    """
    if not 0 < budget <= 20:
        raise ValueError('terminal budget must be in (0, 20] seconds')
    began = time.monotonic()
    # Leave a small allowance for transport teardown after a timeout.
    deadline = began + max(0.01, budget - 0.25)
    final_reserve = min(5, budget / 2)
    previous = None
    records = []
    final = False
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        final = remaining <= final_reserve + 0.1
        end = deadline if final else deadline - final_reserve
        if end - time.monotonic() < 0.1:
            continue
        try:
            snapshot = observe_terminal(pid, window_id, session=session,
                timeout=max(0.01, min(2, (end-time.monotonic()) / 2)), previous=previous, driver=driver)
            previous = snapshot
            model_start = time.monotonic()
            verdict = visual.inspect(snapshot, postcondition, max(0.01, end-time.monotonic()))
            records.append({'snapshot_id': snapshot['snapshot_id'], 'quality': snapshot['observation_quality'],
                            'driver_ms': snapshot['driver_ms'], 'visual_ms': (time.monotonic()-model_start)*1000,
                            'final_inspection': final, 'verdict': verdict})
            if verdict['state'] == 'ready':
                return {'status': 'observed', 'snapshot': snapshot, 'inspection': verdict,
                        'records': records, 'wall_ms': (time.monotonic()-began)*1000}
        except (TimeoutError, subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError, RuntimeError, OSError) as error:
            records.append({'error': type(error).__name__, 'final_inspection': final})
            # Failed perception cannot establish a stall. Do not retry a poisoned
            # worker or silently spend a second model attempt.
            break
        if final:
            break
        time.sleep(max(0, min(1, deadline-final_reserve-time.monotonic())))
    return {'status': 'unknown', 'reason': 'terminal_postcondition_not_established',
            'snapshot': previous, 'records': records, 'wall_ms': (time.monotonic()-began)*1000}
