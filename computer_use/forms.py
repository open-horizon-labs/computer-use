"""Web form controls the plain press and type steps cannot drive: a <select> (Chrome: AXPopUpButton) and a checkbox (AXCheckBox).

Found live (A/B suite 2026-10-01): the agent typed text fields fine, but pressing a select opened the native popup whose options exist twice in the tree
(`exact_target_not_unique`), typing into it was `control_not_pressable`, and a checkbox press was only ever "proved" by label presence.

Both are routed from the existing `type` and `press` steps, no new step kind and no new tool, and only when the step's `control` names EXACTLY ONE such
control in the page content (anything else falls through to the old path unchanged):

  type  control=<select's label>  text=<exact visible option label>   the Driver's AX value set on the popup button. It presses the child option
        directly: the native popup is never opened and no focus is taken. Done only when a FRESH read shows the select displaying exactly that label.
  press control=<checkbox label>  expect=checked|unchecked|<anything>  a normal bound AXPress of the observed checkbox. Done only when a FRESH read shows
        its checked state flipped to the wanted state (AX value/selected, look.toggle_marker). With expect checked/unchecked a box already in that state is
        not pressed (a press toggles: it would undo it); otherwise the press is a pure flip and needs the look_id of a look that saw the current state.

The state is the proof; `expect` is not read as page text on these routes. Read-only observations decide; nothing is retried after a delivery.
"""
import re

import look as lk

SELECT_ROLES = ('AXPopUpButton',)
CHECK_ROLES = ('AXCheckBox',)
STATE_WORDS = ('checked', 'unchecked')
TOKEN = re.compile(r'[a-z][a-z0-9_]{0,60}')


def _core():
    import core
    return core


def _result(status, reason=None, delivery='none', message=None, **more):
    out = {'status': status, 'delivery': delivery, **more}
    if reason:
        out['reason'] = reason
    if message:
        out['message'] = message
    return out


def _fresh(f, pid, window_id):
    """(snapshot handle, state) of a fresh observation, or None when it cannot be read (the old path then reports it in its own typed words)."""
    Gap = _core().Gap
    try:
        obs = f.observe(pid, window_id)
        state = f.state(obs['snapshot'])
    except Gap:
        return None
    return (obs['snapshot'], state) if not state.get('no_tokens') else None


def _found(f, state, label, roles):
    """Indices of page-content controls of these roles whose label is exactly `label` (whitespace and case folded)."""
    content = f._content_ids(state) - f._column_copies(state)
    want = lk.norm(label)
    return [i for i in sorted(content) if i not in state['aliases'] and state['nodes'][i].get('role') in roles and lk.norm(state['nodes'][i].get('label')) == want]


def options_of(f, state, index):
    """Labels of the option items under a select, in tree order. A closed Chrome select may list only its selected option."""
    members = f.subtree(state, 'e%d' % index)[1]
    return [lk.clean(state['nodes'][i].get('label')) for i in sorted(members) if state['nodes'][i].get('role') == 'AXMenuItem' and lk.clean(state['nodes'][i].get('label'))]


def shown_of(f, state, index):
    """What a select displays: its own AX value, else the label of its selected option item. None when it shows nothing readable."""
    node = state['nodes'][index]
    value = node.get('value')
    if isinstance(value, str) and value.strip():
        return lk.clean(value)
    for i in sorted(f.subtree(state, 'e%d' % index)[1]):
        item = state['nodes'][i]
        if item.get('role') == 'AXMenuItem' and item.get('selected') is True and lk.clean(item.get('label')):
            return lk.clean(item['label'])
    return None


def _poll(f, pid, window_id, read):
    """Read-only, bounded verification: observe, and while `read(state)` is not final wait the look's own OBSERVE_RETRY_DELAYS. Returns the last read."""
    Gap = _core().Gap
    delays = (0,) + tuple(_core().OBSERVE_RETRY_DELAYS)
    seen = None
    for n, delay in enumerate(delays):
        if delay:
            f.sleep(delay)
        try:
            obs = f.observe(pid, window_id)
            seen = read(f.state(obs['snapshot']))
        except Gap:
            seen = {'final': False, 'gone': True}
            continue
        if seen['final']:
            break
    return seen


def _code(error):
    text = str(error)
    code = text.split('Driver refused:', 1)[1].strip() if 'Driver refused:' in text else text.split(':', 1)[0].strip()
    return code if TOKEN.fullmatch(code) else 'driver_refused'


# ---- select --------------------------------------------------------------------------------------------------------------------

