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


# Driver refusal codes that mean the user has not granted or prepared the browser attachment. Any other refusal is NOT a permission problem
# (live 2026-09-30: a goto to a 404 page was reported permission_required).
PERMISSION_CODES = frozenset({'browser_consent_required', 'browser_requires_setup', 'existing_profile_not_granted', 'consumer_profile_endpoint_requires_grant',
                              'permission_denied', 'browser_permission_required'})


def _navigate_refused(code, action):
    code = code or 'refused'
    if code in PERMISSION_CODES:
        return _permission(code or 'refused', action)
    return _gap('navigate_refused: the Driver refused to %s (%s); nothing else was tried' % (action, code))


def _permission(code, action):
    return _gap('permission_required: the Driver refused to %s (%s). Attaching to your browser profile needs the Driver started with '
                '`serve --grant existing-profile`; nothing was opened in another browser or profile' % (action, code))


def _tabs(bound):
    tabs = bound.get('tabs') or []
    return [t for t in tabs if isinstance(t, dict) and t.get('tab_id')]


def _call(f, tool, args):
    """A Driver call whose refusal is a Gap whether the Driver raised it or returned it as data."""
    from core import Gap as CoreGap
    value = f._read(tool, lambda: f.driver.call(tool, {'session': f.session, **args}))
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
    from core import Gap as CoreGap, DriverCallFailed
    url = check_url(url)
    target, tab = bind(f, pid, window_id)
    try:
        _call(f, 'browser_navigate', {'target_id': target, 'tab_id': tab, 'url': url})
    except DriverCallFailed as error:
        # Live 2026-09-30: a 404 is exit 1 'navigation failed: net::ERR_HTTP_RESPONSE_CODE_FAILURE' (no refusal code): the page did not
        # load. Not a permission, not a landing: its own reason, no Driver text.
        raise _gap('navigate_failed: the page did not load (an HTTP error or a network failure; %s); nothing else was tried' % (getattr(error, 'kind', None) or 'error'))
    except CoreGap as error:
        raise _navigate_refused(_refusal_code(error), 'navigate this tab')
    seen = {}
    def check():
        page = page_of(f, target, tab)
        verdict = landing(url, page['url'], page['title'])
        seen.update(page=page, verdict=verdict)
        return verdict != 'unknown' and not (verdict == 'navigated_elsewhere' and page['url'] in ('', 'about:blank'))
    settle(f, check)
    return _verdict(url, seen)


def _verdict(url, seen):
    verdict, page = seen.get('verdict', 'unknown'), seen.get('page', {'url': '', 'title': ''})
    if verdict == 'ok':
        return {'status': 'ok', 'page': page}
    if verdict == 'login_wall':
        gap = _gap('login_wall: the page asks you to sign in (%s); sign in yourself in that browser, then call again. Nothing was typed' % page['url'][:200])
    elif verdict == 'navigated_elsewhere':
        gap = _gap('navigated_elsewhere: asked for %s, the tab shows %s' % (url[:200], page['url'][:200]))
    else:
        gap = _gap('landing_unknown: the Driver reported no page URL for the tab after navigating; the tab may still be loading')
    gap.page = page  # where the tab actually is: open_tab records it so the tab it opened can still be closed
    raise gap


# ---- tabs (Driver 0.30.4 and 0.31.0 have no tab-create/close tool: Cmd+T opens; the tab's own AX Close button closes; Cmd+W is an explicit foreground fallback) ----
# Measured live on 0.31.0: target_id and every tab_id are RE-MINTED on each bind (no stable id), the list order is NOT the window's tab
# order (a new tab was listed first), and after a navigation no tab is reported active. What is reliable: each tab's url and title, the tab
# count, and the bind's native_title (the window's own title, which is the ACTIVE tab's title). So the facade's tab is recognised by its
# landed url being unique among the tabs, the count being unchanged, and native_title being that tab's title; never by an id or position.

NEW_TAB_URLS = ('chrome://newtab/', 'chrome://new-tab-page/', 'about:blank', 'edge://newtab/', 'brave://newtab/', 'chrome-search://local-ntp/local-ntp.html')


def tab_state(f, pid, window_id):
    """[{position, url, title, active, tab_id (valid for THIS bind only)}] from a fresh exact bind, plus the bind's target_id."""
    bound = _bound(f, pid, window_id)
    f.native_title = bound.get('native_title') or ''
    tabs = [{'position': i, 'url': t.get('url') or '', 'title': t.get('title') or '', 'active': bool(t.get('active') or t.get('selected')), 'tab_id': t['tab_id']}
            for i, t in enumerate(_tabs(bound))]
    return bound.get('target_id'), tabs


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


