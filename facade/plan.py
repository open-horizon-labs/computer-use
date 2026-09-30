"""cua_do plans (option B, CE-FACADE-005): LOOK, then PLAN ONCE, then a deterministic executor.

A plan is a short list of steps the driving LLM writes after seeing the page (cua_look). The server validates the whole plan before
any Driver action, then executes step by step. Each step is one run of the existing single-step machinery (`Facade._do`): a fresh
observation, discovery, filter, bind, act with scope revalidation, per-step recovery (a stale refusal re-runs THAT step with a NEW
selection; a click is never retried), verification by `expect`. Nothing is shared between steps except the window and, for an explicit
confirm step, the identity of the record the previous press selected. The first step that is not done stops the plan.

The one new safety rule is the look_id: a filter over displayed lines (`where.lines`) is allowed only against a look the caller
actually made of THIS window, and only while the page still reads the same. No filter without sight.
"""
from __future__ import annotations

import copy
import json
import re
import uuid

import look as lk

MAX_STEPS = 10
STEP_KEYS = frozenset({'do', 'goal', 'where', 'control', 'control_match', 'near', 'identity', 'text', 'expect', 'treat_as_match', 'accept_unknown', 'confirm', 'allow_destructive', 'dialog_text', 'dialog_controls', 'accept_hidden_text', 'allow_foreground', 'url'})
WHERE_KEYS = frozenset({'lines', 'fields', 'predicates'})
DO_KINDS = ('press', 'type', 'confirm', 'verify', 'goto', 'open_tab', 'close_tab')
LINE_OPS = ('contains', 'eq', 'not_contains', 'neq')
MAX_CONDITIONS = 6
MAX_VALUE_CHARS = 60
RESPONSE_BYTES = 5800
# The destructive-verb guard of option D, applied to plans: a control whose label carries one of these needs the plan's own goal to say so.
# A FLOOR, not a definition: stems (case/space-insensitive) of labels that need the step's own allow_destructive. It cannot be complete (every language and
# phrasing needs another entry), so the real backstop for anything that opens a dialog is the confirm step's dialog_text whitelist. Do not extend it to pass a probe.
DESTRUCTIVE = {'delete': r'\bdelet', 'remove': r'\bremov(?:e|es|ing)\b', 'erase': r'\beras', 'discard': r'\bdiscard', 'reset': r'\breset', 'clear': r'\bclear', 'wipe': r'\bwip(?:e|ing)',
               'purge': r'\bpurg', 'drop': r'\bdrop(?!\s*-?down)', 'destroy': r'\bdestroy', 'uninstall': r'\buninstall',
               'empty trash': r'\bempty\s+(?:the\s+)?(?:trash|bin|recycle)', 'move to trash': r'\bmove\s+to\s+(?:the\s+)?(?:trash|bin|recycle)',
               'overwrite': r'\boverwrit', 'deactivate': r'\bdeactivat', 'terminate': r'\bterminat', 'revoke': r'\brevok', 'unsubscribe': r'\bunsubscrib',
               'disconnect': r'\bdisconnect(?:s|ing)?\b', 'close account': r'\bclos\w*\s+(?:(?:my|the|your|this)\s+)?account', 'cancel subscription': r'\bcancel\w*\s+(?:(?:my|the|your|this)\s+)?subscription',
               'log out': r'\blog(?:ging|ged)?[ -]?out', 'sign out': r'\bsign(?:ing|ed)?[ -]?out',
               # irreversible or outward-facing
               'buy': r'\bbuy(?:ing)?\b', 'purchase': r'\bpurchas', 'pay': r'\bpay(?:ing)?\b', 'send': r'\bsend(?:ing)?\b', 'publish': r'\bpublish', 'transfer': r'\btransfer', 'refund': r'\brefund',
               'void': r'\bvoid\b', 'submit order': r'\bsubmit\s+(?:my\s+|the\s+)?order', 'place order': r'\bplace\s+(?:my\s+|the\s+)?order', 'confirm payment': r'\bconfirm\s+(?:the\s+)?payment'}


def destructive_verbs(label):
    """Destructive verbs in a control label, matched on FOLDED text (NFKC, zero-width and diacritics stripped, casefold, Cyrillic/Greek look-alikes mapped to Latin).
    Goal text NEVER unlocks one (a goal is a regex target for a negation or an injected sentence): only the step's own allow_destructive naming the exact label does."""
    folded = lk.fold(label)
    return [v for v, rx in DESTRUCTIVE.items() if re.search(rx, folded)]


def allowed(step_allow, label):
    return bool(step_allow) and lk.fold(step_allow) == lk.fold(label)


def _gap(message):
    from core import Gap
    return Gap(message)


# --- validation: everything that can be decided without the Driver, before any Driver action -------------------------------------

