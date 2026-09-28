"""EXPERIMENTAL option D: a server-side task agent that runs the whole multi-step loop (docs/AGENT-D.md).

Pure and injectable: everything goes through a Facade (observe, actions, choose, act) and a Policy. The policy only
CHOOSES among offered candidates; binding, scope revalidation, single-use selections and never-retry-a-click stay in the
facade. Every stop condition returns `escalated` with evidence and performs no further click."""
from __future__ import annotations

import json
import re

from core import Gap, StaleUI, DriverCallFailed

MIN_CONFIDENCE = 0.5
RECORD_CHARS = 240
CANDIDATE_LIMIT = 18  # the generic chooser's capacity (sketch S4.5): never truncate or rank an oversized scope
MAX_STEPS_CAP = 12
DESTRUCTIVE = {'delete': r'\bdelet', 'remove': r'\bremov', 'erase': r'\beras', 'discard': r'\bdiscard',
               'reset': r'\breset', 'sign out': r'\bsign[\s-]*out'}
NAVIGATION_GOAL = re.compile(r'\b(navigate|go to|open|visit|browse)\b', re.I)
STOP = frozenset('the a an to of on in for and or with by at is are be this that it then click press select choose pick '
                 'button please now page window'.split())
TRANSIENT = (ValueError, RuntimeError, TimeoutError, OSError)


def norm(value):
    return re.sub(r'\s+', ' ', str(value or '').strip()).casefold()


def tokens(text):
    return {t for t in re.findall(r'[a-z0-9#]+', norm(text)) if t not in STOP and len(t) > 1}


def destructive_verbs(label, goal):
    """Destructive verbs in a control label that the goal never asked for."""
    return [v for v, rx in DESTRUCTIVE.items() if re.search(rx, norm(label)) and not re.search(rx, norm(goal))]


class ChooserPolicy:
    """The real adapter: the existing generic chooser (Jev/Qwen/Julia) through Facade.provider('generic').
    It never returns `done` (done is decided only by the deterministic expect check). Confidence is whatever
    the provider reports, else None (then only its own authorization applies)."""
    def __init__(self, facade):
        self.facade = facade

    def choose(self, ctx):
        actions = [{'id': c['id'], 'name': c['label'], 'description': c['description'], 'evidence_text': c['description']}
                   for c in ctx['candidates']]
        request = {'snapshot_id': ctx['snapshot_id'], 'kind': 'semantic', 'operation': 'click', 'goal': ctx['goal'],
                   'actions': actions, 'observation': '\n'.join(a['description'] for a in actions), 'history': ctx['history']}
        out = self.facade.provider('generic')({'method': 'choose'}, request)
        choice = out.get('choice')
        if choice in ('reobserve', 'abstain') or not out.get('action_authorized', True):choice = 'abstain'
        conf = out.get('confidence')
        return {'choice': choice, 'confidence': conf if isinstance(conf, (int, float)) and not isinstance(conf, bool) else None,
                'model': out.get('model') or out.get('route') or 'generic'}


def record_lines(text):
    """Lines of a record context; an AXRow's JSON cell list is expanded into one line per cell line."""
    out = []
    for line in (text or '').split('\n'):
        try:cells = json.loads(line).get('cells') if line.startswith('{') else None
        except (ValueError, AttributeError):cells = None
        for piece in (cells if isinstance(cells, list) else [line]):
            out += [x for x in str(piece).split('\n') if x.strip()]
    return out


def nav_signature(state, facade):
    sig = []
    for i, n in sorted(state['nodes'].items()):
        if n.get('role') == 'AXWebArea':
            sig.append(facade.address_fields(state, facade.subtree(state, 'e'+str(i))[1]))
    return sig