def _hotkey(f, pid, window_id, keys, foreground=False):
    # Measured live (0.31.0, Chrome): Cmd+T is accepted in the background; Cmd+W is not (a menu key-equivalent; the Driver documents
    # foreground delivery for those), so close_tab fronts the window briefly and only with the caller's explicit permission.
    f.driver.call('hotkey', {'session': f.session, 'pid': pid, 'window_id': window_id, 'keys': keys, 'delivery_mode': 'foreground' if foreground else 'background'})


def _active(tabs):
    on = [t for t in tabs if t['active']]
    return on[0] if len(on) == 1 else None


def open_tab(f, pid, window_id, url):
    """Open one new tab (Cmd+T), verified: exactly one more tab than before and the active tab is a fresh new-tab page. Then navigate THAT
    tab (its id from the same bind) with the goto landing checks, and record (window, position, landed url, tab count) so close_tab can
    recognise it later. A Cmd+T that shows no new tab stops tab_not_opened: it is NOT retried (a delayed tab would make two)."""
    url = check_url(url)
    _, before = tab_state(f, pid, window_id)
    _hotkey(f, pid, window_id, ['cmd', 't'])
    seen = {}
    def check():
        target, tabs = tab_state(f, pid, window_id)
        active = _active(tabs)
        seen.update(target=target, tabs=tabs, active=active)
        return len(tabs) == len(before) + 1 and active is not None and active['url'] in NEW_TAB_URLS
    settle(f, check)
    tabs, active = seen.get('tabs', []), seen.get('active')
    if not (len(tabs) == len(before) + 1 and active is not None and active['url'] in NEW_TAB_URLS):
        raise _gap('tab_not_opened: after Cmd+T the window has %d tabs (was %d) and the active tab is %s; it was not retried' % (
            len(tabs), len(before), 'a new-tab page' if active and active['url'] in NEW_TAB_URLS else (active or {}).get('url', 'unknown')[:80] or 'unknown'))
    try:
        landed = _navigate_tab(f, seen['target'], active['tab_id'], url)
    except _core_gap() as error:
        # The tab IS open even though its landing failed (redirect, login wall, unknown): remember where it is so it can be closed, never left behind.
        page = getattr(error, 'page', None) or {'url': active['url'], 'title': active['title']}
        _remember_tab(f, pid, window_id, page, len(tabs))
        raise
    _remember_tab(f, pid, window_id, landed['page'], len(tabs))
    return landed


def _remember_tab(f, pid, window_id, page, count):
    if page.get('url'):
        f.opened_tabs = [t for t in getattr(f, 'opened_tabs', []) if t['window'] != (pid, window_id)] + [
            {'window': (pid, window_id), 'url': page['url'], 'title': page.get('title') or '', 'count': count}]


def _navigate_tab(f, target, tab, url):
    from core import Gap as CoreGap, DriverCallFailed
    try:
        _call(f, 'browser_navigate', {'target_id': target, 'tab_id': tab, 'url': url})
    except DriverCallFailed as error:
        # Live 2026-09-30: a 404 is exit 1 'navigation failed: net::ERR_HTTP_RESPONSE_CODE_FAILURE' (no refusal code): the page did not
        # load. Not a permission, not a landing: its own reason, no Driver text.
        raise _gap('navigate_failed: the page did not load (an HTTP error or a network failure; %s); nothing else was tried' % (getattr(error, 'kind', None) or 'error'))
    except CoreGap as error:
        raise _navigate_refused(_refusal_code(error), 'navigate this tab')
    seen = {}
    def check():
        page = page_of(f, target, tab)
        verdict = landing(url, page['url'], page['title'])
        seen.update(page=page, verdict=verdict)
        return verdict != 'unknown' and not (verdict == 'navigated_elsewhere' and page['url'] in ('', 'about:blank') + NEW_TAB_URLS)
    settle(f, check)
    return _verdict(url, seen)


def _titled(native, title):
    """The window's title shows the active tab: Chrome writes '<tab title> - Google Chrome' (or '- <profile>'), so a prefix match."""
    return bool(title) and (native == title or native.startswith(title + ' - ') or native.startswith(title + ' \u2013 '))


def _under_web_area(nodes, index):
    seen = set()
    while index in nodes and index not in seen:
        seen.add(index)
        index = nodes[index].get('parent_index')
        if index in nodes and nodes[index].get('role') == 'AXWebArea':
            return True
    return False


def _tab_label(label, title):
    """Chrome names the tab-strip radio button '<title> - Memory usage - 32.4 MB' (live capture 2026-09-29): the title itself, or the title
    followed by ' - ' and Chrome's suffix. Never a plain substring ('Three Targets' must not match 'Three Targets 2 - ...')."""
    label = label or ''
    return label == title or label.startswith(title + ' - ')


