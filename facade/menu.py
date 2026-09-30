"""press {menu: [...]}: an application-menu item pressed through the Driver's invoke_menu route when the ordinary press is refused (#39, #5).

The menu bar is chrome: cua_do's page scope never offers it, and the Driver refuses an ordinary press on a menu item it cannot prove belongs to the
window (`element_outside_target_window`, #5 on Driver 0.28 to 0.30.4) while `invoke_menu` with the exact menu path worked and was verified independently.
So a press step names the path it wants (`menu: ["Profiles", "Person 1"]`) and the facade:

1. resolves it in a FRESH observation of the window: each segment must be exactly one observed menu item under the window's AXMenuBar (AXMenu
   containers are skipped); the path sent to the Driver is then built from the observed ancestors of that AXMenuItem, never from the caller's text
   (a segment that was not observed, is ambiguous or is disabled stops before any Driver action);
2. tries the ordinary bound press of exactly that observed element first (the same revalidation as any press);
3. only when that press is refused `element_outside_target_window`, and only because the element is a menu item, routes the SAME window (same pid and
   window_id, never another) through invoke_menu, with the observed path. The Driver's own doc says invoke_menu temporarily activates the target
   window, so this needs the step's explicit allow_foreground (the same permission as every other route that fronts a window); without it the
   refusal is preserved, nothing is clicked, and the response says what would be needed. Any other refusal, or any other control, is never rerouted;
4. verifies like any press: a fresh observation and `expect` against the page text that was not there before (a menu command whose result lands in
   ANOTHER window is verified by a following step on that window, not by this one).
"""
from __future__ import annotations

import re

import look as lk

MENU_ITEM_ROLES = ('AXMenuItem', 'AXMenuBarItem')   # what a path segment can be; the LAST must be an AXMenuItem
MAX_PATH = 8
REFUSAL = 'element_outside_target_window'


def _gap(message):
    from core import Gap
    return Gap(message)


def check_path(path):
    """The caller's menu path as validated text: 2 to MAX_PATH nonempty strings. Raises core.Gap(bad_request)."""
    if not isinstance(path, list) or not 2 <= len(path) <= MAX_PATH or not all(isinstance(x, str) and x.strip() and len(x) <= 80 for x in path):
        raise _gap('bad_request: menu is the exact observed menu path, %d to %d labels of at most 80 characters, from the menu bar item down (for example ["Profiles", "Person 1"])' % (2, MAX_PATH))
    return [x.strip() for x in path]


def _items_under(f, state, kids, node):
    """The menu items directly under `node`, looking through AXMenu containers (AXMenuBar > AXMenuBarItem > AXMenu > AXMenuItem > AXMenu > ...)."""
    out = []
    for child in kids.get(node, []):
        role = state['nodes'][child].get('role')
        if role in MENU_ITEM_ROLES:
            out.append(child)
        elif role == 'AXMenu':
            out += _items_under(f, state, kids, child)
    return out


def resolve(f, state, path):
    """(element index of the final AXMenuItem, observed path) or raises core.Gap menu_item_not_found / menu_item_ambiguous / menu_item_disabled.

    The observed path is rebuilt from the found node's ancestors (labels of its AXMenuItem/AXMenuBarItem ancestors up to the AXMenuBar, then its own),
    so what is sent to the Driver is what the observation shows, whatever the caller typed."""
    nodes, kids = state['nodes'], f._kids(state)
    bars = sorted(i for i, n in nodes.items() if n.get('role') == 'AXMenuBar')
    if not bars:
        raise _gap('menu_item_not_found: the window shows no application menu bar to resolve the path in')
    level = bars
    chosen = None
    for depth, segment in enumerate(path):
        found = [c for parent in level for c in _items_under(f, state, kids, parent) if lk.clean(nodes[c].get('label')) == lk.clean(segment)]
        if not found:
            raise _gap('menu_item_not_found: no menu item is labelled as segment %d of the path under the menu bar (nothing was pressed)' % (depth + 1))
        if len(found) > 1:
            raise _gap('menu_item_ambiguous: %d menu items carry segment %d of the path; nothing was pressed' % (len(found), depth + 1))
        chosen = found[0]
        level = [chosen]
    if nodes[chosen].get('role') != 'AXMenuItem':
        raise _gap('menu_item_not_found: the last segment is a menu bar title, not a menu item (nothing was pressed)')
    if nodes[chosen].get('enabled') is False:
        raise _gap('menu_item_disabled: the menu item is disabled; nothing was pressed')
    return chosen, observed_path(state, chosen)