def run_agent(facade, goal, title, expect, text=None, confirm=None, max_steps=8, budget_s=60, policy=None,
              min_confidence=MIN_CONFIDENCE):
    clock, sleep = facade.clock, facade.sleep
    t0 = clock()
    policy = policy or ChooserPolicy(facade)
    steps, cost = [], {'model_calls': 0, 'model_ms': 0, 'driver_ms': 0, 'llm_visible_calls': 'n/a'}
    ctx = {'stage': 'request', 'pid': None, 'window_id': None, 'clicks': 0, 'delivery': 'none'}
    ms_click = [0.0]

    def over():return clock()-t0-ms_click[0] > budget_s
    def hard():return clock()-t0 > 3*budget_s

    def finish(status, reason=None, hint=None, evidence=None, **more):
        out = {'status': status, 'stage': ctx['stage'], 'steps': steps[-MAX_STEPS_CAP:], 'evidence': {'clicks': ctx['clicks'], **(evidence or {})},
               'delivery': ctx['delivery'], 'cost': dict(cost), **more}
        if status == 'escalated' or status == 'failed':
            esc = {'reason': reason, 'hint': hint or 'Nothing further was clicked. Inspect observation.snapshot before acting.'}
            if ctx['pid'] is not None:
                obs = facade._do_observation(ctx['pid'], ctx['window_id'])
                if obs:esc['observation'] = obs
            out['escalation' if status == 'escalated' else 'failure'] = esc
            out['reason'] = reason
        facade.event('agent', status=status, stage=ctx['stage'], reason=reason, steps=len(steps), clicks=ctx['clicks'])
        return out

    def escalate(reason, hint=None, **evidence):return finish('escalated', reason, hint, evidence)

    def observe():
        began = clock()
        try:return facade.state(facade.observe(ctx['pid'], ctx['window_id'])['snapshot'])
        finally:cost['driver_ms'] += round((clock()-began)*1000)

    def handle_of(state):return next(h for h, s in facade.snapshots.items() if s is state)

    try:
        if not isinstance(goal, str) or not goal.strip():raise Gap('bad_request: goal is required')
        if not isinstance(expect, str) or not expect.strip():raise Gap('bad_request: expect is required nonempty text')
        if not isinstance(title, str) or not title.strip():raise Gap('bad_request: title is required')
        if text is not None:raise Gap('bad_request: text_not_supported_in_prototype (type_text steps are not part of option D yet)')
        if confirm is not None and (not isinstance(confirm, str) or not confirm.strip()):raise Gap('bad_request: confirm must be the exact label of a dialog control')
        if not isinstance(max_steps, int) or isinstance(max_steps, bool) or not 1 <= max_steps <= MAX_STEPS_CAP:raise Gap('bad_request: max_steps must be 1..%d' % MAX_STEPS_CAP)
        if not isinstance(budget_s, (int, float)) or isinstance(budget_s, bool) or budget_s <= 0:raise Gap('bad_request: budget_s must be positive seconds')
        facade.reject_answer_leak({'nodes': {int(m): 0 for m in facade.OBSERVED_ID.findall(goal)}}, goal)
        ctx['stage'] = 'window'
        found = facade.windows(title)['windows']
        if len(found) != 1:raise Gap('window_%s: %d windows match the exact title' % ('not_found' if not found else 'ambiguous', len(found)))
        ctx.update(pid=found[0]['pid'], window_id=found[0]['window_id'])
        ctx['stage'] = 'observe'
        first = observe()
        facade.reject_answer_leak(first, goal)
        if any(n.get('role') in facade.MODAL_ROLES for n in first['nodes'].values()):
            return escalate('dialog_already_open', 'A dialog was open before the first step; the candidate scope is ambiguous.')
        check0 = facade._expect_check(first, first, expect)
        if check0.get('present_before'):
            return escalate('expect_present_before_action', 'expect text is already on the page, so it cannot prove the outcome; state text that is absent before the action.')
        base_nav = nav_signature(first, facade)
        wants_nav = bool(NAVIGATION_GOAL.search(goal))
        prev, pending, no_progress, confirm_used = first, None, 0, False
        state = first
        while True:
            # ---- account for the previous click, if any
            if pending:
                changed = (facade.scope_digest(state, pending['root']) != pending['digest']) if pending['root'] is not None and pending['root'] in state['nodes'] \
                    else (pending['root'] is not None or state['fingerprint'] != pending['fingerprint'])
                steps[-1]['scope_changed'] = changed
                no_progress = 0 if changed else no_progress + 1
            check = facade._expect_check(state, first, expect)
            if check['status'] == 'satisfied':
                ctx['stage'] = 'verify'
                return finish('done', evidence={'verification': {k: check[k] for k in ('status', 'route')}})
            if ctx['clicks'] and not wants_nav and nav_signature(state, facade) != base_nav:
                return escalate('navigation', 'The address field changed and the goal did not ask for navigation.')
            plan = None
            if pending:
                new, replaced = facade._new_modals(state, prev)
                modals = [i for i, n in state['nodes'].items() if n.get('role') in facade.MODAL_ROLES]
                if new or replaced:
                    verdict = handle_dialog(facade, state, new, replaced, confirm, confirm_used, goal, pending, escalate)
                    if verdict.get('escalated'):return verdict['escalated']
                    plan = confirm_plan(facade, state, verdict, goal, escalate)
                    if plan.get('escalated'):return plan['escalated']
                    confirm_used = True
                elif modals:
                    return escalate('dialog_still_open', 'A dialog is still open after the last step.')
                if plan is None and no_progress >= 2:return escalate('no_progress', 'Two consecutive clicks changed nothing in the bound scope.')
            if len(steps) >= max_steps:return escalate('step_budget', 'max_steps reached without the expected outcome.')
            if over() or hard():return escalate('time_budget', 'The wall budget ran out; no further click was made.')
            ctx['stage'] = 'plan'
            if plan is None:
                plan = plan_step(facade, state, goal, policy, steps, cost, sleep, over, hard, min_confidence, escalate)
                if plan.get('escalated'):return plan['escalated']
            ctx['stage'] = 'act'
            began = clock()
            try:
                try:facade.act(plan['selection'])
                except StaleUI:
                    if plan['model'] == 'confirm_exact':return escalate('ui_changed_repeatedly', 'The dialog changed before it was confirmed; nothing further was clicked.')
                    # one bounded re-plan per step; the refused selection is never reused
                    state = observe();prev = state
                    if over() or hard():return escalate('time_budget', 'The wall budget ran out before the re-plan.')
                    plan = plan_step(facade, state, goal, policy, steps, cost, sleep, over, hard, min_confidence, escalate)
                    if plan.get('escalated'):return plan['escalated']
                    try:facade.act(plan['selection'])
                    except StaleUI:return escalate('ui_changed_repeatedly', 'The content changed again before the click; nothing was clicked.')
            except DriverCallFailed:
                return driver_failure(facade, plan, ctx, finish)
            except Gap as gap:
                return escalate('act_refused', str(gap)[:160])
            finally:
                spent = clock()-began
                ms_click[0] += spent;cost['driver_ms'] += round(spent*1000)
            ctx['clicks'] += 1;ctx['delivery'] = 'delivered'
            item = facade.selections[plan['selection']]
            steps.append({'n': len(steps)+1, 'action': plan['action'], 'model': plan['model'], 'confidence': plan['confidence'],
                          'ms': plan['ms'], 'scope_changed': None})
            pending = {'root': item.get('scope_root'), 'digest': item.get('scope_digest'), 'fingerprint': plan['fingerprint'],
                       'record': plan['record'], 'others': plan['others']}
            prev = state
            ctx['stage'] = 'observe'
            state = observe()
    except DriverCallFailed as gap:
        ctx['delivery'] = ctx['delivery'] if ctx['delivery'] != 'none' else 'none'
        return finish('failed', 'driver_call_failed', evidence={'retryable': ctx['delivery'] == 'none'}, retryable=ctx['delivery'] == 'none')
    except Gap as gap:
        text_ = str(gap)
        return finish('failed', 'bad_request' if text_.startswith('bad_request') else 'refused', text_[:160], retryable=False)
    except TRANSIENT as error:
        return finish('failed', 'provider_failure', type(error).__name__, retryable=ctx['clicks'] == 0)


