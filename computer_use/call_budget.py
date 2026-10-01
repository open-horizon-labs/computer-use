"""Call-budget guardrails: the default path is look, then do (look, do): two tools and a measured, ceilinged number of LLM-visible calls (computer_use/CALL_BUDGET.json).

Measures the REAL server tool functions through a counting harness on fake fixtures (no Driver, model,
desktop or network), and lints the tool surface and the skill's default workflow. Shared by
computer_use/test_budget.py and scripts/check_call_budget.py.
"""
import ast
import asyncio
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
BUDGET = HERE / 'CALL_BUDGET.json'
RESPONSE_BUDGET = HERE / 'RESPONSE_BUDGET.json'
RESPONSE_CE = 'CE-FACADE-011'
HEADROOM = 1.1  # a ceiling is the measured number x 1.1, rounded up
CES = ROOT / 'inference/cua-decider/capability-dispatch/COUNTEREXAMPLES.json'
SKILL = ROOT / 'skills/computer-use/SKILL.md'
SERVER = HERE / 'server.py'
# Tool names in prose are the backticked bare names (`look`, `do`, `observe`, ...): the MCP tools have no prefix since #53.
TOOL_NAME_IN_TEXT = r'`(look|do|windows|observe|read|choose|act|verify|trace|finish|agent)`'
PRIMITIVE_CHAIN = ('observe', 'read', 'choose', 'act', 'verify')


def load_budget():
    return json.loads(BUDGET.read_text())


def load_response_budget():
    return json.loads(RESPONSE_BUDGET.read_text())


def response_budget_violations(budget=None, ces=None):
    """The same provenance rule as the call numbers: every ceiling names a CE that records the same number under response_budget."""
    return budget_violations(budget or load_response_budget(), ces, key='response_budget')


def ceiling(measured):
    import math
    return math.ceil(round(measured * HEADROOM, 6))


def response_budget_from(measured, listing, previous=None):
    """The ceilings for a measured run: bytes and waits x HEADROOM rounded up; every leaf names RESPONSE_CE. Used to (re)generate RESPONSE_BUDGET.json
    and the matching CE record: `python computer_use/call_budget.py --write-response-budget`. Existing text fields are kept."""
    out = {k: v for k, v in (previous or {}).items() if k in ('purpose',)}
    leaf = lambda value: {'value': value, 'changed_by': RESPONSE_CE}
    out['tools_list'] = {'instructions': leaf(ceiling(listing['instructions']))}
    for name, sizes in listing['tools'].items():
        out['tools_list'][name + '_description'] = leaf(ceiling(sizes['description']))
        out['tools_list'][name + '_schema'] = leaf(ceiling(sizes['schema']))
    out['scenarios'] = {name: {'max_total_bytes': leaf(ceiling(m['total_bytes'])), 'max_call_bytes': leaf(ceiling(m['max_bytes'])), 'max_wait_s': leaf(ceiling(m['wait_s']) if m['wait_s'] else 0)}
                        for name, m in measured.items()}
    return out


def response_violations(budget, measured, listing):
    """Problems of a measured run against RESPONSE_BUDGET.json: a scenario over a ceiling, a scenario with none, the tools/list over its ceiling."""
    problems = []
    for name, m in measured.items():
        limits = budget['scenarios'].get(name)
        if limits is None:problems.append('%s: no response ceiling in RESPONSE_BUDGET.json' % name);continue
        for field, label in (('total_bytes', 'max_total_bytes'), ('max_bytes', 'max_call_bytes'), ('wait_s', 'max_wait_s')):
            if m[field] > limits[label]['value']:problems.append('%s: %s %s > %s %s' % (name, field, m[field], label, limits[label]['value']))
    tools = budget['tools_list']
    if listing['instructions'] > tools['instructions']['value']:problems.append('tools_list: instructions %d > %d' % (listing['instructions'], tools['instructions']['value']))
    for name, sizes in listing['tools'].items():
        for field in ('description', 'schema'):
            limit = tools.get('%s_%s' % (name, field))
            if limit is None or sizes[field] > limit['value']:problems.append('tools_list: %s %s %d > %s' % (name, field, sizes[field], limit and limit['value']))
    return problems


def leaves(node, path=()):
    """Yield (path, leaf-dict) for every {value, changed_by} in the budget."""
    if isinstance(node, dict) and 'value' in node:
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from leaves(value, path + (key,))


def budget_violations(budget=None, ces=None, key='call_budget'):
    """Every number needs a CE id, the CE must exist, and its recorded call_budget (response_budget for RESPONSE_BUDGET.json) must equal the number."""
    budget = budget or load_budget()
    ces = ces if ces is not None else json.loads(CES.read_text())
    by_id = {ce['id']: ce for ce in ces}
    out = []
    for path, leaf in leaves(budget):
        name = '.'.join(path)
        ce = by_id.get(leaf.get('changed_by'))
        if not ce:out.append('%s: changed_by %r names no CE in COUNTEREXAMPLES.json' % (name, leaf.get('changed_by')));continue
        recorded = ce.get(key, {}).get(name)
        if recorded != leaf['value']:out.append('%s: value %r differs from %s call_budget %r' % (name, leaf['value'], ce['id'], recorded))
    return out


def tool_surface(source):
    """[(name, docstring, nested)] of every @mcp.tool function in server.py in registration order; nested is True when it is
    defined inside register_advanced() (registered only when CUA_TASK_ADVANCED=1)."""
    tree = ast.parse(source)
    nested = {n.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef) and fn.name == 'register_advanced' for n in ast.walk(fn) if n is not fn and isinstance(n, ast.FunctionDef)}
    return [(n.name, ast.get_docstring(n) or '', n.name in nested) for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and any('tool' in ast.dump(d) for d in n.decorator_list)]


def guard_present(source):
    """register_advanced() is called only under `if ADVANCED:` and ADVANCED reads CUA_TASK_ADVANCED."""
    tree = ast.parse(source)
    flag = any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'ADVANCED' for t in n.targets) and 'CUA_TASK_ADVANCED' in ast.dump(n) for n in tree.body)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'register_advanced']
    guarded = [n for n in tree.body if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == 'ADVANCED'
               and any(isinstance(x, ast.Expr) and isinstance(x.value, ast.Call) and getattr(x.value.func, 'id', '') == 'register_advanced' for x in n.body)]
    return flag and len(calls) == 1 and len(guarded) == 1


def surface_violations(source, budget=None):
    """Default surface is exactly the default-path tools; every other tool lives in register_advanced (opt-in) and is documented Advanced."""
    budget = budget or load_budget()
    default = budget['default_path_tools']['value']
    tools = tool_surface(source)
    out = []
    if [t[0] for t in tools[:len(default)]] != default:out.append('the default-path tools %s must be registered first, in that order, got %s' % (default, [t[0] for t in tools[:len(default)]]))
    if len(tools) > budget['max_tool_count']['value']:out.append('%d tools exceed max_tool_count %d' % (len(tools), budget['max_tool_count']['value']))
    for name, doc, nested in tools:
        if name not in default and not nested:out.append('%s is registered by default: only %s may be visible without CUA_TASK_ADVANCED=1' % (name, default))
        if name not in default and not doc.startswith('Advanced'):out.append('%s is neither a default-path tool nor marked Advanced' % name)
        if name in default and (doc.startswith('Advanced') or nested):out.append('%s is a default-path tool but is marked Advanced or nested' % name)
    if not guard_present(source):out.append('register_advanced() must be called only under `if ADVANCED:` where ADVANCED reads CUA_TASK_ADVANCED')
    return out