def validate(f, goal, title, pid, window_id, steps, look_id, abort_if, budget_s, expect, single):
    """Return the normalized steps or raise Gap('<reason>: ...'). No Driver call, no model, no clock."""
    if not isinstance(goal, str) or not goal.strip():
        raise _gap('bad_request: goal is required (the plan\'s goal, in words)')
    f.reject_answer_leak({'nodes': {int(m): 0 for m in f.OBSERVED_ID.findall(goal)}}, goal)
    if not isinstance(steps, list) or not steps:
        raise _gap('bad_request: steps must be a nonempty list')
    if len(steps) > MAX_STEPS:
        raise _gap('bad_request: a plan has at most %d steps (got %d); split it and call cua_do again for the rest' % (MAX_STEPS, len(steps)))
    used = [k for k, v in single.items() if v is not None and not (k == 'operation' and v == 'click')]
    if used:
        raise _gap('bad_request: steps cannot be combined with %s; put them on the steps (a single step is a one-step plan)' % ', '.join(sorted(used)))
    if expect is not None:
        raise _gap('bad_request: with steps, expect belongs on each step; pass expect=null at the top level')
    if title is not None and (pid is not None or window_id is not None):
        raise _gap('bad_request: give title or pid+window_id, not both')
    if title is None and (pid is None or window_id is None):
        raise _gap('bad_request: supply title, or pid and window_id')
    if not isinstance(budget_s, (int, float)) or isinstance(budget_s, bool) or budget_s <= 0:
        raise _gap('bad_request: budget_s must be positive seconds')
    if abort_if is not None and (not isinstance(abort_if, str) or not abort_if.strip() or len(abort_if) > 200):
        raise _gap('bad_request: abort_if must be nonempty text of at most 200 characters')
    if look_id is not None and (not isinstance(look_id, str) or not look_id.strip()):
        raise _gap('bad_request: look_id is the id cua_look returned')
    out, needs_look = [], False
    for n, raw in enumerate(steps, 1):
        at = 'step %d' % n
        if not isinstance(raw, dict):
            raise _gap('bad_request: %s must be an object' % at)
        unknown = sorted(set(raw) - STEP_KEYS)
        if unknown:
            raise _gap('bad_request: %s has unknown keys %s' % (at, ', '.join(unknown)))
        step = {k: v for k, v in raw.items() if v is not None}
        kind = step.get('do')
        if kind not in DO_KINDS:
            raise _gap('bad_request: %s do=%r is not one of %s' % (at, kind, ', '.join(DO_KINDS)))
        final = n == len(steps)
        for key in ('goal', 'control', 'near', 'text', 'confirm', 'expect', 'allow_destructive'):
            if key in step and (not isinstance(step[key], str) or (key != 'text' and not step[key].strip())):
                raise _gap('bad_request: %s %s must be nonempty text' % (at, key))
        if 'accept_hidden_text' in step and step['accept_hidden_text'] is not True:
            raise _gap('bad_request: %s accept_hidden_text is true (an explicit acknowledgement) or absent' % at)
        if 'allow_foreground' in step and step['allow_foreground'] is not True:
            raise _gap('bad_request: %s allow_foreground is true (an explicit permission to front the window briefly) or absent' % at)
        if kind == 'confirm':
            declared = step.get('dialog_text')
            if not isinstance(declared, list) or not declared or not all(isinstance(x, str) and x.strip() for x in declared) or len(declared) > 20:
                raise _gap('bad_request: %s (confirm) needs dialog_text: the COMPLETE text lines of the dialog you expect (1 to 20 texts); nothing is pressed unless the dialog shows exactly them. The dialog text is usually unknown until it appears: a first confirm that misses defers with the actual lines' % at)
            controls = step.get('dialog_controls')
            if not isinstance(controls, list) or not controls or not all(isinstance(x, str) and x.strip() for x in controls) or len(controls) > 20:
                raise _gap('bad_request: %s (confirm) needs dialog_controls: the EXACT list of the dialog\'s control labels (1 to 20), each with its state when it has one, for example "Also delete my account [checked]"; an undeclared control or state defers' % at)
            bare = {lk.norm(re.sub(r'\s*\[[a-z ]+\]\s*$', '', x)) for x in controls}
            if lk.norm(step.get('confirm')) not in bare:
                raise _gap('bad_request: %s (confirm) label %r must be one of dialog_controls' % (at, str(step.get('confirm'))[:40]))
        if step.get('control_match', 'exact') not in ('exact', 'prefix'):
            raise _gap('bad_request: %s control_match is exact (the default) or prefix' % at)
        if 'goal' in step:
            f.reject_answer_leak({'nodes': {int(m): 0 for m in f.OBSERVED_ID.findall(step['goal'])}}, step['goal'])
        for key in ('treat_as_match', 'accept_unknown'):
            if key in step and (not isinstance(step[key], list) or not step[key] or not all(isinstance(x, str) and x for x in step[key])):
                raise _gap('bad_request: %s %s must be a list of record ids' % (at, key))
        takes = {'press': {'do', 'goal', 'where', 'control', 'control_match', 'near', 'identity', 'expect', 'treat_as_match', 'accept_unknown', 'allow_destructive', 'accept_hidden_text', 'allow_foreground'},
                 'type': {'do', 'goal', 'control', 'control_match', 'text', 'expect', 'allow_destructive'},
                 'confirm': {'do', 'goal', 'confirm', 'identity', 'expect', 'allow_destructive', 'dialog_text', 'dialog_controls'},
                 'verify': {'do', 'goal', 'expect'},
                 'goto': {'do', 'goal', 'url', 'expect'},
                 'open_tab': {'do', 'goal', 'url', 'expect'},
                 'close_tab': {'do', 'goal', 'expect', 'allow_foreground'}}[kind]
        extra = sorted(set(step) - takes)
        if extra:
            raise _gap('bad_request: %s (%s) does not take %s' % (at, kind, ', '.join(extra)))
        if kind == 'verify' and 'expect' not in step:
            raise _gap('expect_required: %s is a verify step and needs expect (visible page text)' % at)
        if kind not in ('verify', 'close_tab') and 'expect' not in step and not final:
            raise _gap('expect_required: %s needs expect: the page text that will be visible once it worked (null is allowed only on the last step, which then ends delivered_unverified)' % at)
        if kind == 'press':
            if 'where' not in step and 'control' not in step:
                raise _gap('bad_request: %s (press) needs control (the exact button label) and/or where (which record)' % at)
        if kind == 'type':
            if 'control' not in step or 'text' not in step:
                raise _gap('bad_request: %s (type) needs control (the field\'s label) and text' % at)
        if kind in ('goto', 'open_tab'):
            import browser
            if 'url' not in step:
                raise _gap('bad_request: %s (%s) needs url (http or https)' % (at, kind))
            try:
                step['url'] = browser.check_url(step['url'])
            except Exception as error:
                raise _gap(str(error).replace('bad_request: ', 'bad_request: %s ' % at, 1))
        if kind == 'confirm':
            if 'confirm' not in step:
                raise _gap('bad_request: %s (confirm) needs confirm=<the exact label of the dialog control>' % at)
            if n == 1 or steps[n - 2].get('do') != 'press':
                raise _gap('bad_request: %s (confirm) must directly follow a press step that opens the dialog' % at)
        where = step.get('where')
        step['where_kind'] = None
        if where is not None:
            if not isinstance(where, dict):
                raise _gap('bad_request: %s where must be an object' % at)
            if sorted(set(where) - WHERE_KEYS):
                raise _gap('bad_request: %s where has unknown keys %s' % (at, ', '.join(sorted(set(where) - WHERE_KEYS))))
            if bool(where.get('lines')) == bool(where.get('fields')):
                raise _gap('bad_request: %s where takes EITHER lines (conditions over the displayed lines, after cua_look) OR fields (+ predicates)' % at)
            if where.get('lines'):
                if 'predicates' in where:
                    raise _gap('bad_request: %s where.predicates go with where.fields, not where.lines' % at)
                conds = where['lines']
                if not isinstance(conds, list) or not 1 <= len(conds) <= MAX_CONDITIONS:
                    raise _gap('bad_request: %s where.lines takes 1 to %d conditions' % (at, MAX_CONDITIONS))
                for cond in conds:
                    if not isinstance(cond, dict) or set(cond) != {'line', 'value'} or cond['line'] not in LINE_OPS \
                            or not isinstance(cond['value'], str) or not cond['value'].strip() or len(cond['value']) > MAX_VALUE_CHARS:
                        raise _gap('bad_request: %s where.lines conditions are {line: %s, value: <text of at most %d characters>}' % (at, '|'.join(LINE_OPS), MAX_VALUE_CHARS))
                step['where_kind'] = 'lines'
                needs_look = True
            else:
                if any(k not in ('fields', 'predicates') for k in where):
                    raise _gap('bad_request: %s where.fields takes fields and predicates' % at)
                f._do_records({'fields': where['fields'], 'predicates': where.get('predicates')})  # the existing validation
                step['where_kind'] = 'fields'
        identity = step.get('identity')
        if identity is not None:
            if not isinstance(identity, list) or not identity or not all(isinstance(x, str) and x.strip() for x in identity):
                raise _gap('bad_request: %s identity must be a nonempty list of texts' % at)
            if step['where_kind'] == 'fields':
                if any(x not in where['fields'] for x in identity):
                    raise _gap('bad_request: %s identity must name fields from where.fields' % at)
            elif any(len(x) > MAX_VALUE_CHARS for x in identity):
                raise _gap('bad_request: %s identity texts are at most %d characters' % (at, MAX_VALUE_CHARS))
            elif kind == 'press' and step['where_kind'] is None:
                raise _gap('bad_request: %s identity needs a where (which record it identifies)' % at)
        # The destructive guard, on the LITERAL label here and again on the RESOLVED control at execution.
        for label in (step.get('control') if kind in ('press', 'type') else None, step.get('confirm')):
            bad = destructive_verbs(label) if label else []
            if bad and not allowed(step.get('allow_destructive'), label):
                raise _gap('destructive_control: %s control %r is destructive (%s); goal text never authorizes it. Only the step itself can: add allow_destructive=%r (the exact label) to that step if it is what the user asked for' % (at, label[:40], ', '.join(bad), label[:40]))
        out.append(step)
    if look_id is not None and not any(key[2] == look_id for key in f.looks):
        raise _gap('unknown_look_id: no cua_look returned %r in this session (or it is too old); call cua_look first and pass the look_id it returns' % look_id[:24])
    if needs_look:
        if look_id is None:
            raise _gap('look_required: where.lines filters over displayed lines, and a filter written without seeing the page is how the wrong record gets clicked; call cua_look first and pass its look_id')
        if not any(key[2] == look_id for key in f.looks):
            raise _gap('unknown_look_id: no cua_look returned %r in this session (or it is too old); call cua_look first and pass the look_id it returns' % look_id[:24])
    return out


