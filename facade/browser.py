"""Browser tabs as the unit of work (CE-FACADE-007, slice 1: navigation with landing verification).

The facade navigates only through the Driver's exact CDP binding (browser_prepare -> get_browser_state bind -> browser_navigate) on the
user's own browser profile, and a navigation counts only when the tab's fresh snapshot reports the requested page. A Driver refusal to
attach (the existing-profile grant, setup) is returned as permission_required naming what is missing: it is never rerouted to another
browser or profile. DOM-first observation and multi-page reads are slice 2.
"""
import re
from urllib.parse import urlsplit

LOGIN_PATH = re.compile(r'(^|/)(sign[-_]?in|log[-_]?in|signin|login|auth|sso|oauth2?|accounts?/(login|signin))(/|$|\.)', re.I)
LOGIN_TITLE = re.compile(r'\b(sign[ -]?in|log[ -]?in)\b', re.I)
SCHEMES = ('http', 'https')


def _gap(message):
    from core import Gap as CoreGap
    return CoreGap(message)


def check_url(url):
    """The URL a caller may navigate to: http(s) with a host. Raises core.Gap(bad_request)."""
    if not isinstance(url, str) or not url.strip() or len(url) > 2048:
        raise _gap('bad_request: url must be a nonempty http(s) URL of at most 2048 characters')
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in SCHEMES or not parts.hostname:
        raise _gap('bad_request: url must be http:// or https:// with a host (got %r)' % url[:80])
    return url.strip()


def _host(parts):
    host = (parts.hostname or '').lower()
    return host[4:] if host.startswith('www.') else host


def _path(parts):
    return (parts.path or '/').rstrip('/') or '/'


def landing(requested, final_url, title=''):
    """Pure verdict on where a navigation landed.

    ok: same host (ignoring a leading www.) and same path (ignoring a trailing slash); scheme upgrades and query/fragment changes pass.
    login_wall: the page asks to sign in (a login path or title) and the request did not ask for one: reported, never bypassed.
    navigated_elsewhere: any other host or path; the caller sees the final URL.
    unknown: the snapshot reported no URL.
    """
    if not isinstance(final_url, str) or not final_url:
        return 'unknown'
    want, got = urlsplit(requested), urlsplit(final_url)
    if _host(want) == _host(got) and _path(want) == _path(got):
        return 'ok'
    asked_for_login = bool(LOGIN_PATH.search(want.path or ''))
    if not asked_for_login and (LOGIN_PATH.search(got.path or '') or LOGIN_TITLE.search(title or '')):
        return 'login_wall'
    return 'navigated_elsewhere'


def _refusal_code(error):
    text = str(error)
    return text.split('Driver refused:', 1)[1].strip() if 'Driver refused:' in text else None


def _permission(code, action):
    return _gap('permission_required: the Driver refused to %s (%s). Attaching to your browser profile needs the Driver started with '
                '`serve --grant existing-profile`; nothing was opened in another browser or profile' % (action, code))


def _tabs(bound):
    tabs = bound.get('tabs') or []
    return [t for t in tabs if isinstance(t, dict) and t.get('tab_id')]


def _call(f, tool, args):
    """A Driver call whose refusal is a Gap whether the Driver raised it or returned it as data."""
    from core import Gap as CoreGap
    value = f.driver.call(tool, {'session': f.session, **args})
    if isinstance(value, dict) and (value.get('refusal') or value.get('status') == 'refused'):
        raise CoreGap('Driver refused: ' + str((value.get('refusal') or {}).get('code', 'unknown')))
    return value


def bind(f, pid, window_id):
    """Exact CDP binding for one native browser window: (target_id, tab_id of its active tab). Prepares the existing-profile endpoint once."""
    from core import Gap as CoreGap
    call = lambda tool, args: _call(f, tool, args)
    try:
        bound = call('get_browser_state', {'pid': pid, 'window_id': window_id})
    except CoreGap as error:
        code = _refusal_code(error)
        if code is None:
            raise
        try:
            call('browser_prepare', {'pid': pid, 'window_id': window_id, 'strategy': {'kind': 'existing_profile'}})
        except CoreGap as prepare_error:
            raise _permission(_refusal_code(prepare_error) or code, 'attach to this browser window')
        try:
            bound = call('get_browser_state', {'pid': pid, 'window_id': window_id})
        except CoreGap as again:
            raise _permission(_refusal_code(again) or code, 'bind this browser window after setup')
    target = bound.get('target_id')
    tabs = _tabs(bound)
    active = [t for t in tabs if t.get('active') or t.get('selected')]
    tab = (active or (tabs if len(tabs) == 1 else []))
    if not target or len(tab) != 1:
        raise _gap('browser_tab_ambiguous: the window is bound to %d tabs and none is reported active; bring the tab to the front of its window' % len(tabs))
    return target, tab[0]['tab_id']


def page_of(f, target, tab):
    """The tab's page as the Driver's own snapshot reports it: {url, title}."""
    snap = _call(f, 'get_browser_state', {'target_id': target, 'tab_id': tab, 'snapshot_format': 'semantic_v2'})
    page = snap.get('page') or {}
    return {'url': page.get('url') or '', 'title': page.get('title') or ''}


