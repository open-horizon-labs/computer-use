"""DOM-first page text for cua_look, bounded, beside the AX tree (CE-FACADE-007 slice 2, #33, #29).

A window bound to a browser tab has two readable sources: the native AX tree (what cua_do acts on) and the Driver's CDP semantic snapshot
(get_browser_state, snapshot_format semantic_v2: page.url/title, outline, refs, content_refs, snapshot.complete, omitted counts, continuation;
trycua/cua docs reference/cua-driver/browser-semantic-snapshots). The look reads both and never silently prefers one:

- every semantic call carries an explicit Driver timeout (SEMANTIC_TIMEOUT_S) inside a total budget (SEMANTIC_BUDGET_S); #29 measured a
  120 s semantic call with no output. A timeout, a refusal or any other Driver failure degrades the look to the AX tree with a note and a
  typed `degraded` value. It is never a transport failure and never retried (a retry would double the wait);
- a line the DOM shows inside a record the AX tree omits (eBay prices missing from AX) is added to that record as `dom_lines`, and
  `sources_disagree` counts what differs in each direction. `dom_lines` are read-only evidence: they are NOT part of look_id and a
  where.lines filter never matches them (the executor acts on the AX path and can only re-prove AX lines);
- the AX records and lines are never dropped or reordered because the DOM is present.

The outline grammar is inferred from the documented example (`- heading "Message"`, two-space nesting); an unparsable outline yields no DOM
lines (reported), never a guess.
"""
from __future__ import annotations

import re

import browser
import look as lk

SEMANTIC_TIMEOUT_S = 6.0    # hard Driver timeout of ONE semantic call: well under the 20 s Driver default and the 120 s of #29
SEMANTIC_BUDGET_S = 10.0    # all semantic calls of ONE look (bind, snapshot, continuations)
MAX_SEGMENTS = 3            # the snapshot plus at most two continuations
DOM_LINE_MAX = 6            # dom_lines shown per record
GROUP_CLIMB = 4             # ancestors searched when placing a DOM-only line in a record
UNPLACED_MAX = 10

OUTLINE_LINE = re.compile(r'^(?P<indent>\s*)-\s+(?P<role>[A-Za-z][\w-]*)(?:\s+"(?P<name>(?:[^"\\]|\\.)*)")?(?P<rest>.*)$')


def _failure(code, note):
    return {'ok': False, 'degraded': code, 'note': note}


def _call(f, args, timeout):
    """One bounded semantic Driver call: ({'value': dict} | {'degraded': code, 'note': text}). No retry, no session restart."""
    from core import DriverCallFailed, Gap
    try:
        value = f.driver.call('get_browser_state', {'session': f.session, **args}, timeout=timeout)
    except DriverCallFailed as error:
        if error.kind == 'timeout':
            return _failure('semantic_timeout', 'the page text was read from the accessibility tree only: the browser semantic snapshot did not answer within %gs' % timeout)
        return _failure('semantic_failed', 'the page text was read from the accessibility tree only: the browser semantic snapshot call failed (%s)' % (error.kind or 'error'))
    except Gap as error:
        code = browser._refusal_code(error) or 'refused'
        return _failure('semantic_refused', 'the page text was read from the accessibility tree only: the Driver refused the browser semantic snapshot (%s)' % code[:60])
    if isinstance(value, dict) and (value.get('refusal') or value.get('status') == 'refused'):
        code = str((value.get('refusal') or {}).get('code', 'refused'))
        return _failure('semantic_refused', 'the page text was read from the accessibility tree only: the Driver refused the browser semantic snapshot (%s)' % code[:60])
    return {'value': value if isinstance(value, dict) else {}}


def _tab_of(bound):
    """The window's tab, exact-or-none: the active one, the only one, or the one whose title the window's own title shows. Never a guess."""
    tabs = browser._tabs(bound)
    active = [t for t in tabs if t.get('active') or t.get('selected')]
    if len(active) == 1:
        return active[0]
    if not active and len(tabs) == 1:
        return tabs[0]
    native = bound.get('native_title') or ''
    titled = [t for t in tabs if browser._titled(native, t.get('title') or '')]
    return titled[0] if len(titled) == 1 and not active else None