def close_control(f, pid, window_id, title):
    """The Close button of the tab-strip tab titled `title`, as an observed element id ('e<n>') of a fresh observation (snapshot handle too).

    Measured live (#4, Driver 0.28.2 and 0.31.0, Chrome): the window's AX tree has one AXRadioButton per tab, named with the tab title,
    whose AX child button is named Close; pressing it through the Driver's background accessibility route closes exactly that tab.
    Exactly one radio button may carry the title, outside any page (AXWebArea), with exactly one Close child; otherwise
    tab_close_control_not_found / tab_close_control_ambiguous, before anything is pressed."""
    if not title:
        raise _gap('tab_close_control_not_found: the recorded tab has no title to find in the tab strip')
    obs = f.observe(pid, window_id)
    nodes = f.state(obs['snapshot'])['nodes']
    tabs = [i for i, n in nodes.items() if n.get('role') == 'AXRadioButton' and _tab_label(n.get('label'), title) and not _under_web_area(nodes, i)]
    if not tabs:
        raise _gap('tab_close_control_not_found: no tab in the window\'s tab strip is titled %r' % title[:80])
    if len(tabs) > 1:
        raise _gap('tab_close_control_ambiguous: %d tabs in the tab strip carry the title %r; none was pressed' % (len(tabs), title[:80]))
    closes = [i for i, n in nodes.items() if n.get('parent_index') == tabs[0] and n.get('role') == 'AXButton' and (n.get('label') or '').strip().lower().startswith('close')]
    if not closes:
        raise _gap('tab_close_control_not_found: the tab titled %r has no Close button in the tab strip' % title[:80])
    if len(closes) > 1:
        raise _gap('tab_close_control_ambiguous: the tab titled %r has %d Close buttons; none was pressed' % (title[:80], len(closes)))
    return obs['snapshot'], 'e%d' % closes[0]


def close_tab(f, pid, window_id, allow_foreground=False):
    """Close the tab open_tab opened in this window, only when it is recognisably that tab: its landed URL appears exactly once among the
    tabs and the count is unchanged since opening (tab ids and order mean nothing across binds, measured).

    Route: press the Close child of the tab's own tab-strip radio button (title matched, exactly one) through the facade's normal bound
    click (an observed element, revalidated by act): background delivery, no window fronting, no allow_foreground. Only when the strip shows
    no such control AND the step passed allow_foreground is the old fallback used: Cmd+W, foreground, and only if the window's own title
    shows that tab (Cmd+W closes the ACTIVE tab). Afterwards that URL must be gone and the count one lower, else tab_not_closed (never retried)."""
    from core import StaleUI
    _, tabs = tab_state(f, pid, window_id)
    mine = [t for t in getattr(f, 'opened_tabs', []) if t['window'] == (pid, window_id)]
    same = [t for t in tabs if mine and t['url'] == mine[0]['url']]
    if not (mine and len(same) == 1 and len(tabs) == mine[0]['count']):
        raise _gap('tab_not_opened_by_facade: the tab is not recognisably the one do opened (its address must appear once and the tab count must be unchanged since open_tab); only that tab is closed. Nothing was pressed')
    control = None
    try:
        control = close_control(f, pid, window_id, mine[0]['title'])
    except _core_gap() as error:
        if str(error).split(':', 1)[0] != 'tab_close_control_not_found' or allow_foreground is not True:
            raise
    if control:
        # The press is revalidated over the whole window; a page that just loaded is still changing (its buttons gain AXPress, the tab's
        # title settles), which refuses StaleUI with nothing pressed (live 2026-09-30: read_pages left a tab open). Re-find and retry ONCE.
        for tries in (1, 2):
            try:
                f.act(f.bind_press(control[0], control[1], 'Close the tab do opened'))
                break
            except StaleUI:
                if tries == 2:
                    raise _gap('tab_strip_changed: the window changed between finding the tab\'s Close button and pressing it, twice; nothing was pressed')
                f.sleep(getattr(f, 'RETRY_BACKOFF_S', 0.3))
                control = close_control(f, pid, window_id, mine[0]['title'])
        how = 'pressing its Close button'
    else:
        if not _titled(getattr(f, 'native_title', ''), mine[0]['title']):
            raise _gap('tab_not_opened_by_facade: the window is not showing the tab do opened, and Cmd+W closes the active tab. Nothing was pressed')
        _hotkey(f, pid, window_id, ['cmd', 'w'], foreground=True)
        how = 'Cmd+W'
    seen = {}
    def check():
        _, now = tab_state(f, pid, window_id)
        seen.update(count=len(now), gone=all(t['url'] != mine[0]['url'] for t in now))
        return seen['count'] == len(tabs) - 1 and seen['gone']
    settle(f, check)
    if not (seen.get('count') == len(tabs) - 1 and seen.get('gone')):
        raise _gap('tab_not_closed: after %s the window has %s tabs (was %d) and the tab is %s; it was not retried' % (how, seen.get('count'), len(tabs), 'gone' if seen.get('gone') else 'still listed'))
    f.opened_tabs = [t for t in getattr(f, 'opened_tabs', []) if t['window'] != (pid, window_id)]
    return {'status': 'ok', 'closed': mine[0]['url']}