def advanced_run(code):
    """Run python code with CUA_TASK_ADVANCED=1 in a fresh interpreter from computer_use/ (the surface is decided at import time)."""
    import os
    import subprocess
    env = {**os.environ, 'CUA_TASK_ADVANCED': '1'}
    done = subprocess.run([sys.executable, '-c', code], cwd=str(HERE), env=env, capture_output=True, text=True, timeout=120)
    if done.returncode:raise RuntimeError(done.stderr[-800:])
    return json.loads(done.stdout.strip().splitlines()[-1])


def advanced_tool_names():
    return advanced_run("import asyncio, json, server; print(json.dumps([t.name for t in asyncio.run(server.mcp.list_tools())]))")


def default_workflow_section(text):
    match = re.search(r'^## Default workflow\s*\n(.*?)(?=^## )', text, re.S | re.M)
    return match.group(1) if match else None


def skill_violations(text):
    section = default_workflow_section(text)
    if section is None:return ['SKILL.md has no "## Default workflow" section']
    named = re.findall(TOOL_NAME_IN_TEXT, section)
    out = []
    if not named or named[0] != 'look':out.append('the default workflow must mention look first (look, then do), got %s' % (named[:1],))
    if named and set(named) - {'look', 'do'}:out.append('the default workflow names tools other than look and do: %s' % sorted(set(named) - {'look', 'do'}))
    if len(set(named)) > 2:out.append('the default workflow names %d tools (max 2): %s' % (len(set(named)), sorted(set(named))))
    if re.search(r'`(?:observe|read|choose|act)`.*`(?:read|choose|act|verify)`', section, re.S):
        out.append('the default workflow instructs the observe/read/choose/act/verify chain')
    return out


def over_budget(measure, limits):
    """Violations of one measured scenario against its limits."""
    out = []
    for key, label in (('calls', 'max_llm_visible_calls'), ('reader', 'max_reader_calls'), ('chooser', 'max_chooser_calls')):
        if measure[key] > limits[label]['value']:out.append('%s %d > %s %d' % (key, measure[key], label, limits[label]['value']))
    return out


def result_text(blocks):
    """Text of a FastMCP call_tool result (a content list, or a CallToolResult for screenshot tools)."""
    content = getattr(blocks, 'content', blocks)
    return content[0].text if isinstance(content, (list, tuple)) and hasattr(content[0], 'text') else json.dumps(blocks)


def new_seen():
    return {'calls': 0, 'tools': [], 'max_bytes': 0, 'per_call': [], 'naps': [], 'napped': 0}


def tally(seen, name, text):
    """Record one LLM-visible call: its response bytes (len of the JSON text the server returned) and the stage timings it carried
    (look.ms_by_stage or do.trace_summary.ms_by_stage; the fake clocks make these simulated, not wall time)."""
    seen['calls'] += 1;seen['tools'].append(name)
    seen['max_bytes'] = max(seen['max_bytes'], len(text))
    body = json.loads(text)
    stages = body.get('ms_by_stage') or (body.get('trace_summary') or {}).get('ms_by_stage') or {}
    waited = sum(seen['naps'][seen['napped']:]);seen['napped'] = len(seen['naps'])
    seen['per_call'].append({'tool': name, 'bytes': len(text), 'ms_by_stage': stages, 'wait_s': round(waited, 2)})
    return body


def seen_measure(seen):
    return {'calls': seen['calls'], 'tools': seen['tools'], 'max_bytes': seen['max_bytes'], 'total_bytes': sum(c['bytes'] for c in seen['per_call']), 'wait_s': round(sum(seen['naps']), 2), 'per_call': seen['per_call']}


def scripted_llm(goal_words=()):
    """The minimal LLM policy: it starts knowing ONLY the goal, expect and the fields/predicates it wants, and learns control, identity, labels
    and ids from the deferral itself. Returns follow(result, current) -> next arguments or None (it gives up)."""
    def pick(labels, goal, prefer=()):
        low = goal.lower()
        for word in list(prefer) + [w for w in re.findall(r'[a-z]+', low) if len(w) > 3]:
            for label in labels:
                if word in label.lower():return label
        return labels[0] if labels else None
    def follow(result, cur):
        reason, base = result.get('reason'), {'title': cur['title'], 'expect': cur['expect']}
        if result.get('dead_end'):return None
        if reason == 'control_needed':
            label = pick([c['label'] for c in result['found']['repeated_controls']], cur['goal'])
            return {**cur, 'control': label} if label else None
        if reason == 'region_label_needed':
            texts = result['found']['region_texts'];labels = [t['text'] for t in texts]
            control = pick(labels, cur['goal'])
            if not control:return None
            more = {'control': control}
            if next(t['count'] for t in texts if t['text'] == control) > 1:
                others = [l for l in labels if l != control and any(w in l.lower() for w in re.findall(r'[a-z]+', cur['goal'].lower()) if len(w) > 3)]
                if others:more['near'] = others[0]
            return {**cur, **more}
        if reason == 'region_ambiguous':
            near = [m['near'] for m in result['matches'] if m['near'] and any(w in m['near'].lower() for w in re.findall(r'[a-z]+', cur['goal'].lower()) if len(w) > 3)]
            return {**cur, 'near': near[0]} if len(near) == 1 else None
        if reason == 'records_ambiguous':
            label = pick(result['found']['controls'], cur['goal'])
            return {**base, 'goal': 'Click "%s"' % label} if label else None
        if reason in ('unknown_competitors_unacknowledged', 'unknown_or_incomplete_scope') and result.get('unknown_ids'):
            return {**cur, 'accept_unknown': result['unknown_ids']}
        if reason == 'confirm_dialog_present':
            label = pick(result['dialog']['controls'], '', prefer=('yes', 'confirm', 'ok', 'accept'))
            return {**base, 'goal': 'Click "%s"' % label}
        if reason == 'confirm_identity_partial':
            return {**base, 'goal': 'Click "%s"' % pick(result['dialog']['controls'], '', prefer=('yes', 'confirm', 'ok', 'accept'))}
        return None
    return follow