def settle(f, check):
    """Bounded, deterministic wait for a landing to be decided: the look's own OBSERVE_RETRY_DELAYS, nothing longer."""
    from core import OBSERVE_RETRY_DELAYS
    if check():
        return
    for delay in OBSERVE_RETRY_DELAYS:
        f.sleep(delay)
        if check():
            return


def navigate(f, pid, window_id, url):
    """Navigate the window's active tab and verify the landing. Returns {'status': 'ok', 'page': ...} or raises core.Gap with a typed reason."""
    from core import Gap as CoreGap
    url = check_url(url)
    target, tab = bind(f, pid, window_id)
    try:
        _call(f, 'browser_navigate', {'target_id': target, 'tab_id': tab, 'url': url})
    except CoreGap as error:
        raise _permission(_refusal_code(error), 'navigate this tab')
    seen = {}
    def check():
        page = page_of(f, target, tab)
        verdict = landing(url, page['url'], page['title'])
        seen.update(page=page, verdict=verdict)
        return verdict != 'unknown' and not (verdict == 'navigated_elsewhere' and page['url'] in ('', 'about:blank'))
    settle(f, check)
    verdict, page = seen.get('verdict', 'unknown'), seen.get('page', {'url': '', 'title': ''})
    if verdict == 'ok':
        return {'status': 'ok', 'page': page}
    if verdict == 'login_wall':
        raise _gap('login_wall: the page asks you to sign in (%s); sign in yourself in that browser, then call again. Nothing was typed' % page['url'][:200])
    if verdict == 'navigated_elsewhere':
        raise _gap('navigated_elsewhere: asked for %s, the tab shows %s' % (url[:200], page['url'][:200]))
    raise _gap('landing_unknown: the Driver reported no page URL for the tab after navigating; the tab may still be loading')


# ---- tabs (Driver 0.30.4 has no tab-create/close tool: the browser's own Cmd+T / Cmd+W, verified against the Driver's tab list) ----

def tab_state(f, pid, window_id):
    """(ids of the window's tabs, the active tab id or None), from a fresh exact bind."""
    bound = _bound(f, pid, window_id)
    tabs = _tabs(bound)
    active = [t['tab_id'] for t in tabs if t.get('active') or t.get('selected')]
    return [t['tab_id'] for t in tabs], (active[0] if len(active) == 1 else None)


def _bound(f, pid, window_id):
    from core import Gap as CoreGap
    try:
        return _call(f, 'get_browser_state', {'pid': pid, 'window_id': window_id})
    except CoreGap as error:
        code = _refusal_code(error)
        if code is None:
            raise
        bind(f, pid, window_id)  # prepares the existing-profile endpoint or raises permission_required
        return _call(f, 'get_browser_state', {'pid': pid, 'window_id': window_id})


def _hotkey(f, pid, window_id, keys):
    f.driver.call('hotkey', {'session': f.session, 'pid': pid, 'window_id': window_id, 'keys': keys, 'delivery_mode': 'background'})


def open_tab(f, pid, window_id, url):
    """Open one new tab in the window (Cmd+T), verified: exactly one new tab id and it is the active tab. Then navigate it (landing verified).
    Records the tab as opened by the facade, so close_tab may close it later. A Cmd+T that shows no new tab stops tab_not_opened: it is
    NOT retried (a delayed tab would make two)."""
    url = check_url(url)
    before, _ = tab_state(f, pid, window_id)
    _hotkey(f, pid, window_id, ['cmd', 't'])
    seen = {}
    def check():
        ids, active = tab_state(f, pid, window_id)
        new = [t for t in ids if t not in before]
        seen.update(new=new, active=active)
        return len(new) == 1 and active == new[0]
    settle(f, check)
    if not (len(seen.get('new', [])) == 1 and seen.get('active') == seen['new'][0]):
        raise _gap('tab_not_opened: after Cmd+T the window shows %d new tabs%s; it was not retried' % (
            len(seen.get('new', [])), '' if seen.get('active') in seen.get('new', []) else ' and the active tab is not a new one'))
    tab = seen['new'][0]
    f.opened_tabs = getattr(f, 'opened_tabs', set()) | {tab}
    return {**navigate(f, pid, window_id, url), 'tab': tab}


def close_tab(f, pid, window_id):
    """Close the window's active tab only when the facade opened it (never one of the user's own tabs), then verify it is gone."""
    ids, active = tab_state(f, pid, window_id)
    mine = getattr(f, 'opened_tabs', set())
    if active is None or active not in mine:
        raise _gap('tab_not_opened_by_facade: the active tab was not opened by cua_do (open_tab); only tabs this session opened are closed. Nothing was pressed')
    _hotkey(f, pid, window_id, ['cmd', 'w'])
    seen = {}
    def check():
        now, _ = tab_state(f, pid, window_id)
        seen['gone'] = active not in now
        return seen['gone']
    settle(f, check)
    if not seen.get('gone'):
        raise _gap('tab_not_closed: the tab is still listed after Cmd+W; it was not retried')
    f.opened_tabs = mine - {active}
    return {'status': 'ok', 'closed': active}