def driver_failure(facade, step, ctx, finish):
    """A Driver failure around act(). used=True means the click may have been delivered: never retryable, no selection."""
    item = facade.selections.get(step['selection'])
    delivered = bool(item and item['used'])
    if delivered:ctx['delivery'] = 'uncertain'
    facade.selections.pop(step['selection'], None)
    return finish('failed', 'driver_call_failed', 'A Driver failure %s.' % ('after a click may have been delivered: do not click again blindly' if delivered else 'before any click'),
                  retryable=not delivered and ctx['clicks'] == 0)


def page_controls(facade, state):
    """(page control indices, non-page actionable control count), by the SAME definition cua_do uses: enabled press-capable
    CONTROL_ROLES inside the single top-level web area (else the whole tree when there is none), minus alias and AXColumn copies.
    Browser menu bar, toolbar and tab strip are outside the web area and never candidates."""
    content = facade._content_ids(state) - facade._column_copies(state)
    page, other = [], 0
    for i, n in sorted(state['nodes'].items()):
        if i in state['aliases'] or not facade._is_control(n) or not facade._operation_compatible(n, 'click'):continue
        if i in content:page.append(i)
        else:other += 1
    return page, other


def record_text_for(facade, state, i, fallback):
    """The control's record text: cua_do's record_context; when that finds nothing, the structural unit / single record that
    Facade.discover_records finds for this control's label."""
    text = facade.record_context(state, i)
    if text:return text
    label = state['nodes'][i].get('label')
    if label:
        try:roots, targets, _, why, _ = facade.discover_records(state, 'click', label)
        except Gap:roots = None
        for root, target in (targets or {}).items():
            if target == 'e'+str(i):
                own = {label, state['nodes'][i].get('value') or ''}
                return '\n'.join(line for line in facade.subtree(state, root)[0].split('\n') if line and line not in own)
    return ''