# --- the lines-where stage inside one step ---------------------------------------------------------------------------------------

def cond_ok(lines, cond):
    value = lk.norm(cond['value'])
    op = cond['line']
    if op == 'contains':
        return any(value in line for line in lines)
    if op == 'eq':
        return any(line == value for line in lines)
    if op == 'not_contains':
        return not any(value in line for line in lines)
    return not any(line == value for line in lines)  # neq


def default_identity(conds):
    """The strings a dialog must display for it to be this record's dialog: the values the plan required to be present."""
    return list(dict.fromkeys(lk.clean(c['value']) for c in conds if c['line'] in ('eq', 'contains')))


def look_matches(f, state, look, look_id):
    """Does the CURRENT observation still read the way the look showed it (title, headings, every control's state, FULL lines of the displayed records)?"""
    analysis = lk.analyze(f, state)
    rows, _, _ = lk.select(analysis, look['terms'], cap=look['n'], opts=look.get('opts', lk.DEFAULT_OPTS))
    return lk.view_id(rows, state['raw'].get('window_title'), analysis) == look_id, analysis


def lines_stage(f, state, snapshot, spec, roots, targets, disabled_roots):
    """Resolve `where.lines` for one step on the CURRENT observation. Returns {'defer': {...}} or {'reading': ..., 'pick': ...}.

    1. The page must still read the way the look showed it: window title, headings, every page control's state and the FULL lines of the displayed
       records are hashed (look_id). A mismatch, including text hidden past the display cut or a flipped checkbox, defers page_changed_since_look.
    2. UNIQUENESS is decided over ALL records of the fresh observation, never only the ones the look displayed (a capped or focused look must not turn an
       ambiguous condition into a click): more than one match stops where_matches_several. A single match the look did not display stops too.
    3. Negative conditions (not_contains, neq) are refused for any record whose lines were cut or omitted.
    4. Selecting a record that had cut or omitted lines needs the step's accept_hidden_text (a shown positive match cannot rule out a contradicting hidden line).
    5. One match binds; none or several defer with the lines (never the chooser)."""
    look = spec['look']
    opts = look.get('opts', lk.DEFAULT_OPTS)
    same, analysis = look_matches(f, state, look, spec['look_id'])
    if not same:
        return {'defer': {'reason': 'page_changed_since_look', 'found': {'records': len(analysis['records']), 'record_kind': analysis['kind']}}}
    rows_look, _, _ = lk.select(analysis, look['terms'], cap=look['n'], opts=opts)
    displayed = {r['rec']['root'] for r in rows_look}
    every, _, _ = lk.select(analysis, [], cap=None, opts=opts)
    visible = {r['rec']['root']: r for r in every}  # ALL records: uniqueness is a property of the page, not of the look
    candidates = [r for r in roots if int(r[1:]) in visible]
    outside = len([r for r in roots if int(r[1:]) not in displayed])
    lines_of = lambda r: [lk.norm(x) for x in visible[int(r[1:])]['lines']]
    positive = [c for c in spec['conditions'] if c['line'] in ('eq', 'contains')]
    negative = [c for c in spec['conditions'] if c['line'] not in ('eq', 'contains')]
    candidates_pos = [r for r in candidates if all(cond_ok(lines_of(r), c) for c in positive)]
    if negative:
        hidden = [visible[int(r[1:])]['r'] for r in candidates_pos if visible[int(r[1:])]['lost']]
        if hidden:
            return {'defer': {'reason': 'negative_condition_over_cut_lines', 'evidence': {'records_with_cut_or_omitted_lines': hidden[:8], 'count': len(hidden)}}}
    matched = [r for r in candidates_pos if all(cond_ok(lines_of(r), c) for c in negative)]
    shown_matches = [r for r in matched if int(r[1:]) in displayed]
    if len(matched) != 1 or len(shown_matches) != 1:
        shown = [{'lines': visible[int(r[1:])]['lines']} for r in shown_matches[:5]]
        return {'defer': {'reason': 'no_matching_record' if len(matched) < 2 else 'where_matches_several', 'excluded_count': len(candidates) - len(matched),
                          'evidence': {'matches': shown, 'match_count': len(shown_matches) if len(matched) < 2 else len(matched), 'displayed_matches': len(shown_matches),
                                       **({'outside_look': outside} if outside else {})}}}
    only = matched[0]
    if visible[int(only[1:])]['lost'] and not spec.get('accept_hidden'):
        return {'defer': {'reason': 'selected_record_has_hidden_text', 'evidence': {'record': visible[int(only[1:])]['r'], 'hidden_lines': visible[int(only[1:])]['lost']}}}
    if only in disabled_roots:
        return {'defer': {'reason': 'record_disabled', 'disabled_count': 1}}
    if only not in targets:
        return {'defer': {'reason': 'control_not_found', 'missing_count': 1}}
    sid = state['raw']['snapshot_id']
    fields = {'lines': {'description': 'the displayed lines of the record', 'type': 'text'}}
    records = [{'record_id': r, 'fields': {'lines': ' | '.join(visible[int(r[1:])]['lines'])}} for r in candidates]
    filt = {'snapshot_id': sid, 'eligible_ids': [only], 'unknown_ids': [], 'excluded_ids': [r for r in candidates if r != only],
            'checks': {r: {'state': 'eligible' if r == only else 'excluded', 'failed': [], 'gaps': []} for r in candidates},
            'coverage_complete': True, 'complete': True}
    handle = 'read_' + uuid.uuid4().hex
    reading = {'reading': handle, 'snapshot': snapshot, 'route': 'deterministic_lines',
               'extraction': {'snapshot_id': sid, 'model': 'deterministic_lines', 'records': records, 'calibrated': False}, 'filter': filt}
    f.readings[handle] = copy.deepcopy({**reading, 'fields': fields, 'predicates': [], 'record_ids': list(candidates)})
    while len(f.readings) > 32:
        f.readings.pop(next(iter(f.readings)))
    f.event('read', route='deterministic_lines', snapshot=snapshot, records=len(candidates), endpoint_ms=0)
    return {'reading': reading, 'pick': {'record_actions': {only: targets[only]}}}