def read(f, pid, window_id):
    """Read the window's page through the Driver's CDP binding, bounded. Returns
    {'ok': True, 'page', 'outline', 'names', 'complete', 'omitted', 'segments', 'refs'} or {'ok': False, 'degraded': code|None, 'note': text|None}.
    degraded None means the window is not a browser-bound page (no bind answer): nothing to report, the look is AX only as before."""
    began = f.clock()
    def remaining():
        return SEMANTIC_BUDGET_S - (f.clock() - began)
    bound = _call(f, {'pid': pid, 'window_id': window_id}, min(SEMANTIC_TIMEOUT_S, remaining()))
    if 'value' not in bound:
        return {'ok': False, **{k: bound[k] for k in ('degraded', 'note')}}
    bound = bound['value']
    if not bound.get('target_id'):
        return {'ok': False, 'degraded': None, 'note': None}
    tab = _tab_of(bound)
    if tab is None:
        return _failure('semantic_refused', 'the page text was read from the accessibility tree only: the window is bound to %d tabs and none is exactly the window\'s own' % len(browser._tabs(bound)))
    outline, names, refs, page, omitted, complete, segments = [], [], 0, {}, {}, False, 0
    args = {'target_id': bound['target_id'], 'tab_id': tab['tab_id'], 'snapshot_format': 'semantic_v2'}
    while segments < MAX_SEGMENTS:
        left = remaining()
        if left <= 0:
            break
        got = _call(f, args, min(SEMANTIC_TIMEOUT_S, left))
        if 'value' not in got:
            if segments == 0:
                return {'ok': False, **{k: got[k] for k in ('degraded', 'note')}}
            break  # a later segment failed: what was read stays, and it is reported as incomplete
        value = got['value']
        snap = value.get('snapshot') if isinstance(value.get('snapshot'), dict) else {}
        if segments == 0:
            page = value.get('page') if isinstance(value.get('page'), dict) else {}
            omitted = {k: v for k, v in (snap.get('omitted') or {}).items() if isinstance(v, int) and v}
        segments += 1
        if isinstance(value.get('outline'), str):
            outline.append(value['outline'])
        for item in list(value.get('content_refs') or []) + list(value.get('refs') or []):
            if isinstance(item, dict):
                refs += 1
                for key in ('name', 'value'):
                    if isinstance(item.get(key), str) and item[key].strip():
                        names.append(item[key])
        complete = snap.get('complete') is True and not snap.get('continuation')
        nxt = snap.get('continuation')
        if complete or not isinstance(nxt, str) or not nxt:
            break
        args = {'target_id': bound['target_id'], 'tab_id': tab['tab_id'], 'snapshot_format': 'semantic_v2', 'continuation': nxt}
    if segments == 0:
        return _failure('semantic_timeout', 'the page text was read from the accessibility tree only: the browser semantic snapshot budget (%gs) ran out before it answered' % SEMANTIC_BUDGET_S)
    if not ''.join(outline).strip() and not names:
        return _failure('semantic_empty', 'the page text was read from the accessibility tree only: the browser semantic snapshot held no page text')
    return {'ok': True, 'page': {'url': str(page.get('url') or '')[:200], 'title': str(page.get('title') or '')[:120]}, 'outline': '\n'.join(outline),
            'names': names, 'complete': complete, 'omitted': omitted, 'segments': segments, 'refs': refs}