def measure_scenarios():
    """Drive the real server tool functions through a counting wrapper under scripted_llm(): call do knowing only goal, expect and the fields
    and predicates, learn control/identity/labels from each deferral, stop at done, a dead end, no hint to follow, or 5 calls.
    Scenarios run on the REAL captured Chrome trees (computer_use/fixtures/live_*_ax.json) and on the synthetic shapes a review found missing
    (computer_use/shapes.py). No tree from an unrelated real site exists yet (that needs the user's consent), so every number is fixture-derived.
    Returns {name: {calls, reader, chooser, max_bytes, status, tools}} with REAL invocation counts."""
    import server
    from core import Facade, DriverCallFailed
    from test_core import FakeVision
    import test_do as fx
    import test_live_shapes as lv
    import shapes as sh

    def run(driver, args, reader, chooser=None, follow=None, vision=None):
        chooser = chooser or fx.NamedChooser();follow = follow or scripted_llm()
        seen = new_seen()  # sleep is recorded, not slept: wait_s is the simulated latency of every settle and idle wait (deterministic)
        server.facade = Facade(driver, reader_factory=lambda: reader, generic_factory=lambda: chooser, visual_factory=vision or lv.UnknownVision, sleep=seen['naps'].append)
        def call(name, **kw):
            return tally(seen, name, result_text(asyncio.run(server.mcp.call_tool(name, kw))))
        current = {'title': 'Demo', **args}
        while True:
            result = call('do', **current)
            if result['status'] == 'done' or seen['calls'] >= 5:break
            nxt = follow(result, current)
            if nxt is None:break
            current = nxt
        return {**seen_measure(seen), 'status': result['status'],
                'reader': len(reader.requests), 'chooser': len(chooser.requests)}

    booking = {'goal': 'Book the Follow-up slot with Dr. Morgan Reyes that starts at 1:45 PM', 'expect': 'Booked:',
               'records': {'fields': lv.BOOKING_FIELDS, 'predicates': lv.BOOKING_ONE}}
    orders = {'goal': 'Cancel the Walnut desk lamp order that is still Processing', 'expect': 'Order #1044 cancelled',
              'records': {'fields': lv.ORDER_FIELDS, 'predicates': lv.ORDER_ONE}}
    def booking_driver(churn=False):
        d = lv.LiveDriver('live_booking_ax.json');d.script = lv.booked()
        if churn:
            def script(driver, els):
                if driver.version >= 2:
                    for e in els:
                        if e['element_index'] == 22:e['label'] = e['value'] = 'Starts 1:35 PM'  # an unrelated record's text changes between observe and act
                lv.booked()(driver, els)
            d.script = script
        return d
    def orders_driver():
        d = lv.LiveDriver('live_orders_ax.json');d.script = lv.orders_flow(d);return d
    def shape(els, script=None):
        d = sh.ShapeDriver(els);d.script = script;return d
    def shape_args(goal='Book Dr. B', **more):
        return {'goal': goal, 'expect': 'Booked:', 'records': {'fields': sh.NAME_FIELDS, 'predicates': sh.NAME_B}, **more}
    reader_b, reader_o = (lambda: lv.LiveReader(lv.BOOKING_PATTERNS)), (lambda: lv.LiveReader(lv.ORDER_PATTERNS))
    reader_s = lambda: lv.LiveReader(sh.PATTERNS)
    out = {}
    out['booking_list'] = run(booking_driver(), booking, reader_b())
    # Orders with everything unknown up front: control_needed, then the dialog deferral, then a second do quoting a dialog label.
    out['orders_cold'] = run(orders_driver(), orders, reader_o())
    out['orders_confirm'] = run(orders_driver(), {**orders, 'control': 'Cancel', 'confirm': 'Yes, cancel order'}, reader_o())
    out['confirm_deferral'] = run(orders_driver(), {**orders, 'control': 'Cancel'}, reader_o())
    d = fx.FlatDriver();d.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'};d.capture_id = 'cap'
    real = d.observe
    def canvas(*a):
        x = real(*a);x['elements'] = [e for e in x['elements'] if e['element_index'] == 0];return x
    d.observe = canvas
    d.parse_result = {'regions': [{'id': 't%d' % i, 'kind': 'text', 'text': t, 'bounds': {'x': 5, 'y': 10 + 30 * i, 'width': 50, 'height': 20}} for i, t in enumerate(['Save', 'Export', 'Reset'])]}
    class Picks(fx.NamedChooser):
        def __call__(self, step, request):self.requests.append(request);return {'choice': 't1', 'route': 'julia-1', 'action_authorized': True}
    out['canvas_regions_unique'] = run(d, {'goal': 'Press "Export"', 'expect': 'Exported', 'allow_foreground': True}, fx.LineReader(), chooser=Picks(), vision=FakeVision)  # a canvas has no AX text: the screenshot model is the verifier
    # allow_foreground on the canvas scenarios: a background pixel click lands at the canvas CENTRE (probe 2026-09-29, CE-FACADE-006 proposed), so a drawn-surface press is refused without it.
    # The live finding: two Export buttons drawn on a canvas, labelled by Toolbar and Footer texts (synthetic parse result). The LLM knows only the goal.
    d = sh.ShapeDriver(sh.canvas());d.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'};d.capture_id = 'cap'
    d.parse_result = {'regions': [{'id': 't%d' % i, 'kind': 'text', 'text': t, 'bounds': {'x': 10, 'y': y, 'width': 80, 'height': 24}}
                                  for i, (t, y) in enumerate([('Toolbar', 10), ('Export', 40), ('Footer', 500), ('Export', 530)])]}
    out['canvas_regions'] = run(d, {'goal': 'Press the Export button in the toolbar', 'expect': 'Exported', 'allow_foreground': True}, lv.LiveReader({}), vision=FakeVision)
    many = [('Provider %03d' % i, 'Follow-up', '30 min', '1:%02d PM' % (i % 60)) for i in range(80)]
    d = fx.FlatDriver();d.rows = fx.booking_rows(many);d.confirm_text = 'Booked Provider 041 1:41 PM'
    out['large_page_400'] = run(d, {'goal': 'Book Provider 041', 'expect': 'Booked Provider 041', 'records': {'fields': fx.FIELDS, 'predicates': [{'field': 'provider', 'value': 'Provider 041'}]}}, fx.LineReader())
    # Recovery and deferral paths on the real shapes.
    out['stale_recovery'] = run(booking_driver(churn=True), booking, reader_b())
    d = booking_driver();real_observe = d.observe;seen_obs = []
    def flaky_observe(*a):
        seen_obs.append(1)
        if len(seen_obs) == 1:raise DriverCallFailed('driver_call_failed: get_window_state exited 1')
        return real_observe(*a)
    d.observe = flaky_observe
    out['driver_failure_recovered'] = run(d, booking, reader_b())
    decoy = {**orders, 'control': 'Cancel', 'confirm': 'Yes, cancel order', 'records': {**orders['records'], 'predicates': [{'field': 'item', 'value': 'Walnut desk lamp'}, {'field': 'status', 'value': 'Processing'}]}}
    out['unknown_then_accept'] = run(orders_driver(), decoy, reader_o())
    class Abstain(fx.NamedChooser):
        def __call__(self, step, request):self.requests.append(request);return {'choice': request['actions'][0]['id'], 'route': 'julia-1', 'action_authorized': False}
    several = {**booking, 'records': {'fields': lv.BOOKING_FIELDS, 'predicates': lv.BOOKING_ONE[:2]}}
    def narrow(result, cur):return {'title': 'Demo', **booking} if result['status'] == 'deferred' and result.get('reason') else None
    out['ambiguity_deferral'] = run(booking_driver(), several, reader_b(), chooser=Abstain(), follow=narrow)
    # The live finding: the LLM wrote its predicates blind (duration contains "30"); the right slot reads "half-hour".
    class ByDescription(fx.NamedChooser):
        def __call__(self, step, request):
            self.requests.append(request);pick = next((a for a in request['actions'] if 'Telehealth' in a['description']), request['actions'][0])
            return {'choice': pick['id'], 'route': 'julia-1', 'action_authorized': True}
    blind = {'goal': 'Book the Morgan Reyes half-hour slot', 'expect': 'Booked:', 'records': {'fields': lv.BOOKING_FIELDS, 'predicates': [
        {'field': 'provider', 'op': 'contains', 'value': 'Morgan Reyes'}, {'field': 'duration', 'op': 'contains', 'value': '30'}]}}
    def judge(result, cur):
        # The LLM reads the deferral: "half-hour" is 30 minutes (S4.8), so those unknown records DO match.
        return {**cur, 'treat_as_match': result['unknown_ids']} if result.get('reason') == 'unknown_competitors_unacknowledged' else None
    out['booking_blind_predicates'] = run(booking_driver(), blind, reader_b(), chooser=ByDescription(), follow=judge)
    # The shapes a review found the two captured trees did not cover (synthetic; the LLM knows only goal, expect and the predicates).
    out['per_record_labels'] = run(shape(sh.cards(label=lambda n: 'Book Dr ' + n), sh.toast(buttons=())), shape_args(), reader_s())
    out['single_record'] = run(shape(sh.cards(names='B'), sh.toast(buttons=())), shape_args(), reader_s())
    out['toast_after_click'] = run(shape(sh.cards(), sh.toast()), shape_args(), reader_s())
    out['five_button_dialog'] = run(shape(sh.cards(), sh.dialog_then_toast(['Yes', 'No', 'Later', 'Help', 'Close'])), shape_args(), reader_s())
    out['disabled_record'] = run(shape(sh.cards(disabled='B')), shape_args(), reader_s())
    out['toolbar_records_ambiguous'] = run(shape(sh.toolbar(), sh.toast('Exported', buttons=())), {'goal': 'Export the report', 'expect': 'Exported', 'records': {'fields': sh.NAME_FIELDS, 'predicates': sh.NAME_B}}, reader_s())
    out['canvas_dead_end'] = run(shape(sh.canvas()), {'goal': 'Click the red dot', 'expect': 'Booked:'}, reader_s())
    out.update(measure_plan_scenarios())
    return out


