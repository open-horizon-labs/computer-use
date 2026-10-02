"""Preserve native iOS ancestry lost by mobile-mcp's flat element formatter.

Only observed children supply activation references; geometry is never used to
invent a child. Provider configuration is a literal JSON argv array.
"""
import json
import os
import subprocess


def read(device, run=subprocess.run):
    from mobile import MobileGap, AGENT_PACKAGE, CALL_TIMEOUT_S
    try:
        prefix = json.loads(os.environ['CUA_MOBILECLI_COMMAND']) if os.environ.get('CUA_MOBILECLI_COMMAND') else ['npx', '-y', AGENT_PACKAGE]
        if not isinstance(prefix, list) or not prefix or not all(isinstance(x, str) and x for x in prefix):
            raise ValueError()
        done = run(prefix + ['dump', 'ui', '--device', device], capture_output=True, text=True,
                   stdin=subprocess.DEVNULL, timeout=CALL_TIMEOUT_S,
                   env={**os.environ, 'MOBILEMCP_DISABLE_TELEMETRY': '1'})
        if done.returncode or len(done.stdout) > 4_000_000:
            raise ValueError()
        payload = json.loads(done.stdout)
        if payload.get('status') != 'ok' or not isinstance(payload.get('data', {}).get('elements'), list):
            raise ValueError()
        return payload['data']['elements']
    except (OSError, ValueError, TypeError, AttributeError, RecursionError, subprocess.TimeoutExpired):
        raise MobileGap('mobile_hierarchy_unavailable', 'the native iOS hierarchy could not be read; no switch activation was inferred')


def normalize_tree(roots):
    from collections import Counter
    import math
    from mobile import normalize, toggle_state, MobileGap
    counts = Counter()
    nodes = 0
    def validate(items, depth=0):
        nonlocal nodes
        if not isinstance(items, list) or depth > 64:
            raise MobileGap('mobile_hierarchy_unavailable', 'the native hierarchy has an invalid or excessively deep child list; nothing was inferred')
        for node in items:
            nodes += 1
            if not isinstance(node, dict) or nodes > 20000:
                raise MobileGap('mobile_hierarchy_unavailable', 'the native hierarchy has invalid or excessive nodes; nothing was inferred')
            ref = node.get('ref')
            if isinstance(ref, str) and ref:
                counts[ref] += 1
            box = node.get('rect', {})
            if isinstance(box, dict) and any(isinstance(v, float) and not math.isfinite(v) for v in box.values()):
                raise MobileGap('mobile_hierarchy_unavailable', 'the native hierarchy has nonfinite bounds; nothing was inferred')
            validate(node.get('children', []), depth + 1)
    validate(roots)
    out = []
    def visit(node):
        if not isinstance(node, dict):
            return
        try:
            e = normalize({**node, 'coordinates': node.get('rect', {})}, len(out))
        except (ValueError, TypeError, OverflowError):
            raise MobileGap('mobile_hierarchy_unavailable', 'the native hierarchy has invalid element bounds; nothing was inferred')
        out.append(e)
        children = node.get('children') or []
        if e['kind'] == 'Switch' and e['names'] and e['bounds'][2] > 3 * e['bounds'][3]:
            candidates = [normalize({**c, 'coordinates': c.get('rect', {})}, 0) for c in children
                          if isinstance(c, dict) and c.get('type') in ('Switch', 'XCUIElementTypeSwitch')]
            valid = len(candidates) == 1
            if valid:
                child = candidates[0]
                valid = (bool(child['ref']) and counts[child['ref']] == 1 and child['ref'] != e['ref']
                         and child['bounds'][2] > 0 and child['bounds'][3] > 0 and child['enabled']
                         and (not child['names'] or child['names'] == e['names'])
                         and toggle_state(e) is not None and toggle_state(child) == toggle_state(e))
            if valid:
                e['activation'] = {'ref': child['ref'], 'bounds': child['bounds'], 'parent_ref': e['ref']}
            else:
                e['activation_refusal'] = 'switch_activation_ambiguous'
        for child in children:
            visit(child)
    for root in roots:
        visit(root)
    return out