def candidates_for(facade, state):
    """([candidate], non_page_count) for the page. record_text is complete (identity matching); the model context bounds it."""
    page, other = page_controls(facade, state)
    out = []
    for i in page:
        n = state['nodes'][i]
        out.append({'id': 'e'+str(i), 'label': n.get('label') or n.get('value') or n.get('role'), 'record_text': record_text_for(facade, state, i, '')})
    return out, other


def plan_step(facade, state, goal, policy, steps, cost, sleep, over, hard, min_confidence, escalate):
    """Return {'escalated': result} or a bound step {selection, action, model, confidence, ms, record, fingerprint, snapshot}."""
    clock = facade.clock
    snapshot = next(h for h, s in facade.snapshots.items() if s is state)
    if len(facade._top_web_areas(state)) > 1:
        return {'escalated': escalate('web_area_ambiguous', 'The window holds several separate page areas; close the extra one or give the title of the window holding only the page.', web_areas=len(facade._top_web_areas(state)))}
    cands, non_page = candidates_for(facade, state)
    every = list(cands)  # identity uniqueness is judged against every page record, not the prefiltered few
    if not cands:
        return {'escalated': escalate('no_page_candidates', 'No enabled actionable control was found in the page content (%d outside it, e.g. browser chrome, were ignored); try cua_choose mode=regions for pixel-only targets.' % non_page,
                                      page_controls=0, non_page_controls=non_page)}
    wanted = tokens(goal)
    scored = [c for c in cands if wanted & tokens(c['label'] + ' ' + c['record_text'])]
    if not scored:
        return {'escalated': escalate('no_candidate', 'No enabled control matches the goal words; try cua_choose mode=regions or refine the goal.', page_controls=len(cands), non_page_controls=non_page)}
    cands, tier = scored, None
    if len(cands) > CANDIDATE_LIMIT:
        # Lexical narrowing by exact evidence only: keep the whole top tier (candidates matching the most goal words),
        # never a truncated slice; an oversized top tier still escalates below.
        rank = {c['id']: len(wanted & tokens(c['label'] + ' ' + c['record_text'])) for c in cands}
        top = max(rank.values());tier = [c for c in cands if rank[c['id']] == top]
        if len(tier) <= CANDIDATE_LIMIT:cands = tier
    if len(cands) > CANDIDATE_LIMIT:
        return {'escalated': escalate('too_many_candidates', 'More than %d candidates remain after the lexical prefilter; narrow the goal with criteria (never truncated).' % CANDIDATE_LIMIT,
                                      candidate_count=len(cands), limit=CANDIDATE_LIMIT)}
    ids = [c['id'] for c in cands]
    began = clock()
    quoted = {norm(q) for q in facade.quoted_tokens(goal)}
    exact = [c for c in cands if norm(c['label']) in quoted]
    picked, model, confidence, record = None, None, None, None
    if len(exact) == 1:
        try:
            choice = facade.choose(snapshot, goal, mode='exact', exact_name=exact[0]['label'], exact_role=state['nodes'][int(exact[0]['id'][1:])].get('role'))
        except Gap:
            choice = {}
        if 'selection' in choice:picked, model, confidence, selection = choice['selected_id'], 'exact', 1.0, choice['selection']
    if picked is None:  # no exact path (not unique in the whole window): the policy decides, never a guess
        actions = facade.actions(state, ids, 'click', None)
        descr = {a['id']: a['description'] for a in actions}
        context = {'goal': goal, 'step': len(steps)+1, 'snapshot_id': state['raw']['snapshot_id'],
                   'candidates': [{'id': c['id'], 'label': c['label'], 'record': c['record_text'][:RECORD_CHARS], 'description': descr.get(c['id'], c['label'])[:300]} for c in cands],
                   'history': [{'action': s['action'], 'scope_changed': s['scope_changed']} for s in steps]}
        decision = None
        for attempt in (1, 2):
            cost['model_calls'] += 1;m0 = clock()
            try:
                decision = policy.choose(context)
                break
            except Exception as error:
                if isinstance(error, (Gap, KeyboardInterrupt)):raise
                if attempt == 2 or over() or hard():
                    return {'escalated': escalate('policy_unavailable', 'The policy transport failed twice (%s); no click was made.' % type(error).__name__)}
                sleep(facade.RETRY_BACKOFF_S)
            finally:cost['model_ms'] += round((clock()-m0)*1000)
        choice, confidence, model = decision.get('choice'), decision.get('confidence'), decision.get('model')
        if choice == 'abstain':return {'escalated': escalate('policy_abstained', 'The policy found no safe choice among %d candidates.' % len(cands))}
        if choice == 'done':return {'escalated': escalate('done_unverified', 'The policy claims the goal is met but expect is not satisfied in the fresh tree.')}
        if choice not in ids:return {'escalated': escalate('policy_invalid_choice', 'The policy named a control outside the offered candidates.')}
        if decision.get('authorized') is False:return {'escalated': escalate('policy_abstained', 'The policy did not authorize its choice.')}
        if confidence is not None and confidence < min_confidence:
            return {'escalated': escalate('low_confidence', 'Policy confidence %.2f is below %.2f.' % (confidence, min_confidence), picked_label=next(c['label'] for c in cands if c['id'] == choice)[:40])}
        picked = choice
        label = next(c['label'] for c in cands if c['id'] == picked)
        bad = destructive_verbs(label, goal)
        if bad:return {'escalated': escalate('destructive_control', 'The chosen control %r is destructive (%s) and the goal does not ask for it.' % (label[:40], ', '.join(bad)))}
        if over() or hard():return {'escalated': escalate('time_budget', 'The wall budget ran out before the click.')}
        try:selection = facade.agent_bind(snapshot, goal, picked, ids)['selection']
        except Gap as gap:return {'escalated': escalate('bind_refused', str(gap)[:160])}
    cand = next(c for c in cands if c['id'] == picked)
    bad = destructive_verbs(cand['label'], goal)
    if bad:
        facade.selections.pop(selection, None)
        return {'escalated': escalate('destructive_control', 'The chosen control %r is destructive (%s) and the goal does not ask for it.' % (cand['label'][:40], ', '.join(bad)))}
    if hard():
        facade.selections.pop(selection, None)
        return {'escalated': escalate('time_budget', 'The wall budget ran out before the click.')}
    return {'selection': selection, 'action': {'id': picked, 'label': cand['label'][:40]}, 'model': model, 'confidence': confidence,
            'ms': round((clock()-began)*1000), 'record': cand['record_text'], 'fingerprint': state['fingerprint'], 'snapshot': snapshot,
            'others': [c['record_text'] for c in every if c['record_text'] != cand['record_text']]}