def look_conditions(look, want):
    """The scripted LLM's part of a plan: from what look SHOWED, choose eq (a line equals the phrase) or contains (it only appears inside a line)
    for each phrase it wants, and accept them only if the conjunction singles out exactly one displayed record. Returns (conditions, the record)."""
    def holds(record, cond):
        lines = [x.lower() for x in record['lines']];value = cond['value'].lower()
        return any(x == value for x in lines) if cond['line'] == 'eq' else any(value in x for x in lines)
    conditions = []
    for phrase in want:
        every = [x.lower() for r in look['records'] for x in r['lines']]
        conditions.append({'line': 'eq' if phrase.lower() in every else 'contains', 'value': phrase})
    hits = [r for r in look['records'] if all(holds(r, c) for c in conditions)]
    return (conditions, hits[0]) if len(hits) == 1 else (None, None)


def unique_line(look, record):
    """The line of `record` that no other displayed record shows (its order number, invoice id): what a dialog will display to identify it."""
    others = [x for r in look['records'] if r is not record for x in r['lines']]
    return next((x for x in record['lines'] if x not in others), None)


def measure_plan_scenarios():
    """Option B (CE-FACADE-005): the scripted LLM starts knowing ONLY the goal and expect, calls look, writes its plan from the strings it saw,
    and reads the plan's deferrals. Every call goes through the REAL server tools; calls, reader and chooser are counted, not assumed.
    Fixture-derived like every number here (real Chrome trees for booking and orders; synthetic shapes for the wizard, the 100-row list and the canvas)."""
    import server
    from core import Facade
    from test_core import FakeVision
    import test_do as fx
    import test_live_shapes as lv
    import shapes as sh

    def run(driver, policy, reader, chooser=None, vision=None):
        chooser = chooser or fx.NamedChooser()
        seen = new_seen()  # sleep is recorded, not slept: wait_s is the simulated latency of every settle and idle wait (deterministic)
        server.facade = Facade(driver, reader_factory=lambda: reader, generic_factory=lambda: chooser, visual_factory=vision or lv.UnknownVision, sleep=seen['naps'].append)
        def call(name, **kw):
            return tally(seen, name, result_text(asyncio.run(server.mcp.call_tool(name, kw))))
        result = policy(call)
        assert not server.facade.agent.tried, 'CE-FACADE-009: parking is server-side and adds no LLM-visible call; these fixtures hold no created or agent-owned window'
        return {**seen_measure(seen), 'status': result['status'], 'reader': len(reader.requests), 'chooser': len(chooser.requests)}

    booking_goal = 'Book the Follow-up slot with Dr. Morgan Reyes that starts at 1:45 PM'
    def booking_driver():
        d = lv.LiveDriver('live_booking_ax.json');d.script = lv.booked();return d
    def orders_driver():
        d = lv.LiveDriver('live_orders_ax.json');d.script = lv.orders_flow(d);return d
    out = {}

    def booking_look_do(call):
        look = call('look', title='Demo')
        conds, _ = look_conditions(look, ['Dr. Morgan Reyes', 'Follow-up', '1:45 PM'])
        return call('do', goal=booking_goal, expect=None, title='Demo', look_id=look['look_id'], steps=[{'do': 'press', 'where': {'lines': conds}, 'expect': 'Booked:'}])
    out['plan_booking_look_do'] = run(booking_driver(), booking_look_do, lv.LiveReader(lv.BOOKING_PATTERNS))

    def booking_half_hour(call):
        look = call('look', title='Demo')
        conds, _ = look_conditions(look, ['Dr. Morgan Reyes', 'half-hour'])  # the LLM saw the string, so it filters on it: the blind "30" is never written
        return call('do', goal='Book the Morgan Reyes half-hour slot', expect=None, title='Demo', look_id=look['look_id'], steps=[{'do': 'press', 'where': {'lines': conds}, 'expect': 'Booked:'}])
    out['plan_booking_half_hour_look_do'] = run(booking_driver(), booking_half_hour, lv.LiveReader(lv.BOOKING_PATTERNS))

    def booking_no_look(call):
        conds = [{'line': 'eq', 'value': 'Dr. Morgan Reyes'}, {'line': 'eq', 'value': 'Follow-up'}, {'line': 'contains', 'value': '1:45 PM'}]
        first = call('do', goal=booking_goal, expect=None, title='Demo', look_id='lk_0000000000', steps=[{'do': 'press', 'where': {'lines': conds}, 'expect': 'Booked:'}])
        if first['status'] != 'refused':return first
        return booking_look_do(call)  # the refusal says: call look first
    out['plan_booking_no_look'] = run(booking_driver(), booking_no_look, lv.LiveReader(lv.BOOKING_PATTERNS))

    def booking_blind_fields(call):
        blind = {'fields': lv.BOOKING_FIELDS, 'predicates': [{'field': 'provider', 'op': 'contains', 'value': 'Morgan Reyes'}, {'field': 'duration', 'op': 'contains', 'value': '30'}]}
        first = call('do', goal='Book the Morgan Reyes half-hour slot', expect=None, title='Demo', steps=[{'do': 'press', 'where': blind, 'expect': 'Booked:'}])
        if first.get('reason') != 'unknown_competitors_unacknowledged':return first
        ids = next(e for e in first['steps'] if e['status'] == 'stopped')['unknown_ids']
        return call('do', goal='Book the Morgan Reyes half-hour slot', expect=None, title='Demo', steps=[{'do': 'press', 'where': blind, 'treat_as_match': ids, 'expect': 'Booked:'}])
    class ByDescription(fx.NamedChooser):
        def __call__(self, step, request):
            self.requests.append(request);pick = next((a for a in request['actions'] if 'Telehealth' in a['description']), request['actions'][0])
            return {'choice': pick['id'], 'route': 'julia-1', 'action_authorized': True}
    out['plan_booking_blind_fields'] = run(booking_driver(), booking_blind_fields, lv.LiveReader(lv.BOOKING_PATTERNS), chooser=ByDescription())

    def orders_plan(dialog_guess, identity=True, declared='guess'):
        """The dialog text is usually unknown until it appears, so a confirm step must DECLARE its complete text (positive authorization). declared='guess':
        the scripted LLM guesses a short text, the confirm defers with the ACTUAL lines, it reads them and presses the dialog control deliberately (3 calls).
        declared='exact': it already knows the wording (best case, 2 calls)."""
        def policy(call):
            look = call('look', title='Demo')
            conds, record = look_conditions(look, ['Walnut desk lamp', 'Processing'])
            control = next(c for c in record['controls'] if c.lower() in 'cancel the walnut desk lamp order')
            ident = unique_line(look, record)
            text = ['Cancel order %s (Walnut desk lamp)?' % ident] if declared == 'exact' else ['Cancel order %s?' % ident]
            press = {'do': 'press', 'where': {'lines': conds}, 'control': control, 'expect': dialog_guess.replace('#N', ident), **({'identity': [ident]} if identity else {})}
            goal = 'Cancel the Walnut desk lamp order that is still Processing'
            first = call('do', goal=goal, expect=None, title='Demo', look_id=look['look_id'], steps=[press, {'do': 'confirm', 'confirm': 'Yes, cancel order', 'dialog_text': text, 'dialog_controls': ['Yes, cancel order', 'Keep order'], 'expect': 'Order %s cancelled' % ident}])
            if first['status'] == 'done' or first.get('reason') not in ('confirm_dialog_present', 'confirm_identity_partial', 'confirm_dialog_unexpected_text'):return first
            if first['reason'] in ('confirm_identity_partial', 'confirm_dialog_unexpected_text'):  # the hint: the click is done; read dialog.lines, and if it is the right record press the dialog's control deliberately
                lines = first['steps'][-1]['dialog']['lines']
                if not any(ident in line for line in lines):return first
                return call('do', goal=goal, expect=None, title='Demo', steps=[{'do': 'press', 'control': 'Yes, cancel order', 'expect': 'Order %s cancelled' % ident}])
            # the dialog was not what the guess said: the click is done, so press the dialog's own control
            label = first['steps'][0]['dialog']['controls'][0]
            return call('do', goal=goal, expect=None, title='Demo', steps=[{'do': 'press', 'control': label, 'expect': 'Order %s cancelled' % ident}])
        return policy
    out['plan_orders_look_do'] = run(orders_driver(), orders_plan('Cancel order #N'), lv.LiveReader(lv.ORDER_PATTERNS))  # declares a guess: confirm defers with the actual dialog lines, then a deliberate press
    out['plan_orders_declared_dialog'] = run(orders_driver(), orders_plan('Cancel order #N', declared='exact'), lv.LiveReader(lv.ORDER_PATTERNS))  # best case: the caller already knows the wording
    out['plan_orders_identity_default'] = run(orders_driver(), orders_plan('Cancel order #N', identity=False, declared='exact'), lv.LiveReader(lv.ORDER_PATTERNS))
    out['plan_orders_wrong_dialog_guess'] = run(orders_driver(), orders_plan('Are you sure'), lv.LiveReader(lv.ORDER_PATTERNS))

    def wizard(final_label):
        def policy(call):
            look = call('look', title='Demo')
            assert 'Step 1 of 3' in ' '.join(look['text']) and 'Next' in look['controls']
            steps = [{'do': 'press', 'control': 'Next', 'expect': 'Step 2 of 3'}, {'do': 'press', 'control': 'Next', 'expect': 'Step 3 of 3'}, {'do': 'press', 'control': final_label, 'expect': 'Setup complete.'}]
            first = call('do', goal='Complete the setup wizard', expect=None, title='Demo', steps=steps)
            if first['status'] == 'done' or first.get('reason') != 'control_not_found':return first
            done = first['failed_step'] - 1  # the hint: steps before it are done; found.controls lists what is pressable
            label = next(c for c in first['steps'][-1]['found']['controls'] if c not in ('Back', 'Cancel'))
            return call('do', goal='Complete the setup wizard', expect=None, title='Demo', steps=[{'do': 'press', 'control': label, 'expect': 'Setup complete.'}])
        return policy
    def wizard_driver():
        d = sh.ShapeDriver(sh.wizard_els(1));d.script = sh.wizard_script;return d
    out['plan_wizard_3_steps'] = run(wizard_driver(), wizard('Finish'), lv.LiveReader({}))
    out['plan_wizard_wrong_final_label'] = run(wizard_driver(), wizard('Submit'), lv.LiveReader({}))

    def invoices(fields):
        def policy(call):
            look = call('look', title='Demo', focus='Northwind', **({'fields': {'vendor': {'description': 'Vendor'}, 'amount': {'description': 'Amount'}}} if fields else {}))
            conds, record = look_conditions(look, ['Northwind Traders', '$1,240.00'])
            return call('do', goal='Approve the invoice from Northwind Traders for $1,240.00', expect=None, title='Demo', look_id=look['look_id'],
                        steps=[{'do': 'press', 'where': {'lines': conds}, 'expect': 'Approved ' + record['lines'][0]}])
        return policy
    def invoice_driver():
        d = sh.ShapeDriver(sh.invoices());d.script = sh.approved_status;return d
    out['plan_invoices_100_focus'] = run(invoice_driver(), invoices(False), lv.LiveReader({}))
    out['plan_invoices_100_fields'] = run(invoice_driver(), invoices(True), fx.LineReader({'vendor': r'(Northwind Trad\w+)', 'amount': r'(\$[\d,\.]+)'}))

    def canvas_driver():
        d = sh.ShapeDriver(sh.canvas());d.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'};d.capture_id = 'cap'
        d.parse_result = {'regions': [{'id': 't%d' % i, 'kind': 'text', 'text': t, 'bounds': {'x': 10, 'y': y, 'width': 80, 'height': 24}}
                                      for i, (t, y) in enumerate([('Toolbar', 10), ('Export', 40), ('Footer', 500), ('Export', 530)])]};return d
    def canvas(call):
        look = call('look', title='Demo')
        export = next(t for t in look['canvas']['text_regions'] if t['text'] == 'Export')
        near = next(n for n in export['near'] if n.lower() in 'press the export button in the toolbar')
        return call('do', goal='Press the Export button in the toolbar', expect=None, title='Demo', steps=[{'do': 'press', 'control': 'Export', 'near': near, 'expect': 'Exported', 'allow_foreground': True}])
    out['plan_canvas_look_do'] = run(canvas_driver(), canvas, lv.LiveReader({}), vision=FakeVision)

    def churn(driver, els):
        wiz = sh.wizard_els(1 + min(len(driver.executed), 1))
        if driver.executed:E = sh.E;E(wiz, 1, 'AXStaticText', 'tick %d' % driver.version, 'tick %d' % driver.version)  # an in-scope text changes on EVERY observation once step 1 landed
        return wiz
    def stale_driver():
        d = sh.ShapeDriver(sh.wizard_els(1));d.script = churn;return d
    def stale(call):
        look = call('look', title='Demo')
        return call('do', goal='Complete the setup wizard', expect=None, title='Demo', steps=[{'do': 'press', 'control': 'Next', 'expect': 'Step 2 of 3'}, {'do': 'press', 'control': 'Next', 'expect': 'Step 3 of 3'}])
    out['plan_stale_mid_plan'] = run(stale_driver(), stale, lv.LiveReader({}))
    # Review of PR 18 (budget honesty): the scripted LLM above takes its phrases from the goal, so it never writes a wrong filter and these ceilings
    # guard CALL COUNTS, not plan correctness (a LOWER BOUND on what a real LLM needs). These scenarios make it write plans the guards must stop.
    import test_plan as tp
    def by(els, i):
        return next(e for e in els if e['element_index'] == i)

    def vocab_mismatch(call):
        look = call('look', title='Demo')
        goal = 'Book the Morgan Reyes Telehealth slot that lasts 30 min'
        conds = [{'line': 'eq', 'value': 'Dr. Morgan Reyes'}, {'line': 'eq', 'value': 'Telehealth'}, {'line': 'contains', 'value': '30 min'}]  # the LLM's own vocabulary
        first = call('do', goal=goal, expect=None, title='Demo', look_id=look['look_id'], steps=[{'do': 'press', 'where': {'lines': conds}, 'expect': 'Booked:'}])
        if first.get('reason') != 'no_matching_record':return first
        rec = next(r for r in look['records'] if 'Telehealth' in r['lines'] and 'Dr. Morgan Reyes' in r['lines'])  # back to the look's own strings
        duration = next(x for x in rec['lines'] if x not in ('Dr. Morgan Reyes', 'Telehealth') and not x.startswith('Starts') and x != 'Video visit')
        conds = [{'line': 'eq', 'value': 'Dr. Morgan Reyes'}, {'line': 'eq', 'value': 'Telehealth'}, {'line': 'eq', 'value': duration}]
        return call('do', goal=goal, expect=None, title='Demo', look_id=look['look_id'], steps=[{'do': 'press', 'where': {'lines': conds}, 'expect': 'Booked:'}])
    out['plan_booking_vocab_mismatch'] = run(booking_driver(), vocab_mismatch, lv.LiveReader(lv.BOOKING_PATTERNS))

    def hidden_driver():
        d = lv.LiveDriver('live_booking_ax.json')
        def script(dr, els):
            by(els, 43)['label'] = by(els, 43)['value'] = 'Starts 1:45 PM' + ' x' * 25 + ' SOLD OUT'  # past the 60-character display cut
            lv.booked()(dr, els)
        d.script = script;return d
    def hidden_negative(call):
        look = call('look', title='Demo')
        conds, _ = look_conditions(look, ['Dr. Morgan Reyes', 'Follow-up', '1:45 PM'])
        return call('do', goal=booking_goal + ' unless it is sold out', expect=None, title='Demo', look_id=look['look_id'],
                    steps=[{'do': 'press', 'where': {'lines': conds + [{'line': 'not_contains', 'value': 'sold out'}]}, 'expect': 'Booked:'}])
    out['plan_hidden_text_negative'] = run(hidden_driver(), hidden_negative, lv.LiveReader(lv.BOOKING_PATTERNS))

    def negated_dialog(call):
        look = call('look', title='Demo')
        conds, record = look_conditions(look, ['Walnut desk lamp', 'Processing'])
        ident = unique_line(look, record)
        return call('do', goal='Cancel the Walnut desk lamp order that is still Processing', expect=None, title='Demo', look_id=look['look_id'],
                    steps=[{'do': 'press', 'where': {'lines': conds}, 'control': 'Cancel', 'identity': [ident], 'expect': 'order ' + ident},
                           {'do': 'confirm', 'confirm': 'Yes, cancel order', 'dialog_text': ['Cancel order %s (Walnut desk lamp)?' % ident], 'dialog_controls': ['Yes, cancel order', 'Keep order'], 'expect': 'Order %s cancelled' % ident}])
    d = lv.LiveDriver('live_orders_ax.json');d.script = tp.orders_dialog('Do NOT cancel order #1044 (Walnut desk lamp)')
    out['plan_negated_dialog'] = run(d, negated_dialog, lv.LiveReader(lv.ORDER_PATTERNS))

    def delete_page():
        els, web = sh.base()
        for label in ('Delete account', 'Keep'):sh.E(els, web, 'AXButton', label)
        d = sh.ShapeDriver(els);d.script = sh.toast('Account deleted', buttons=());return d
    def destructive(declared_after_refusal):
        def policy(call):
            step = {'do': 'press', 'control': 'Delete account', 'expect': 'Account deleted'}
            first = call('do', goal='Delete my account', expect=None, title='Demo', steps=[step])
            if first['status'] != 'refused' or not declared_after_refusal:return first
            return call('do', goal='Delete my account', expect=None, title='Demo', steps=[{**step, 'allow_destructive': 'Delete account'}])  # the refusal names the declaration
        return policy
    out['plan_destructive_undeclared'] = run(delete_page(), destructive(False), lv.LiveReader({}))
    out['plan_destructive_declared_after_refusal'] = run(delete_page(), destructive(True), lv.LiveReader({}))

    # Second review of PR 18.
    import test_plan_review2 as tp2
    def capped_uniqueness(call):
        look = call('look', title='Demo', focus='1:45')  # the LLM focuses on the slot it wants; other real records still satisfy a loose condition
        loose = [{'line': 'eq', 'value': 'Dr. Morgan Reyes'}, {'line': 'eq', 'value': 'Follow-up'}]
        first = call('do', goal=booking_goal, expect=None, title='Demo', look_id=look['look_id'], steps=[{'do': 'press', 'where': {'lines': loose}, 'expect': 'Booked:'}])
        if first.get('reason') != 'where_matches_several':return first
        return call('do', goal=booking_goal, expect=None, title='Demo', look_id=look['look_id'], steps=[{'do': 'press', 'where': {'lines': loose + [{'line': 'contains', 'value': '1:45 PM'}]}, 'expect': 'Booked:'}])
    out['plan_uniqueness_over_all_records'] = run(booking_driver(), capped_uniqueness, lv.LiveReader(lv.BOOKING_PATTERNS))

    def hidden_page():
        d = sh.ShapeDriver(tp2.two_orders(hidden=('Status: Cancelled',)));d.script = sh.toast('Opened', buttons=());return d
    def hidden_ack(call):
        look = call('look', title='Demo')
        return call('do', goal='Open the active order A', expect=None, title='Demo', look_id=look['look_id'],
                    steps=[{'do': 'press', 'where': {'lines': [{'line': 'eq', 'value': 'Order A'}, {'line': 'eq', 'value': 'Status: Active'}]}, 'expect': 'Opened'}])
    out['plan_hidden_text_ack'] = run(hidden_page(), hidden_ack, lv.LiveReader({}))
    def hidden_wide(call):
        look = call('look', title='Demo', max_lines=20, line_chars=200)  # the whole record is visible, so the LLM can see order A is cancelled and picks B
        return call('do', goal='Open the active order', expect=None, title='Demo', look_id=look['look_id'],
                    steps=[{'do': 'press', 'where': {'lines': [{'line': 'eq', 'value': 'Status: Active'}, {'line': 'not_contains', 'value': 'Cancelled'}]}, 'expect': 'Opened'}])
    out['plan_hidden_text_wide_look'] = run(hidden_page(), hidden_wide, lv.LiveReader({}))

    def checkbox_flip(call):
        look = call('look', title='Demo')
        box['value'] = '1'  # someone else subscribed between the look and the plan
        return call('do', goal='Subscribe to the newsletter', expect=None, title='Demo', look_id=look['look_id'], steps=[{'do': 'press', 'control': 'Subscribe', 'expect': 'Subscribed'}])
    els, web = sh.base();sh.E(els, web, 'AXStaticText', 'Newsletter', 'Newsletter');idx = sh.E(els, web, 'AXCheckBox', 'Subscribe', '0');box = {'value': '0'}
    def box_script(dr, e2):
        by(e2, idx)['value'] = box['value']
        if dr.executed:sh.E(e2, 1, 'AXStaticText', 'Subscribed', 'Subscribed')
    d = sh.ShapeDriver(els);d.script = box_script
    out['plan_checkbox_flip'] = run(d, checkbox_flip, lv.LiveReader({}))

    # Third review: dialog text and record text are REGION-COMPLETE.
    import test_plan_review3 as tp3
    def extra_control(call):
        look = call('look', title='Demo')
        conds, record = look_conditions(look, ['Walnut desk lamp', 'Processing'])
        ident = unique_line(look, record)
        return call('do', goal='Cancel the Walnut desk lamp order that is still Processing', expect=None, title='Demo', look_id=look['look_id'],
                    steps=[{'do': 'press', 'where': {'lines': conds}, 'control': 'Cancel', 'identity': [ident], 'expect': 'order ' + ident},
                           {'do': 'confirm', 'confirm': 'Yes, cancel order', 'dialog_text': ['Cancel order %s (Walnut desk lamp)?' % ident], 'dialog_controls': ['Yes, cancel order', 'Keep order'], 'expect': 'x'}])
    d = lv.LiveDriver('live_orders_ax.json');d.script = tp3.dialog_flow(lambda k: [tp3.node(k, 15, 'AXCheckBox', 'Also delete my account', '1', checked=True, actions=['AXPress'])])
    out['plan_dialog_extra_control'] = run(d, extra_control, lv.LiveReader(lv.ORDER_PATTERNS))  # a pre-checked box the caller never declared: nothing further pressed

    def image_badge(call):
        look = call('look', title='Demo')
        badge = [r for r in look['records'] if any(x.startswith('image: ') and 'Cancelled' in x for x in r['lines'])]
        target = next(r for r in look['records'] if r not in badge)  # the LLM SEES the badge line and picks the other order
        return call('do', goal='Open the order that is not cancelled', expect=None, title='Demo', look_id=look['look_id'],
                    steps=[{'do': 'press', 'where': {'lines': [{'line': 'eq', 'value': target['lines'][0]}]}, 'expect': 'Opened'}])
    d = sh.ShapeDriver(tp3.record_page(images='Cancelled'));d.script = sh.toast('Opened', buttons=())
    out['plan_image_badge_seen'] = run(d, image_badge, lv.LiveReader({}))

    # CE-FACADE-007: navigation as plan steps. The Driver's browser tools are faked (test_browser.BrowserDriver, shapes from the 0.31.0 live measurements)
    # over the REAL captured booking tree; the tab strip of the open_tab scenario is SYNTHETIC (no live capture has one). Fixture-derived, not a rate.
    import test_browser as tb
    def nav_driver(strip=False, press=False):
        d = tb.BrowserDriver();d.strip = strip
        if press:d.script = lv.booked()
        return d
    def goto_look_plan(call):
        first = call('do', goal='Open the booking page', expect=None, title='Demo', steps=[{'do': 'goto', 'url': tb.BOOKING, 'expect': 'Dr. Priya Shah'}])
        if first['status'] != 'done':return first
        return booking_look_do(call)
    out['nav_goto_look_plan'] = run(nav_driver(press=True), goto_look_plan, lv.LiveReader(lv.BOOKING_PATTERNS))

    # CE-FACADE-010 (#64): the aha moment, the first verified do, traced as time_to_first_verified_do: look, do (2 calls) on a ready machine and goto, look, do
    # (3) when the page is not open yet. The scripted LLM is the same as above; first_do_calls is the facade's own trace, and table() requires it to equal the counted calls. Fixture-derived, not a rate.
    out['onboarding_first_do'] = run(booking_driver(), booking_look_do, lv.LiveReader(lv.BOOKING_PATTERNS))
    out['onboarding_first_do']['first_do_calls'] = (server.facade.first_do or {}).get('calls')
    out['onboarding_first_do_goto'] = run(nav_driver(press=True), goto_look_plan, lv.LiveReader(lv.BOOKING_PATTERNS))
    out['onboarding_first_do_goto']['first_do_calls'] = (server.facade.first_do or {}).get('calls')

    def open_read_close(call):
        first = call('do', goal='Open the booking page in a new tab', expect=None, title='Demo', steps=[{'do': 'open_tab', 'url': tb.BOOKING, 'expect': 'Dr. Priya Shah'}])
        if first['status'] != 'done':return first
        look = call('look', title='Demo')  # the read: the look's records are the answer, nothing is clicked
        assert look['records'], look
        return call('do', goal='Close the tab this task opened', expect=None, title='Demo', steps=[{'do': 'close_tab'}])
    out['nav_open_tab_read_close'] = run(nav_driver(strip=True), open_read_close, lv.LiveReader(lv.BOOKING_PATTERNS))

    def permission_stop(call):
        result = call('do', goal='Open the booking page', expect=None, title='Demo', steps=[{'do': 'goto', 'url': tb.BOOKING, 'expect': 'Dr. Priya Shah'}])
        assert result['steps'][0]['reason'] == 'permission_required', result
        return result  # stop and ask the user: no retry, no other browser or profile
    d = nav_driver();d.refuse = {'get_browser_state': 'browser_requires_setup', 'browser_prepare': 'existing_profile_not_granted'}
    out['nav_permission_required_stop'] = run(d, permission_stop, lv.LiveReader({}))
    assert d.called('browser_navigate') == [] and d.executed == [], 'a permission stop must deliver nothing'

    # CE-FACADE-007 (#34): a multi-page read is ONE do call (open_tab -> look -> close_tab per url, each page with its own look_id and landing verdict),
    # where comparing N pages with goto plus look costs 2N calls. Same fakes as above (REAL booking tree, SYNTHETIC tab strip); fixture-derived, not a rate.
    import test_read_pages as trp
    def pages_driver(dest=None):
        d = trp.PagesDriver(trp.Clock());d.dest = dest or {}
        return d
    def read_three(call):
        result = call('do', goal='Compare the three booking pages', expect=None, title='Demo', steps=[{'do': 'read_pages', 'urls': [trp.A, trp.B, trp.C]}])
        pages = result['steps'][0]['pages']
        assert [p['status'] for p in pages] == ['ok'] * 3 and all(p['look_id'] for p in pages), result
        return result
    out['nav_read_pages_3'] = run(pages_driver(), read_three, lv.LiveReader({}))

    def read_one_fails(call):
        result = call('do', goal='Compare the three booking pages', expect=None, title='Demo', steps=[{'do': 'read_pages', 'urls': [trp.A, trp.B, trp.C]}])
        pages = result['steps'][0]['pages']
        assert [p['status'] for p in pages] == ['ok', 'failed', 'ok'] and pages[1]['landing'] == 'navigated_elsewhere', result
        return result  # the LLM has two pages and the verdict of the third: it reports, it does not retry
    out['nav_read_pages_one_fails'] = run(pages_driver({trp.B: trp.ELSEWHERE}), read_one_fails, lv.LiveReader({}))

    # CE-FACADE-008 (#54): a device is look, then do through mobile-mcp (a fake backend serving the REAL emulator element list); fixture-derived, not a rate.
    import test_mobile as tm
    out.update(tm.budget_scenarios())
    return out