def token_in(text, wanted):
    """`wanted` as a WHOLE token: not adjacent to an alphanumeric character, '#', '_' or '-', and not followed by '.'/',' and a digit (so #1044 is none of
    #10441, ##1044, #1044-A, #1044_x, #1044.5, #1044,5). A sanity check on top of the declared dialog text, never the authorization."""
    w = lk.norm(wanted)
    return bool(w) and re.search(r'(?<![a-z0-9#_.,-])' + re.escape(w) + r'(?![a-z0-9#_-])(?![.,]\d)', text) is not None


def identity_state(dialog_text, wanted):
    """('matched'|'partial'|'unknown', shown, not_shown): every wanted string must be a whole token of the dialog's lines. It says nothing about intent
    (a dialog "Do not cancel order #1044" matches): the caller's declared dialog_text is what authorizes a confirm. Deterministic, no reader."""
    lines = [l.strip() for l in (dialog_text or '').split('\n') if l.strip()]
    shown = [w for w in wanted if any(token_in(lk.norm(l), w) for l in lines)]
    missing = [w for w in wanted if w not in shown]
    return ('matched' if wanted and not missing else ('partial' if shown else 'unknown')), shown, missing


# --- hints: only cua_look / cua_do parameters, never a primitive ----------------------------------------------------------------