def _open_and_press(f, pid, window_id, node, index, control, label):
    """Open the select with a press, then press the one option item UNDER it whose label is exactly `label`.
    None when the option was pressed (the caller verifies the shown value); else the step result (nothing chosen)."""
    Gap, DriverCallFailed = _core().Gap, _core().DriverCallFailed
    press = lambda token: f.driver.call('click', {'session': f.session, 'pid': pid, 'window_id': window_id, 'element_token': token})
    try:
        press(node['element_token'])
    except (Gap, DriverCallFailed) as error:
        return _result('refused', 'select_refused', message='select_refused: %r could not be opened (%s); nothing was changed' % (control[:60], _code(error)))
    f.latest.pop((pid, window_id), None)
    # Chrome lists the options under the select a moment after the press (live 2026-10-01: the first read still showed only the
    # selected one), so re-read within the look's own bounded delays until more than one option is listed.
    fresh, again = None, []
    for delay in (0,) + tuple(_core().OBSERVE_RETRY_DELAYS):
        if delay:
            f.sleep(delay)
        fresh = _fresh(f, pid, window_id)
        if fresh is None:
            continue
        again = _found(f, fresh[1], control, SELECT_ROLES)
        if len(again) == 1 and len(options_of(f, fresh[1], again[0])) > 1:
            break
        f.latest.pop((pid, window_id), None)
    if fresh is None:
        return _result('stopped', 'select_unverified', 'uncertain', message='select_unverified: %r was opened but could not be read; nothing was chosen' % control[:60])
    _, opened = fresh
    if len(again) != 1:
        return _result('stopped', 'select_unverified', 'uncertain', message='select_unverified: %r could not be found again after opening; nothing was chosen' % control[:60])
    members = f.subtree(opened, 'e%d' % again[0])[1]
    items = [i for i in sorted(members) if opened['nodes'][i].get('role') == 'AXMenuItem' and lk.norm(opened['nodes'][i].get('label')) == lk.norm(label)]
    if len(items) != 1:
        offered = options_of(f, opened, again[0])
        return _result('refused', 'select_option_not_offered', 'uncertain', options=offered[:12],
                       message='select_option_not_offered: %d options of %r are labelled %r (offered: %s); nothing was chosen' % (len(items), control[:60], label[:60], ', '.join(o[:30] for o in offered[:12])))
    try:
        press(opened['nodes'][items[0]]['element_token'])
    except (Gap, DriverCallFailed) as error:
        return _result('failed', 'select_not_applied', 'unknown', message='select_not_applied: pressing %r in %r failed (%s); it may or may not have changed' % (label[:60], control[:60], _code(error)))
    f.latest.pop((pid, window_id), None)
    return None


def select(f, pid, window_id, control, option):
    """None when `control` is not exactly one select of the page (the old type path decides), else the step result dict."""
    Gap, DriverCallFailed = _core().Gap, _core().DriverCallFailed
    fresh = _fresh(f, pid, window_id)
    if fresh is None:
        return None
    handle, state = fresh
    found = _found(f, state, control, SELECT_ROLES)
    if not found:
        return None
    if len(found) > 1:
        return _result('refused', 'select_ambiguous', message='select_ambiguous: %d selects are labelled %r; nothing was changed' % (len(found), control[:60]))
    index = found[0]
    node = state['nodes'][index]
    label = lk.clean(option)
    if not label:
        return _result('refused', 'select_option_not_offered', message='select_option_not_offered: text must be the exact visible option label of %r; nothing was changed' % control[:60])
    if node.get('enabled') is False:
        return _result('refused', 'select_disabled', message='select_disabled: %r is disabled; nothing was changed' % control[:60])
    options = options_of(f, state, index)
    if len(options) > 1 and label not in options:
        return _result('refused', 'select_option_not_offered', options=options[:12],
                       message='select_option_not_offered: %r is not an option of %r (offered: %s); nothing was changed' % (label[:60], control[:60], ', '.join(o[:30] for o in options[:12])))
    before = shown_of(f, state, index)
    if before == label:
        return _result('done', route='already_selected', shown=label, selected={'description': control[:120]},
                       verification={'status': 'satisfied', 'route': 'ax_select_value'})
    f.check_foreground(state['raw'])
    args = {'session': f.session, 'pid': pid, 'window_id': window_id, 'element_token': node['element_token'], 'value': label}
    try:
        answer = f.driver.call('set_value', args)
        if isinstance(answer, dict) and (answer.get('refusal') or answer.get('status') == 'refused'):  # a fake or a client that hands a refusal back as data
            raise Gap('Driver refused: ' + str((answer.get('refusal') or {}).get('code', 'unknown')))
    except DriverCallFailed:
        # The failed set may still have landed: read the select first, and only press when it still shows what it showed before.
        now = _fresh(f, pid, window_id)
        again = _found(f, now[1], control, SELECT_ROLES) if now else []
        shown_now = shown_of(f, now[1], again[0]) if len(again) == 1 else None
        if shown_now != label and shown_now != before:
            return _result('failed', 'select_not_applied', 'unknown', message='select_not_applied: the Driver gave no answer for %r; it may or may not have changed' % control[:60])
        if shown_now == label:
            opened = None
        else:
            opened = _open_and_press(f, pid, window_id, now[1]['nodes'][again[0]], again[0], control, label)  # the token from the fresh read: the failed set may have expired the old one
        # Live 2026-10-01 (Chrome for Testing 154, Driver 0.31): a closed select exposes no option children, so set_value exits 1
        # ("No AX child matching 'Billing'"). Pressing the select opens it; its options then appear under it as AXMenuItems
        # (Chrome also lists them again in its native menu, outside the select), and pressing the one under the select
        # chooses it in the background. The value is verified below exactly as for set_value.
        if opened is not None:
            return opened
    except Gap as gap:
        return _result('refused', 'select_refused', message='select_refused: the Driver refused to choose %r in %r (%s); nothing was changed' % (label[:60], control[:60], _code(gap)))
    f.latest.pop((pid, window_id), None)

    def read(now):
        again = _found(f, now, control, SELECT_ROLES)
        if len(again) != 1:
            return {'final': False, 'gone': True}
        shown = shown_of(f, now, again[0])
        return {'final': shown == label, 'shown': shown, 'gone': False}
    seen = _poll(f, pid, window_id, read) or {'final': False, 'gone': True}
    base = {'selected': {'description': control[:120]}, 'delivery': 'delivered'}
    if seen['final']:
        return _result('done', shown=label, verification={'status': 'satisfied', 'route': 'ax_select_value'}, **base)
    if seen.get('gone'):
        return _result('stopped', 'select_unverified', verification={'status': 'unknown', 'route': 'ax_select_value'}, **base,
                       message='select_unverified: %r could not be read again after choosing; its value is not proven' % control[:60])
    shown = seen.get('shown')
    same = shown == before
    return _result('stopped', 'select_value_unchanged' if same else 'select_value_differs', shown=shown, verification={'status': 'not_satisfied', 'route': 'ax_select_value'}, **base,
                   message='%s: %r shows %r after choosing %r' % ('select_value_unchanged' if same else 'select_value_differs', control[:60], (shown or '')[:60], label[:60]))