def tools_list_bytes():
    """What every tools/list (and the initialize instructions) costs the LLM in the default surface: bytes of each visible tool's description (the
    docstring) and input schema (parameter descriptions), and of the server instructions. Measured through the real FastMCP registry."""
    import server
    tools = asyncio.run(server.mcp.list_tools())
    return {'instructions': len(server.INSTRUCTIONS.encode()),
            'tools': {t.name: {'description': len((t.description or '').encode()), 'schema': len(json.dumps(t.inputSchema).encode())} for t in tools}}


def table(budget=None, measured=None):
    """Rows (scenario, calls, budget, verdict, detail) plus the overall violation list."""
    budget = budget or load_budget();measured = measured or measure_scenarios()
    rows, problems = [], []
    limit_bytes = budget['max_response_bytes']['value']
    for name, limits in budget['scenarios'].items():
        m = measured[name]
        bad = over_budget(m, limits)
        if m['status'] != limits.get('final_status', 'done'):bad.append('status %s, expected %s' % (m['status'], limits.get('final_status', 'done')))
        if m['tools'] and any(t not in budget['default_path_tools']['value'] for t in m['tools']):bad.append('default path used %s' % sorted(set(m['tools'])))
        if m['max_bytes'] > limit_bytes:bad.append('response %d bytes > %d' % (m['max_bytes'], limit_bytes))
        if 'first_do_calls' in m and m['first_do_calls'] != m['calls']:bad.append('time_to_first_verified_do traced %s calls, counted %d' % (m['first_do_calls'], m['calls']))
        rows.append((name, m['calls'], limits['max_llm_visible_calls']['value'], 'FAIL' if bad else 'PASS',
                     'reader=%d chooser=%d bytes=%d%s' % (m['reader'], m['chooser'], m['max_bytes'], '; ' + '; '.join(bad) if bad else '')))
        problems += ['%s: %s' % (name, b) for b in bad]
    return rows, problems