HINTS = {
    'page_changed_since_look': 'The page no longer reads the way the look showed it, so a filter over its lines is not safe; nothing was clicked by step %(n)d. Call cua_look again, then cua_do with the new look_id and steps from step %(n)d on.',
    'no_matching_record': 'No record shown by the look satisfies step %(n)d where.lines (see steps[].evidence.match_count and the lines in cua_look). Nothing was clicked by this step. Correct the conditions against the strings cua_look showed (a duration may read "half-hour"), then call cua_do with the steps from step %(n)d on.',
    'where_matches_several': 'Several records satisfy step %(n)d where.lines (evidence.matches shows their lines); nothing was guessed or clicked by this step. Add a condition that only the one you mean satisfies, then call cua_do with the steps from step %(n)d on.',
    'control_needed': 'Each record has several controls (see found.repeated_controls). Set control on step %(n)d to the exact label of the one to press, then call cua_do with the steps from step %(n)d on.',
    'control_not_found': 'No control matches step %(n)d (found.controls lists what is pressable). Nothing was clicked by this step. Call cua_look, then cua_do with a corrected control from step %(n)d on.',
    'control_ambiguous': 'Several controls match step %(n)d; nothing was guessed. Set control to the exact full label, then call cua_do with the steps from step %(n)d on.',
    'control_not_pressable': 'The control of step %(n)d is present but not pressable right now; nothing was clicked by this step. Call cua_look, then cua_do with the steps from step %(n)d on.',
    'records_ambiguous': 'The records on this page cannot be told apart without guessing; nothing was clicked by step %(n)d. Call cua_look for the controls on the page, then give step %(n)d control=<the exact button label>.',
    'record_disabled': 'The record step %(n)d selects is disabled, so its control cannot be pressed; nothing was clicked by this step. Report that it is unavailable, or call cua_look and choose another record.',
    'confirm_dialog_present': 'The step\'s click is done and a dialog is showing (see steps[].dialog.controls); nothing in it was pressed and the dialog was not an expected outcome. Do not repeat the click. To press a dialog control call cua_do with steps=[{do:"press", control:<one of dialog.controls, exact>, expect:<text that will be visible once it is done>}].',
    'confirm_dialog_not_found': 'Step %(n)d found no new dialog after the previous step; nothing was clicked by this step. Call cua_look to see what the page shows now.',
    'confirm_dialog_ambiguous': 'A dialog was already open, was replaced, or several appeared, or several controls carry that label; nothing was clicked by step %(n)d. Call cua_look to see what the page shows now.',
    'confirm_needs_identity': 'Step %(n)d has no complete identity to check the dialog against, and the previous step\'s click is already done, so nothing further was pressed. Read dialog.lines: if it is the right record\'s dialog, call cua_do with steps=[{do:"press", control:<one of dialog.controls, exact>, expect:<text that will be visible once it is done>}]; otherwise stop and report it. Next time give the press step identity=[<texts the dialog displays>].',
    'confirm_identity_partial': 'The dialog shows only part of the record identity (identity_shown and identity_not_shown count the strings), and the previous step\'s click is already done, so nothing further was pressed by step %(n)d. Read dialog.lines: if it is the right record\'s dialog, call cua_do with steps=[{do:"press", control:<one of dialog.controls, exact>, expect:<text that will be visible once it is done>}]; otherwise stop and report it. Next time give the press step identity=[<texts the dialog displays, e.g. the order number>].',
    'confirm_identity_unknown': 'The dialog does not display the identity of the selected record, and the previous step\'s click is already done, so nothing further was pressed by step %(n)d. Read dialog.lines: if it is the right record\'s dialog, call cua_do with steps=[{do:"press", control:<one of dialog.controls, exact>, expect:<text that will be visible once it is done>}]; otherwise stop and report it. Next time give the press step identity=[<texts the dialog displays>].',
    'confirm_control_not_found': 'The dialog has no control labelled exactly as step %(n)d confirm (dialog.controls lists them); nothing was clicked by this step. Call cua_do with the exact label.',
    'destructive_control': 'The control step %(n)d names or resolved to is destructive; goal text never authorizes it and nothing was clicked by this step. If the user asked for it, call cua_do again with allow_destructive=<the exact control label> on that step.',
    'negative_condition_over_cut_lines': 'Step %(n)d uses not_contains or neq over records whose lines were cut or omitted in the look (steps[].evidence.records_with_cut_or_omitted_lines): absence cannot be shown over text nobody saw. Nothing was clicked by this step. Use positive conditions (eq, contains) that single the record out, or call cua_look with focus so the record fits, then call cua_do with the steps from step %(n)d on.',
    'selected_record_has_hidden_text': 'The record step %(n)d selects had lines cut or omitted in the look (steps[].evidence.record, hidden_lines), so a line you never saw could contradict your conditions; nothing was clicked by this step. Call cua_look with max_lines and line_chars large enough to show the whole record and plan again, or, if you accept the risk, add accept_hidden_text=true to that step.',
    'toggle_state_unseen': 'Step %(n)d presses a checkbox, radio or switch, which flips its CURRENT state, and this plan carries no look_id of a look that saw that state; nothing was clicked by this step. Call cua_look, then cua_do with its look_id and an expect naming the resulting state.',
    'confirm_dialog_unexpected_text': 'The dialog\'s text is not exactly the dialog_text you declared (steps[].dialog.lines shows the ACTUAL lines), and the previous step\'s click is already done, so nothing further was pressed by step %(n)d. Read the lines: if this is the dialog the user\'s task calls for, call cua_do with steps=[{do:"press", control:<one of dialog.controls, exact>, expect:<text that will be visible once it is done>}]; otherwise stop and report it. Next time declare exactly those lines as dialog_text on the confirm step.',
    'delivery_unverified': 'Step %(n)d\'s click was delivered but its expect was not seen. Do not click again. Call cua_do with steps=[{do:"verify", expect:<page text that should be visible now>}] to check, or report the state.',
    'not_verified': 'The expect of the verify step was not established (control labels never count). Nothing was clicked. Call cua_do with a different expect, or report what cua_look shows.',
    'unknown_competitors_unacknowledged': 'Some records could not be compared with the predicates (step %(n)d unknown_ids and evidence.extracted show their strings). Call cua_do with the same steps and treat_as_match=<ids> on that step if you judge they DO match, or accept_unknown=<ids> if they do NOT. Nothing was clicked by this step.',
    'unknown_or_incomplete_scope': 'Some records could not be compared with the predicates (step %(n)d unknown_ids and evidence.extracted show their strings). Call cua_do with the same steps and treat_as_match=<ids> on that step if you judge they DO match, or accept_unknown=<ids> if they do NOT. Nothing was clicked by this step.',
    'no_eligible_record': 'No record satisfies step %(n)d where.predicates (evidence.extracted shows the strings read); nothing was clicked by this step. Call cua_look and correct the predicates.',
    'budget_exceeded': 'The plan ran out of time before step %(n)d finished; nothing further ran. If a click had landed, call cua_do with steps=[{do:"verify", expect:<text>}] to check; otherwise call cua_do with the remaining steps.',
    'record_changed': 'After a stale-UI refusal the fresh page selects a different record for step %(n)d; nothing was clicked by this step. Call cua_look, then cua_do again.',
    'record_changed_unverifiable': 'The page changed before step %(n)d\'s click and its record cannot be re-identified by its lines; nothing was clicked by this step. Call cua_look, then cua_do again.',
    'ui_changed_repeatedly': 'The page kept changing during step %(n)d; nothing was clicked by this step. Call cua_look, then cua_do again.',
    'web_area_ambiguous': 'The window holds several separate page areas; nothing was clicked. Close the extra one or give the exact title of the page window, then call cua_look.',
    'no_actionable_controls': 'Nothing pressable was found in the page content; nothing was clicked. Stop and report this to the user; do not retry.',
    'region_label_needed': 'This page has no pressable controls but text is drawn on it (found.region_texts). Give step %(n)d control=<the exact drawn text>, and near=<the text just above or left of it> when it is drawn more than once.',
    'region_ambiguous': 'Several drawn texts read the same; nothing was clicked by step %(n)d. Give step %(n)d near=<the text just above or left of the one you mean> (see the matches).',
    'region_uncorroborated': 'Another drawn text reads almost the same, so the label cannot be trusted; nothing was clicked by step %(n)d. Give near=<the text just above or left of the control> or report it.',
    'driver_call_failed': 'A Driver call failed (see delivery: none means nothing was clicked). If delivery is none call cua_do again; otherwise call cua_do with a verify step first.',
    'provider_failure': 'A specialist failed while running step %(n)d (see delivery). If delivery is none call cua_do again; otherwise call cua_do with a verify step first.',
}
GENERIC_HINT = 'Step %(n)d stopped and nothing further ran. Call cua_look to see the page now, then cua_do with the remaining steps (the earlier steps are already done; do not repeat them).'