def handle_dialog(facade, state, new, replaced, confirm, confirm_used, goal, pending, escalate):
    """A dialog appeared after a click. Only the exact `confirm` label, an identity match against the clicked record, and
    exactly one enabled control with that label allow ONE confirm click. Returns {'escalated': result} or {'confirm_index': i}."""
    if replaced or len(new) != 1:return {'escalated': escalate('dialog_ambiguous', 'A dialog was replaced or several appeared.')}
    if not confirm:return {'escalated': escalate('dialog_needs_confirm', 'A dialog appeared and no confirm label was supplied; nothing in it was pressed. Rerun with confirm=<exact control label>.',
                                                 dialog_controls=dialog_labels(facade, state, new[0]))}
    if confirm_used:return {'escalated': escalate('dialog_needs_confirm', 'A second dialog appeared; confirm is used at most once per run.')}
    nodes = state['nodes'];modal = new[0]
    buttons = dialog_buttons(facade, state, modal)
    hits = [i for i in buttons if norm(nodes[i].get('label')) == norm(confirm)]
    if len(hits) != 1:return {'escalated': escalate('confirm_control_not_found' if not hits else 'confirm_dialog_ambiguous', 'The confirm label is not exactly one enabled dialog control.',
                                                    dialog_controls=dialog_labels(facade, state, modal))}
    bad = destructive_verbs(confirm, goal)
    if bad:return {'escalated': escalate('destructive_control', 'The confirm control %r is destructive (%s) and the goal does not ask for it.' % (confirm[:40], ', '.join(bad)))}
    # identity: the record lines unique to the clicked record must all be displayed in the dialog
    dialog_text = norm(facade.subtree(state, 'e'+str(modal))[0])
    others = {norm(line) for text in pending.get('others', []) for line in record_lines(text)}
    unique = [norm(line) for line in record_lines(pending['record']) if norm(line) not in others]
    if not unique:return {'escalated': escalate('confirm_identity_unknown', 'The clicked record has no distinguishing text to match against the dialog.')}
    # identifier-like lines (containing a digit) carry identity; a dialog seldom repeats every descriptive line
    unique = [u for u in unique if any(ch.isdigit() for ch in u)] or unique
    if not all(u in dialog_text for u in unique):
        return {'escalated': escalate('confirm_identity_mismatch', 'The dialog does not display the clicked record\'s identity.')}
    return {'confirm_index': hits[0], 'snapshot_state': state}


def confirm_plan(facade, state, verdict, goal, escalate):
    node = state['nodes'][verdict['confirm_index']]
    snapshot = next(h for h, s in facade.snapshots.items() if s is state)
    try:choice = facade.choose(snapshot, goal, mode='exact', exact_name=node.get('label'), exact_role=node.get('role'))
    except Gap as gap:return {'escalated': escalate('confirm_refused', str(gap)[:160])}
    if 'selection' not in choice:return {'escalated': escalate('confirm_control_not_found', 'The confirm label is not one unique observed control.')}
    return {'selection': choice['selection'], 'action': {'id': choice['selected_id'], 'label': (node.get('label') or '')[:40]}, 'model': 'confirm_exact',
            'confidence': 1.0, 'ms': 0, 'record': '', 'others': [], 'fingerprint': state['fingerprint']}


def dialog_buttons(facade, state, modal):
    nodes = state['nodes']
    return [i for i in sorted(facade.subtree(state, 'e'+str(modal))[1]) if i not in state['aliases'] and facade._is_control(nodes[i]) and 'AXPress' in nodes[i].get('actions', [])]


def dialog_labels(facade, state, modal):
    return [(state['nodes'][i].get('label') or '')[:40] for i in dialog_buttons(facade, state, modal)][:12]