def response_table(measured, listing):
    """Rows (scenario, per-call bytes, total, wait_s, per-call stage ms) for the printed table."""
    return [(name, [c['bytes'] for c in m['per_call']], m['total_bytes'], m['wait_s'], [sum(c['ms_by_stage'].values()) for c in m['per_call']]) for name, m in measured.items()]


def all_violations(with_measure=False):
    measured = measure_scenarios();listing = tools_list_bytes()
    problems = budget_violations() + response_budget_violations() + surface_violations(SERVER.read_text()) + skill_violations(SKILL.read_text())
    rows, measured_problems = table(measured=measured)
    problems = problems + measured_problems + response_violations(load_response_budget(), measured, listing)
    return (rows, problems, measured, listing) if with_measure else (rows, problems)


if __name__ == '__main__':
    if sys.argv[1:] == ['--write-response-budget']:
        previous = load_response_budget() if RESPONSE_BUDGET.exists() else None
        measured, listing = measure_scenarios(), tools_list_bytes()
        budget = response_budget_from(measured, listing, previous)
        RESPONSE_BUDGET.write_text(json.dumps(budget, indent=2) + '\n')
        flat = {'.'.join(path): leaf['value'] for path, leaf in leaves(budget)}
        ces = json.loads(CES.read_text())
        ce = next(c for c in ces if c['id'] == RESPONSE_CE)
        ce['response_budget'] = {'note': 'Ceilings are the measured number x 1.1 rounded up (bytes of the JSON the server returns; wait_s is the simulated settle and idle waits); a number changes only with this CE or a later one naming it.', **flat}
        CES.write_text(json.dumps(ces, indent=1, ensure_ascii=False) + '\n')
        print('wrote %s (%d ceilings) and %s response_budget' % (RESPONSE_BUDGET.name, len(flat), RESPONSE_CE))
    else:
        raise SystemExit('usage: call_budget.py --write-response-budget')