# ---- checkbox ------------------------------------------------------------------------------------------------------------------

def want_state(expect):
    word = lk.norm(expect) if isinstance(expect, str) else ''
    return word if word in STATE_WORDS else None


def toggle(f, pid, window_id, control, expect, goal, look_id):
    """None when `control` is not exactly one checkbox of the page (the old press path decides), else the step result dict."""
    Gap, DriverCallFailed, StaleUI = _core().Gap, _core().DriverCallFailed, _core().StaleUI
    import plan as planmod
    fresh = _fresh(f, pid, window_id)
    if fresh is None:
        return None
    handle, state = fresh
    found = _found(f, state, control, CHECK_ROLES)
    if not found:
        return None
    if len(found) > 1:
        return _result('refused', 'checkbox_ambiguous', message='checkbox_ambiguous: %d checkboxes are labelled %r; nothing was pressed' % (len(found), control[:60]))
    index = found[0]
    node = state['nodes'][index]
    if node.get('enabled') is False or 'AXPress' not in (node.get('actions') or []):
        return _result('refused', 'checkbox_disabled', message='checkbox_disabled: %r is disabled or cannot be pressed right now; nothing was pressed' % control[:60])
    before = lk.toggle_marker(node)
    want = want_state(expect)
    base = {'selected': {'description': control[:120]}}
    if want == before:
        return _result('done', route='already_in_state', state=before, verification={'status': 'satisfied', 'route': 'ax_toggle_state'}, **base)
    if want is None:
        seen = f.looks.get((pid, window_id, look_id)) if look_id else None
        if seen is None or not planmod.look_matches(f, state, seen, look_id)[0]:
            return _result('refused', 'toggle_state_unseen', message='toggle_state_unseen: a press flips %r and no look_id saw its current state; nothing was pressed' % control[:60])
        want = 'unchecked' if before == 'checked' else 'checked'
    try:
        selection = f.bind_press(handle, 'e%d' % index, goal)
        f.act(selection)
    except DriverCallFailed:
        return _result('failed', 'driver_call_failed', 'uncertain', message='driver_call_failed: a Driver call failed; the checkbox may have been pressed')
    except StaleUI:
        return _result('refused', 'page_changed_since_look', message='page_changed_since_look: the page changed before the press; nothing was pressed')
    except Gap as gap:
        code = _code(gap)
        return _result('refused', code if code != 'driver_refused' else 'checkbox_refused', message='%s: the checkbox %r was not pressed (%s)' % (code, control[:60], str(gap)[:120]))

    def read(now):
        again = _found(f, now, control, CHECK_ROLES)
        if len(again) != 1:
            return {'final': False, 'gone': True}
        marker = lk.toggle_marker(now['nodes'][again[0]])
        return {'final': marker == want, 'state': marker, 'gone': False}
    seen = _poll(f, pid, window_id, read) or {'final': False, 'gone': True}
    base['delivery'] = 'delivered'
    if seen['final']:
        return _result('done', state=want, verification={'status': 'satisfied', 'route': 'ax_toggle_state'}, **base)
    if seen.get('gone'):
        return _result('stopped', 'checkbox_unverified', verification={'status': 'unknown', 'route': 'ax_toggle_state'}, **base,
                       message='checkbox_unverified: %r could not be read again after the press; its state is not proven' % control[:60])
    return _result('stopped', 'checkbox_not_flipped', state=seen.get('state'), verification={'status': 'not_satisfied', 'route': 'ax_toggle_state'}, **base,
                   message='checkbox_not_flipped: %r still reads %s after the press (wanted %s)' % (control[:60], seen.get('state'), want))