def _core_gap():
    from core import Gap
    return Gap


# ---- multi-page read (#34): open_tab -> look -> close_tab per url, each page independent ----

READ_PAGES_MAX = 5           # urls per step
READ_PAGES_BUDGET_S = 90.0   # wall budget for the whole step: a page that has begun is finished (and its tab closed), then the budget is checked before the next
STOP_ALL = ('permission_required', 'tab_not_opened', 'browser_tab_ambiguous', 'foreground_required')  # the window cannot open tabs at all: asking again would only repeat it
SAMPLE_RECORDS = 3
SAMPLE_LINES = 4
SAMPLE_CHARS = 50
TEXT_LINES = 4


def _page_summary(response):
    """A small, bounded view of one page's look (its look_id says what it showed; the full look is one look away on that page)."""
    import look as lk
    out = {'title': (response.get('window') or {}).get('title'), 'record_kind': response.get('record_kind'), 'records': (response.get('counts') or {}).get('records', 0),
           'text': [lk.cut(x, SAMPLE_CHARS)[0] for x in (response.get('text') or [])[:TEXT_LINES]]}
    out['sample'] = [{'r': r['r'], 'lines': [lk.cut(x, SAMPLE_CHARS)[0] for x in r['lines'][:SAMPLE_LINES]], **({'values': r['values']} if r.get('values') else {}),
                      **({'dom_lines': r['dom_lines'][:SAMPLE_LINES]} if r.get('dom_lines') else {})} for r in (response.get('records') or [])[:SAMPLE_RECORDS]]
    if response.get('degraded'):
        out['degraded'] = response['degraded']
    if (response.get('sources_disagree') or {}).get('dom_only'):
        out['sources_disagree'] = response['sources_disagree']
    return out


def read_pages(f, pid, window_id, urls, fields=None, budget_s=READ_PAGES_BUDGET_S):
    """For each url, in order: open ONE new tab in the window (the user's own tab is never navigated), verify the landing, look (read-only), close the tab
    this call opened. Returns [{url, status: ok|failed|skipped, landing, look_id?, summary?, close?, reason?, message?}], one per url, in order.

    Every page stands alone: a page that does not land (navigated_elsewhere, login_wall, landing_unknown) is reported with its verdict and the other
    pages are still read; nothing is skipped silently (a skipped page says why). Only a condition that would repeat for every page stops the rest
    (no permission, Cmd+T opens nothing, a tab that could not be closed: opening more would leave more tabs behind), and every skipped url is listed."""
    import look as lk
    from core import Gap
    began = f.clock()
    pages, stop = [], None
    for url in urls:
        entry = {'url': url}
        pages.append(entry)
        if stop is None and f.clock() - began >= budget_s:
            stop = 'budget_exceeded'
        if stop:
            entry.update(status='skipped', reason=stop)
            continue
        mine = lambda: [t for t in getattr(f, 'opened_tabs', []) if t['window'] == (pid, window_id)]
        prior = mine()  # a tab an earlier step opened in this window: never mistaken for this page's tab, and restored afterwards
        try:
            landed = open_tab(f, pid, window_id, url)
            entry.update(status='ok', landing='ok', final_url=landed['page']['url'][:200])
        except Gap as gap:
            reason = str(gap).split(':', 1)[0]
            entry.update(status='failed', landing=reason, reason=reason, message=str(gap)[:200])
            if reason in STOP_ALL:
                stop = reason
        opened = bool(mine()) and not (prior and mine()[0] is prior[0])
        if entry['status'] == 'ok':
            seen = lk.run_look(f, None, pid, window_id, fields)
            if seen.get('status') == 'ok':
                entry.update(look_id=seen['look_id'], summary=_page_summary(seen))
            else:
                entry.update(status='failed', reason='look_' + str(seen.get('status')), message=str(seen.get('message') or seen.get('reason') or seen.get('hint') or '')[:200])
        if opened:
            try:
                close_tab(f, pid, window_id)
                entry['closed'] = True
            except Gap as gap:
                entry['closed'] = False
                entry['close'] = {'status': 'failed', 'reason': str(gap).split(':', 1)[0], 'message': str(gap)[:200]}
                stop = stop or 'previous_tab_not_closed'
            else:
                f.opened_tabs = [t for t in getattr(f, 'opened_tabs', []) if t['window'] != (pid, window_id)] + prior
    return pages
