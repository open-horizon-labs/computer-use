"""Call-budget guardrails: the default path stays one LLM-visible call (facade/CALL_BUDGET.json).

Measures the REAL server tool functions through a counting harness on fake fixtures (no Driver, model,
desktop or network), and lints the tool surface and the skill's default workflow. Shared by
facade/test_budget.py and scripts/check_call_budget.py.
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
CES = ROOT / 'inference/cua-decider/capability-dispatch/COUNTEREXAMPLES.json'
SKILL = ROOT / 'skills/cua-capability-dispatch/SKILL.md'
SERVER = HERE / 'server.py'
PRIMITIVE_CHAIN = ('cua_observe', 'cua_read', 'cua_choose', 'cua_act', 'cua_verify')


def load_budget():
    return json.loads(BUDGET.read_text())


def leaves(node, path=()):
    """Yield (path, leaf-dict) for every {value, changed_by} in the budget."""
    if isinstance(node, dict) and 'value' in node:
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from leaves(value, path + (key,))


def budget_violations(budget=None, ces=None):
    """Every number needs a CE id, the CE must exist, and its recorded call_budget must equal the number."""
    budget = budget or load_budget()
    ces = ces if ces is not None else json.loads(CES.read_text())
    by_id = {ce['id']: ce for ce in ces}
    out = []
    for path, leaf in leaves(budget):
        name = '.'.join(path)
        ce = by_id.get(leaf.get('changed_by'))
        if not ce:out.append('%s: changed_by %r names no CE in COUNTEREXAMPLES.json' % (name, leaf.get('changed_by')));continue
        recorded = ce.get('call_budget', {}).get(name)
        if recorded != leaf['value']:out.append('%s: value %r differs from %s call_budget %r' % (name, leaf['value'], ce['id'], recorded))
    return out


def tool_surface(source):
    """[(name, docstring)] of every @mcp.tool function in server.py, in registration order."""
    tools = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and any('tool' in ast.dump(d) for d in node.decorator_list):
            tools.append((node.name, ast.get_docstring(node) or ''))
    return tools


def surface_violations(source, budget=None):
    budget = budget or load_budget()
    default = budget['default_path_tools']['value']
    tools = tool_surface(source)
    out = []
    if not tools or tools[0][0] != default[0]:out.append('%s must be registered first, got %s' % (default[0], tools[0][0] if tools else None))
    if len(tools) > budget['max_tool_count']['value']:out.append('%d tools exceed max_tool_count %d' % (len(tools), budget['max_tool_count']['value']))
    for name, doc in tools:
        if name not in default and not doc.startswith('Advanced'):out.append('%s is neither a default-path tool nor marked Advanced' % name)
        if name in default and doc.startswith('Advanced'):out.append('%s is a default-path tool but marked Advanced' % name)
    return out


def default_workflow_section(text):
    match = re.search(r'^## Default workflow\s*\n(.*?)(?=^## )', text, re.S | re.M)
    return match.group(1) if match else None


def skill_violations(text):
    section = default_workflow_section(text)
    if section is None:return ['SKILL.md has no "## Default workflow" section']
    named = re.findall(r'cua_[a-z_]+', section)
    out = []
    if not named or named[0] != 'cua_do':out.append('the default workflow must mention cua_do first, got %s' % (named[:1],))
    if len(set(named)) > 2:out.append('the default workflow names %d tools (max 2): %s' % (len(set(named)), sorted(set(named))))
    if re.search(r'cua_(?:observe|read|choose|act)\b.*cua_(?:read|choose|act|verify)\b', section, re.S):
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


def measure_scenarios():
    """Drive the real server tools through a counting wrapper under a minimal LLM policy: call cua_do; on a deferral, follow the
    scenario's recovery hint once (or, when the scenario has none, naively repeat the call once); stop at done or after 4 calls.
    Returns {name: {calls, reader, chooser, max_bytes, status, tools}} with REAL invocation counts."""
    import server
    from core import Facade
    from test_core import FakeVision
    import test_do as fx

    RETRY = object()

    def run(driver, args, reader=None, chooser=None, follow=RETRY):
        reader = reader or fx.LineReader();chooser = chooser or fx.NamedChooser()
        server.facade = Facade(driver, reader_factory=lambda: reader, generic_factory=lambda: chooser, visual_factory=FakeVision, sleep=lambda s: None)
        seen = {'calls': 0, 'tools': [], 'max_bytes': 0}
        def call(name, **kw):
            seen['calls'] += 1;seen['tools'].append(name)
            text = result_text(asyncio.run(server.mcp.call_tool(name, kw)))
            seen['max_bytes'] = max(seen['max_bytes'], len(text))
            return json.loads(text)
        current = {'title': 'Demo', **args}
        while True:
            result = call('cua_do', **current)
            if result['status'] == 'done' or seen['calls'] >= 4:break
            nxt = current if follow is RETRY else (follow(result, current) if follow else None)
            if nxt is None:break
            current = nxt
            follow = RETRY if follow is RETRY else follow
        return {'calls': seen['calls'], 'tools': seen['tools'], 'max_bytes': seen['max_bytes'], 'status': result['status'],
                'reader': len(reader.requests), 'chooser': len(chooser.requests)}

    def records(pred, fields=fx.FIELDS):
        return {'fields': fields, 'predicates': pred}
    stale_rows = lambda v: fx.booking_rows([(n, s, d, '1:35 PM' if (n == 'Provider A' and v >= 2) else t) for n, s, d, t in fx.PROVIDERS])
    orders = lambda: {'records': records([{'field': 'order', 'value': '1042'}, {'field': 'customer', 'value': 'Cedar'}], fx.ORDER_FIELDS),
                      'goal': 'Cancel the order 1042 for customer Cedar', 'expect': 'Order 1042 cancelled'}
    def orders_driver():
        d = fx.FlatDriver();d.rows = fx.order_rows();d.confirm_text = 'Order 1042 cancelled';d.modal = fx.ConfirmDialog.MODAL;return d
    booking = {'goal': 'Book the Follow-up slot that starts at 1:45 PM', 'records': records(fx.ONE), 'expect': 'Booked Provider E'}
    out = {}
    d = fx.FlatDriver();d.confirm_text = 'Booked Provider E 1:45 PM'
    out['booking_list'] = run(d, booking)
    out['orders_confirm'] = run(orders_driver(), {**orders(), 'confirm': 'Yes, cancel order'}, reader=fx.LineReader(fx.ORDER_PATTERNS))
    d = fx.FlatDriver();d.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'};d.capture_id = 'cap'
    real = d.observe
    def canvas(*a):
        x = real(*a);x['elements'] = [e for e in x['elements'] if e['element_index'] == 0];return x
    d.observe = canvas
    d.parse_result = {'regions': [{'id': 't%d' % i, 'kind': 'text', 'text': t, 'bounds': {'x': 5, 'y': 10 + 30 * i, 'width': 50, 'height': 20}} for i, t in enumerate(['Save', 'Export', 'Reset'])]}
    class Picks(fx.NamedChooser):
        def __call__(self, step, request):self.requests.append(request);return {'choice': 't1', 'route': 'julia-1', 'action_authorized': True}
    out['canvas_regions'] = run(d, {'goal': 'Press "Export"', 'expect': 'Exported'}, chooser=Picks())
    many = [('Provider %03d' % i, 'Follow-up', '30 min', '1:%02d PM' % (i % 60)) for i in range(80)]
    d = fx.FlatDriver();d.rows = fx.booking_rows(many);d.confirm_text = 'Booked Provider 041 1:41 PM'
    out['large_page_400'] = run(d, {'goal': 'Book Provider 041', 'records': records([{'field': 'provider', 'value': 'Provider 041'}]), 'expect': 'Booked Provider 041'})
    # Recovery and deferral paths: what a clean-looking run costs when the world misbehaves.
    d = fx.FlatDriver();d.confirm_text = 'Booked Provider E 1:45 PM';d.rows_at = stale_rows
    out['stale_recovery'] = run(d, booking)
    d = fx.FlatDriver();d.confirm_text = 'Booked Provider E 1:45 PM';flaky = d.observe;seen_obs = []
    def flaky_observe(*a):
        seen_obs.append(1)
        if len(seen_obs) == 1:
            from core import DriverCallFailed
            raise DriverCallFailed('driver_call_failed: get_window_state exited 1')
        return flaky(*a)
    d.observe = flaky_observe
    out['driver_failure_recovered'] = run(d, booking)
    d = fx.FlatDriver();d.confirm_text = 'Booked Provider D';reader = fx.LineReader();reader.missing = lambda call, rid, field: rid == fx.button(11) and field == 'duration'
    out['unknown_then_accept'] = run(d, {'goal': 'Book the 45 minute consultation', 'records': records(fx.D_ONLY), 'expect': 'Booked Provider D'}, reader=reader,
                                     follow=lambda result, cur: {**cur, 'accept_unknown': result['unknown_ids']} if result.get('unknown_ids') else None)
    d = orders_driver()
    out['confirm_deferral'] = run(d, orders(), reader=fx.LineReader(fx.ORDER_PATTERNS),
                                  follow=lambda result, cur: {'title': 'Demo', 'goal': 'Press "Yes, cancel order"', 'expect': 'Order 1042 cancelled'})
    d = fx.FlatDriver();d.confirm_text = 'Booked Provider D'
    class Abstain(fx.NamedChooser):
        def __call__(self, step, request):self.requests.append(request);return {'choice': request['actions'][0]['id'], 'route': 'julia-1', 'action_authorized': False}
    out['ambiguity_deferral'] = run(d, {'goal': 'Book a consultation that is not the 60 minute one', 'records': records(fx.TWO), 'expect': 'Booked Provider D'}, chooser=Abstain(),
                                    follow=lambda result, cur: {**cur, 'records': records(fx.TWO + [{'field': 'provider', 'value': 'Provider D'}])})
    return out


def table(budget=None, measured=None):
    """Rows (scenario, calls, budget, verdict, detail) plus the overall violation list."""
    budget = budget or load_budget();measured = measured or measure_scenarios()
    rows, problems = [], []
    limit_bytes = budget['max_response_bytes']['value']
    for name, limits in budget['scenarios'].items():
        m = measured[name]
        bad = over_budget(m, limits)
        if m['status'] != 'done':bad.append('status %s, expected done' % m['status'])
        if m['tools'] and any(t not in budget['default_path_tools']['value'] for t in m['tools']):bad.append('default path used %s' % sorted(set(m['tools'])))
        if m['max_bytes'] > limit_bytes:bad.append('response %d bytes > %d' % (m['max_bytes'], limit_bytes))
        rows.append((name, m['calls'], limits['max_llm_visible_calls']['value'], 'FAIL' if bad else 'PASS',
                     'reader=%d chooser=%d bytes=%d%s' % (m['reader'], m['chooser'], m['max_bytes'], '; ' + '; '.join(bad) if bad else '')))
        problems += ['%s: %s' % (name, b) for b in bad]
    return rows, problems


def all_violations():
    problems = budget_violations() + surface_violations(SERVER.read_text()) + skill_violations(SKILL.read_text())
    rows, measured_problems = table()
    return rows, problems + measured_problems
