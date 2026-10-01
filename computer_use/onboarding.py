"""Agent onboarding (#64, CE-FACADE-010): the first blocked call teaches only what blocks it; the first verified `do` is measured.

The user being onboarded is an LLM agent driving `look` and `do`. Nothing here adds a tool or a mandatory step (CE-FACADE-005):
  * `setup_for` answers a refusal that is an ENVIRONMENT problem of the target the call named with a `setup` block built from the matching
    doctor checks (cli.py: reused, never duplicated): [{check, status, fix, who: agent | user}]. Shown once per server process unless the set
    of blockers changes; never on a healthy machine (a check that passes is not a blocker, so no blocking reason means no block).
  * `is_verified_do` / `Facade.first_do` record time_to_first_verified_do: the LLM-visible calls and the seconds since the server started
    when the first do ended done with a verified ACTION (press, type or confirm; a goto alone is setup, not the aha moment).
"""
import cli

MAX_ENTRIES = 4
MAX_FIX_CHARS = 240
ACTIONS = ('press', 'type', 'confirm')
AGENT_FIXES = ('python -m computer_use bootstrap', 'python scripts/', 'scripts/')  # what `bootstrap` (or a script in this checkout) can run from a shell

DEVICE_AGENT_FALLBACK = {'check': 'mobile.device_agent', 'status': cli.BLOCKER, 'who': 'user',
                         'fix': "install mobile-mcp's on-device agent on that device (see the mobile-mcp setup notes); Node.js itself is fine"}

# refusal reason -> (doctor checks that can explain it, the check that explains it when those all pass, or None). Every key is tied to the
# target the call named: a browser refusal never carries a device blocker and the other way round.
BLOCKERS = {
    'agent_browser_unavailable': (('check_agent_browser', 'check_node'), None),
    'permission_required': (('check_driver_daemon', 'check_driver_grant', 'check_driver_permissions'), 'check_full_disk_access'),
    'mobile_backend_unavailable': (('check_node',), None),
    'mobile_device_agent_missing': (('check_node',), DEVICE_AGENT_FALLBACK),
    'perception_not_available': (('check_perception',), None),
    'driver_call_failed': (('check_driver_installed', 'check_driver_daemon'), None),  # only when the daemon really is down: a passing check adds nothing
    'agent_display_unavailable': (('check_space_mover',), None),
}


def who_for(fix):
    """agent: a command `bootstrap` or a script of this checkout runs; user: installing software or a System Settings grant."""
    return 'agent' if str(fix).startswith(AGENT_FIXES) else 'user'


def reasons_of(result):
    """The refusal reasons a look or do response carries, in order: the response's own, each plan step's, a device list's backend."""
    out = []
    def add(reason):
        if isinstance(reason, str) and reason not in out:
            out.append(reason)
    add(result.get('reason'))
    for step in result.get('steps') or []:
        if isinstance(step, dict):
            add(step.get('reason'))
    unavailable = result.get('devices_unavailable')
    if isinstance(unavailable, dict):
        add(unavailable.get('reason'))
    return out


def _entry(check):
    fix = check['fix'] or check['detail']
    return {'check': check['name'], 'status': check['status'], 'fix': fix[:MAX_FIX_CHARS], 'who': who_for(check['fix'])}


def _run(env, name):
    try:
        out = getattr(cli, name)(env)
    except Exception:  # a check bug must never hide the refusal it explains
        return []
    return out if isinstance(out, list) else [out]


def entries_for(reason, env):
    """The blocking doctor checks behind one reason: warn and blocker only (ok and skipped are not in the way)."""
    names, fallback = BLOCKERS[reason]
    found = [_entry(c) for name in names for c in _run(env, name) if c['status'] in (cli.WARN, cli.BLOCKER)]
    if not found and isinstance(fallback, dict):
        return [dict(fallback)]
    if not found and fallback:
        return [_entry(c) for c in _run(env, fallback) if c['status'] in (cli.WARN, cli.BLOCKER)]
    return found


def setup_for(f, result):
    """Attach `setup` to a refused look/do response when the refusal is an environment problem of its target, once per distinct set of blockers."""
    if f.setup_env is None or not isinstance(result, dict) or 'setup' in result:
        return result
    hits = [r for r in reasons_of(result) if r in BLOCKERS]
    if not hits:
        return result
    env = f.setup_env()
    entries, names = [], set()
    for reason in hits:
        for entry in entries_for(reason, env):
            if entry['check'] not in names:
                names.add(entry['check'])
                entries.append(entry)
    entries = entries[:MAX_ENTRIES]
    key = frozenset((e['check'], e['status']) for e in entries)
    if not entries or key in f.setup_seen:
        return result
    f.setup_seen.add(key)
    f.event('setup_shown', checks=sorted(names))
    result['setup'] = entries
    return result


def is_verified_do(result):
    """done with a verified action: a single-form do that ended done (verified), or a plan with a press, type or confirm step that is done.
    verify-only (observed), goto and open_tab alone, and everything that is not done never count."""
    if not isinstance(result, dict) or result.get('status') != 'done':
        return False
    steps = result.get('steps')
    if isinstance(steps, list):
        return any(isinstance(s, dict) and s.get('do') in ACTIONS and s.get('status') == 'done' for s in steps)
    return result.get('verified') is True


# ---- empty states (#64): what would appear, why it matters, the one call to get it ------------------------------------------------------------------

NO_AGENT_BROWSER = ('No agent browser is running, so no browser window is listed. Call `do` with a goto step (steps=[{do:"goto", url:<the page>, expect:<text that page shows>}]) '
                    'to start it: its window then appears here, and `look` reads it by title.')
NO_WINDOWS = ('The Driver lists no windows. If apps are open, Accessibility or Screen Recording is probably not granted to CuaDriver: only the user can grant it '
              '(System Settings > Privacy & Security), then call `windows` again. If none is open, open the app, or call `do` with a goto step for a web page.')
NO_WINDOW_WITH_TITLE = 'No window has exactly that title; call `windows` without title to see every title, then pass one exactly.'


def windows_notes(f, found, title=None):
    """Extra keys for an answer of the Advanced `windows` tool: an empty list or a missing agent browser explains itself."""
    out = {}
    browser = getattr(f, 'agent_browser', None)
    if browser is not None and browser.mode == 'auto' and not browser.alive():
        out['agent_browser'] = {'running': False, 'hint': NO_AGENT_BROWSER}
    if not found.get('windows'):
        out['windows_hint'] = NO_WINDOW_WITH_TITLE if title is not None else NO_WINDOWS
    return out