def hint_for(reason, n, delivered):
    text = HINTS.get(reason, GENERIC_HINT) % {'n': n}
    if n > 1 and 'already done' not in text:
        text += ' Steps 1 to %d are already done; do not repeat them.' % (n - 1)
    return text


# --- the executor ----------------------------------------------------------------------------------------------------------------

def inside_records(state, index):
    """True for a text inside a table row or list (a record's own text is not the page's status text)."""
    nodes, seen, a = state['nodes'], {index}, state['nodes'][index].get('parent_index')
    while a in nodes and a not in seen:
        seen.add(a)
        if nodes[a].get('role') in ('AXRow', 'AXList'):
            return True
        a = nodes[a].get('parent_index')
    return False


def _summary(f, pid, window_id):
    state = f.snapshots.get(f.latest.get((pid, window_id)))
    if not state:
        return None
    content = f._content_ids(state) - f._column_copies(state) - set(state['aliases'])
    texts, controls = [], []
    for i in sorted(content):
        node = state['nodes'][i]
        if node.get('role') in f.CONTROL_ROLES:
            label = lk.clean(node.get('label'))
            if label and label not in controls and node.get('enabled') is not False:
                controls.append(label[:30])
        elif node.get('role') not in lk.NON_TEXT_ROLES and node.get('role') not in lk.INPUT_ROLES and lk.text_of(node) and not inside_records(state, i):
            line = lk.cut(lk.text_of(node))[0]
            if line not in texts:
                texts.append(line)
    return {'title': state['raw'].get('window_title'), 'text': texts[:6], 'controls': controls[:12]}


