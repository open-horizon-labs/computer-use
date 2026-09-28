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
    """Drive the real server tools on the canonical fixtures. Returns {name: {calls, reader, chooser, max_bytes, status, tools}}."""
    import server
    from core import Facade
    from test_core import FakeVision
    import test_do as fx

    def run(driver, goal, args, reader=None, chooser=None, plan=None):
        reader = reader or fx.LineReader();chooser = chooser or fx.NamedChooser()
        server.facade = Facade(driver, reader_factory=lambda: reader, generic_factory=lambda: chooser, visual_factory=FakeVision, sleep=lambda s: None)
        seen = {'calls': 0, 'tools': [], 'max_bytes': 0}
        def call(name, **kw):
            seen['calls'] += 1;seen['tools'].append(name)
            blocks = asyncio.run(server.mcp.call_tool(name, kw))
            text = result_text(blocks)
            seen['max_bytes'] = max(seen['max_bytes'], len(text))
            return json.loads(text)
        result = call('cua_do', goal=goal, title='Demo', **args)  # the whole default-path plan: state the intent once
        return {'calls': seen['calls'], 'tools': seen['tools'], 'max_bytes': seen['max_bytes'], 'status': result['status'],
                'reader': len(reader.requests), 'chooser': len(chooser.requests)}

    def records(pred, fields=fx.FIELDS):
        return {'fields': fields, 'predicates': pred}
    out = {}
    d = fx.FlatDriver();d.confirm_text = 'Booked Provider E 1:45 PM'
    out['booking_list'] = run(d, 'Book the Follow-up slot that starts at 1:45 PM', {'records': records(fx.ONE), 'expect': 'Booked Provider E'})
    d = fx.FlatDriver();d.rows = fx.order_rows();d.confirm_text = 'Order 1042 cancelled';d.modal = fx.ConfirmDialog.MODAL
    reader = fx.LineReader(fx.ORDER_PATTERNS)
    out['orders_confirm'] = run(d, 'Cancel the order 1042 for customer Cedar',
        {'records': records([{'field': 'order', 'value': '1042'}, {'field': 'customer', 'value': 'Cedar'}], fx.ORDER_FIELDS), 'expect': 'Order 1042 cancelled'},
        reader=reader, chooser=fx.NamedChooser('Yes'))
    d = fx.FlatDriver();d.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'};d.capture_id = 'cap'
    real = d.observe
    def canvas(*a):
        x = real(*a);x['elements'] = [e for e in x['elements'] if e['element_index'] == 0];return x
    d.observe = canvas
    d.parse_result = {'regions': [{'id': 't%d' % i, 'kind': 'text', 'text': t, 'bounds': {'x': 5, 'y': 10 + 30 * i, 'width': 50, 'height': 20}} for i, t in enumerate(['Save', 'Export', 'Reset'])]}
    class Picks(fx.NamedChooser):
        def __call__(self, step, request):self.requests.append(request);return {'choice': 't1', 'route': 'julia-1', 'action_authorized': True}
    out['canvas_regions'] = run(d, 'Press "Export"', {'expect': 'Exported'}, chooser=Picks())
    many = [('Provider %03d' % i, 'Follow-up', '30 min', '1:%02d PM' % (i % 60)) for i in range(80)]
    d = fx.FlatDriver();d.rows = fx.booking_rows(many);d.confirm_text = 'Booked Provider 041 1:41 PM'
    out['large_page_400'] = run(d, 'Book Provider 041', {'records': records([{'field': 'provider', 'value': 'Provider 041'}]), 'expect': 'Booked Provider 041'})
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