def observed_path(state, index):
    """Labels of the node's menu ancestors from the AXMenuBar down, then its own: built ONLY from the observed tree. None if the node is not under an AXMenuBar."""
    nodes, labels, seen, at = state['nodes'], [], set(), index
    while at in nodes and at not in seen:
        seen.add(at)
        node = nodes[at]
        if node.get('role') == 'AXMenuBar':
            labels.reverse()
            return labels if labels and all(labels) else None
        if node.get('role') in MENU_ITEM_ROLES:
            label = node.get('label')
            labels.append(label if isinstance(label, str) and label.strip() else '')  # the RAW observed label: the Driver matches each segment exactly
        elif node.get('role') != 'AXMenu':
            return None  # a menu item is reached through menu containers only
        at = node.get('parent_index')
    return None


def press(f, pid, window_id, path, goal, allow_destructive=None):
    """Press the observed menu item named by `path`. Returns {'route': 'press'|'invoke_menu', 'depth': n, 'before': the observation}. Raises core.Gap for a refusal
    (nothing clicked) and core.DriverCallFailed when a Driver call failed (the action may have been delivered)."""
    import plan as planmod
    from core import Gap, StaleUI
    obs = f.observe(pid, window_id)
    state = f.state(obs['snapshot'])
    index, observed = resolve(f, state, path)
    for n, label in enumerate(observed):
        bad = planmod.destructive_verbs(label)
        if bad and not (n == len(observed) - 1 and planmod.allowed(allow_destructive, label)):
            raise _gap('destructive_control: menu segment %d is destructive (%s); goal text never authorizes it. Only the step itself can, for the LAST segment: add allow_destructive=<its exact label>' % (n + 1, ', '.join(bad)))
    selection = f.bind_press(obs['snapshot'], 'e%d' % index, goal)
    try:
        f.act(selection)
        return {'route': 'press', 'depth': len(observed), 'before': state}
    except StaleUI:
        raise _gap('ui_changed: the window changed between observing the menu item and pressing it; nothing was pressed')
    except Gap as gap:
        from core import DriverCallFailed
        # The Driver reports this refusal either as a refusal answer or (Driver 0.30.4 and 0.31.0, live 2026-09-30) as exit 1 with
        # {"code": "element_outside_target_window"} on stdout: refused before dispatch either way, nothing delivered.
        refused = getattr(gap, 'code', None) == REFUSAL if isinstance(gap, DriverCallFailed) else REFUSAL in str(gap)
        if not refused:
            raise  # any other refusal or failure stays exactly what it is: never rerouted
        if not f.foreground_ok:
            raise _gap('%s: the Driver refused to press this application-menu item (it cannot prove the item belongs to the window); nothing was clicked. The Driver can invoke it by its menu path, but that briefly fronts the window: only if the user allows that, call cua_do again with the same step plus allow_foreground=true' % REFUSAL)
    # The element IS an observed AXMenuItem under the AXMenuBar and the user allowed fronting: the same window, the observed path.
    f.driver.call('invoke_menu', {'session': f.session, 'pid': state['pid'], 'window_id': state['window_id'], 'path': observed})
    f.event('act', route='invoke_menu', path_depth=len(observed), original_refusal=REFUSAL, verification='pending')
    return {'route': 'invoke_menu', 'depth': len(observed), 'before': state}


def verify(f, pid, window_id, before, expect, budget_s):
    """Independent verification like any press: a fresh observation, `expect` in ONE text node that was not there before, else Perception / the screenshot model."""
    current = f.state(f.observe(pid, window_id)['snapshot'])
    check = f._expect_check(current, before, expect, None, None)
    if check['status'] == 'satisfied':
        return check
    if check.get('unproven'):
        return {k: v for k, v in check.items() if k != 'unproven'}
    seen = f._escalate(current, expect, max(1.0, min(20.0, budget_s)))
    return {**seen, **({'reason': check['reason']} if check.get('reason') else {})}