def parse_outline(text):
    """[{'depth', 'role', 'text': [strings], 'parent'}] from the semantic outline (two-space nesting). Lines that do not parse are skipped and counted by the caller."""
    nodes, stack = [], []
    for raw in (text or '').split('\n'):
        match = OUTLINE_LINE.match(raw.rstrip())
        if not match:
            continue
        depth = len(match.group('indent').replace('\t', '  ')) // 2
        texts = []
        if match.group('name'):
            texts.append(lk.clean(match.group('name').replace('\\"', '"')))
        rest = match.group('rest') or ''
        tail = re.match(r'^\s*:\s*(.+)$', rest)
        if tail and not tail.group(1).lstrip().startswith(('[', '{')):
            texts.append(lk.clean(tail.group(1)))
        while stack and nodes[stack[-1]]['depth'] >= depth:
            stack.pop()
        nodes.append({'depth': depth, 'role': match.group('role'), 'text': [t for t in texts if t], 'parent': stack[-1] if stack else None})
        stack.append(len(nodes) - 1)
    return nodes


def _subtree(nodes):
    kids = {}
    for i, n in enumerate(nodes):
        kids.setdefault(n['parent'], []).append(i)
    def under(i):
        out, todo = [], [i]
        while todo:
            j = todo.pop()
            out.append(j)
            todo.extend(kids.get(j, []))
        return out
    return under


def compare(analysis, semantic, ax_texts):
    """What the DOM shows that the AX look does not (placed in a record by the outline's own grouping, else unplaced), and what AX shows that the DOM lacks.

    Returns {'by_root': {root: [lines]}, 'unplaced': [lines], 'dom_only': n, 'ax_only': n, 'compared': n, 'unparsed': bool}. Pure: no Driver, no clock."""
    nodes = parse_outline(semantic['outline'])
    dom_texts = []
    for n in nodes:
        for t in n['text']:
            if t not in dom_texts:
                dom_texts.append(t)
    for t in semantic['names']:
        t = lk.clean(t)
        if t and t not in dom_texts:
            dom_texts.append(t)
    ax_blob = '\n'.join(ax_texts)
    dom_blob = '\n'.join(lk.norm(t) for t in dom_texts)
    covered = lambda t: lk.norm(t) in ax_blob or len(lk.norm(t)) < 2
    dom_only = [t for t in dom_texts if not covered(t)]
    records = analysis['records']
    by_root, unplaced, placed = {}, [], 0
    under = _subtree(nodes)
    rec_norm = {r['root']: {lk.norm(x) for x in r['lines']} for r in records}
    for text in dom_only:
        home = next((i for i, n in enumerate(nodes) if text in n['text']), None)
        root = None
        if home is not None:
            at, climbed = nodes[home]['parent'], 0
            while at is not None and climbed < GROUP_CLIMB and root is None:
                here = {lk.norm(t) for j in under(at) for t in nodes[j]['text']}
                scores = sorted(((len(rec_norm[r['root']] & here), r['root']) for r in records), reverse=True)
                if scores and scores[0][0] >= 2 and (len(scores) == 1 or scores[0][0] > scores[1][0]):
                    root = scores[0][1]
                at, climbed = nodes[at]['parent'], climbed + 1
        if root is None:
            unplaced.append(text)
        else:
            by_root.setdefault(root, []).append(text)
            placed += 1
    compared = sum(len(r['lines']) for r in records)
    ax_only = sum(1 for r in records for line in r['lines'] if len(lk.norm(line)) >= 2 and lk.norm(line) not in dom_blob)
    return {'by_root': by_root, 'unplaced': unplaced, 'dom_only': len(dom_only), 'placed': placed, 'ax_only': ax_only, 'compared': compared, 'unparsed': bool(semantic['outline'].strip()) and not nodes}


def ax_text_blob(f, state, analysis):
    """Every text the AX look can show (record lines, page text, headings, dialogs, control labels), normalised: what a DOM string is compared against."""
    parts = [x for r in analysis['records'] for x in r['lines']] + list(analysis['text']) + list(analysis['headings']) + list(analysis['header']) + list(analysis['other_controls'])
    for d in analysis['dialogs']:
        parts += d['lines'] + d['controls']
    nodes = state['nodes']
    parts += [lk.text_of(nodes[i]) for i in analysis['ctrl_ids'] if lk.text_of(nodes[i])]
    return [lk.norm(p) for p in parts if p]