def _abort_hit(f, pid, window_id, abort_if, since):
    """abort_if in the fresh observation: text-bearing non-control content nodes only (a button label never counts)."""
    state = f.snapshots.get(f.latest.get((pid, window_id)))
    if not state or state['created'] < since:
        return False
    needle = lk.norm(abort_if)
    content = f._content_ids(state)
    return any(i in content and n.get('role') not in f.CONTROL_ROLES and needle in lk.norm(' '.join(str(n.get(k) or '') for k in ('label', 'value')))
               for i, n in state['nodes'].items())


def _fit(result):
    """Keep the response small: drop the most verbose optional detail first."""
    for drop in (('steps', 'evidence'), ('steps', 'found'), ('summary', 'text'), ('summary', 'controls')):
        if len(json.dumps(result)) <= RESPONSE_BYTES:
            break
        if drop[0] == 'steps':
            for entry in result['steps']:
                entry.pop(drop[1], None)
        elif result.get('summary'):
            result['summary'].pop(drop[1], None)
    return result


def run_plan(f, goal, title, pid, window_id, steps, look_id, abort_if, budget_s, expect, single):
    from core import Gap
    def refuse(gap):
        reason = f._do_reason(str(gap))
        message = lk.safe_message(reason, str(gap))
        hints = {'look_required': 'Call cua_look first, then cua_do with its look_id.', 'unknown_look_id': 'Call cua_look first, then cua_do with the look_id it returns.'}
        f.event('do_plan', status='refused', reason=reason, steps=0)
        return {'status': 'refused', 'reason': reason, 'message': message, 'steps': [], 'delivery': 'none', 'follow_up_needed': True,
                'hint': hints.get(reason, 'Correct the plan as the message says and call cua_do again; nothing was done.')}
    try:
        plan_steps = validate(f, goal, title, pid, window_id, steps, look_id, abort_if, budget_s, expect, single)
    except Gap as gap:
        return refuse(gap)
    t0 = f.clock()
    entries, delivery, failed, final = [], 'none', None, None
    ctx = {'pid': pid, 'window_id': window_id}
    carry = {'before': None, 'identity': None}
    for n, step in enumerate(plan_steps, 1):
        elapsed = f.clock() - t0
        remaining = 3 * budget_s - elapsed
        if remaining <= 0:
            failed = {'n': n, 'reason': 'budget_exceeded', 'status': 'stopped'}
            entries.append({'n': n, 'do': step['do'], 'status': 'stopped', 'reason': 'budget_exceeded', 'ms': 0})
            break
        began = f.clock()
        kind = step['do']
        spec = {'goal': step.get('goal') or goal, 'operation': {'press': 'click', 'confirm': 'click', 'type': 'type_text', 'verify': 'verify', 'goto': 'verify', 'open_tab': 'verify', 'close_tab': 'verify'}[kind],
                'control': step.get('control'), 'text': step.get('text'), 'near': step.get('near'), 'expect': step.get('expect'),
                'accept_unknown': step.get('accept_unknown'), 'treat_as_match': step.get('treat_as_match'), 'records': None}
        channel = {'goal': goal, 'out': {}, 'allow': step.get('allow_destructive'), 'look_id': look_id}
        if step['where_kind'] == 'fields':
            where = step['where']
            spec['records'] = {'fields': where['fields'], **({'predicates': where['predicates']} if where.get('predicates') else {}),
                               **({'identity': step['identity']} if step.get('identity') else {})}
        elif step['where_kind'] == 'lines':
            conds = step['where']['lines']
            channel['lines_where'] = {'look_id': look_id, 'look': None, 'conditions': conds, 'identity': step.get('identity') or default_identity(conds), 'accept_hidden': step.get('accept_hidden_text') is True}
        if kind == 'confirm':
            spec['control'] = step['confirm']
            channel['confirm_step'] = {'label': step['confirm'], 'identity': step.get('identity') or carry['identity'], 'before': carry['before'], 'dialog_text': step['dialog_text'], 'dialog_controls': step['dialog_controls']}
        # The window is resolved once (by the first step) and then pinned: every step acts on the same window.
        window = {'title': title} if ctx['pid'] is None else {'pid': ctx['pid'], 'window_id': ctx['window_id']}
        if kind in ('goto', 'open_tab', 'close_tab'):
            # CE-FACADE-007: navigate the pinned window's active tab; done only when the tab reports the requested page and, when given,
            # expect is visible on a fresh observation. A refusal to attach is permission_required, never another browser.
            import browser
            from core import Gap
            try:
                if ctx['pid'] is None:
                    found = f.windows(title)['windows']
                    if len(found) != 1:
                        raise Gap('window_%s: %d windows match the exact title' % ('not_found' if not found else 'ambiguous', len(found)))
                    ctx['pid'], ctx['window_id'] = found[0]['pid'], found[0]['window_id']
                if kind == 'close_tab':
                    browser.close_tab(f, ctx['pid'], ctx['window_id'], allow_foreground=step.get('allow_foreground') is True)
                    page = {'url': '', 'title': ''}
                else:
                    page = (browser.open_tab if kind == 'open_tab' else browser.navigate)(f, ctx['pid'], ctx['window_id'], step['url'])['page']
                result = {'status': 'done' if kind == 'close_tab' else 'delivered_unverified', 'delivery': 'delivered'}
                if step.get('expect'):
                    result = {**f._do(spec['goal'], None, ctx['pid'], ctx['window_id'], None, 'verify', None, step['expect'], None,
                                      max(0.5, min(budget_s, remaining / 3)), None, None, None, None, plan=channel), 'delivery': 'delivered'}
                if result['status'] == 'observed':
                    result['status'] = 'done'  # a verified navigation is an action that worked, not an observation
                if page['url']:
                    result['page'] = {'url': page['url'][:200], 'title': page['title'][:120]}
            except Gap as gap:
                reason = str(gap).split(':', 1)[0]
                result = {'status': 'refused' if reason in ('permission_required', 'bad_request', 'tab_not_opened_by_facade', 'foreground_required') else 'failed', 'reason': reason, 'message': str(gap),
                          'delivery': 'none' if reason in ('permission_required', 'tab_not_opened_by_facade', 'foreground_required', 'bad_request') else 'unknown'}
            status = result['status']
            entry = {'n': n, 'do': kind, 'status': {'deferred': 'stopped'}.get(status, status), 'ms': round((f.clock() - began) * 1000)}
            for key in ('reason', 'page'):
                if result.get(key):entry[key] = result[key]
            if result.get('verification'):
                entry['verification'] = {k: result['verification'].get(k) for k in ('status', 'route')}
            if result.get('delivery') not in (None, 'none'):
                delivery = 'delivered'
            ok = status in ('done', 'observed') or (status == 'delivered_unverified' and n == len(plan_steps))
            if not ok:
                entry['message'] = lk.safe_message(result.get('reason'), result.get('message'))
                failed = {'n': n, 'reason': result.get('reason') or status, 'status': status}
            entries.append(entry)
            carry['before'], carry['identity'] = None, None
            if not ok:
                break
            continue
        f.prefix_control = step.get('control_match') == 'prefix'
        f.foreground_ok = step.get('allow_foreground') is True  # this step only
        try:
            result = f._do(spec['goal'], window.get('title'), window.get('pid'), window.get('window_id'), spec['records'], spec['operation'], spec['text'],
                       spec['expect'], spec['accept_unknown'], max(0.5, min(budget_s, remaining / 3)), None, spec['control'], spec['treat_as_match'], spec['near'], plan=channel)
        finally:
            f.prefix_control = True;f.foreground_ok = False
        if channel.get('pid') is not None:
            ctx['pid'], ctx['window_id'] = channel['pid'], channel['window_id']
        status = result['status']
        entry = {'n': n, 'do': kind, 'status': {'deferred': 'stopped'}.get(status, status), 'ms': round((f.clock() - began) * 1000)}
        if result.get('reason'):
            entry['reason'] = result['reason']
        if result.get('selected'):
            entry['selected'] = {'description': result['selected'].get('description', '')[:120]}
        if result.get('verification'):
            entry['verification'] = {k: result['verification'].get(k) for k in ('status', 'route')}
        if result.get('delivery') and result['delivery'] != 'none':
            delivery = result['delivery'] if delivery != 'delivered' else 'delivered'
        ok = status in ('done', 'observed') or (status == 'delivered_unverified' and n == len(plan_steps))
        if not ok:
            if status == 'refused':
                entry['message'] = lk.safe_message(result.get('reason'), result.get('message'))
            for key in ('found', 'dialog', 'unknown_ids', 'evidence', 'excluded_count', 'missing_fields', 'control_count', 'identity_shown', 'identity_not_shown', 'disabled_count', 'missing_count', 'matches'):
                if key in result:
                    entry[key] = result[key]
            failed = {'n': n, 'reason': result.get('reason') or status, 'status': status}
        entries.append(entry)
        carry['before'] = channel['out'].get('before')
        carry['identity'] = channel['out'].get('identity_strings')
        if kind == 'confirm' and ok:
            carry['before'], carry['identity'] = None, None
        aborted = ctx['pid'] is not None and abort_if and _abort_hit(f, ctx['pid'], ctx['window_id'], abort_if, began)
        if aborted:
            failed = {'n': n, 'reason': 'abort_if_matched', 'status': 'aborted'}
            break
        if not ok:
            break
    ran_actions = any(e['do'] != 'verify' and e['status'] in ('done', 'delivered_unverified') for e in entries)
    if failed is None:
        last = entries[-1]['status']
        status = 'delivered_unverified' if last == 'delivered_unverified' else ('done' if ran_actions else 'observed')
    elif failed['status'] == 'aborted':
        status = 'aborted'
    elif failed['status'] == 'refused' and delivery == 'none':
        status = 'refused'
    elif failed['status'] == 'failed':
        status = 'failed'
    else:
        status = 'stopped'
    response = {'status': status, **({'failed_step': failed['n'], 'reason': failed['reason']} if failed else {}), 'steps': entries,
                'delivery': delivery, 'follow_up_needed': status not in ('done', 'observed')}
    if ctx['pid'] is not None:
        summary = _summary(f, ctx['pid'], ctx['window_id'])
        if summary:
            response['summary'] = summary
    if failed:
        response['hint'] = hint_for(failed['reason'], failed['n'], delivery == 'delivered')
        if failed['reason'] == 'abort_if_matched':
            response['hint'] = 'abort_if text appeared after step %d, so the plan stopped; steps up to it ran. Report it to the user or call cua_look to see the page.' % failed['n']
    elif status == 'delivered_unverified':
        response['hint'] = 'The last click was delivered but no expect was given, so nothing was checked. Do not click again. To check, call cua_do with steps=[{do:"verify", expect:<page text that should be visible now>}].'
    if status == 'failed':
        response['retryable'] = delivery == 'none'
    f.event('do_plan', status=status, steps=len(entries), delivery=delivery, reason=(failed or {}).get('reason'))
    return _fit(response)
