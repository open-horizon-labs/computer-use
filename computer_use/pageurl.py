"""Target a page by url (look/do url=...): the browser window whose tab shows a url containing the given domain or part of the url.

Titles of browser windows change with every page and tab ("Chrome" is not a title), so the stable handle is the page's url. Resolution reads the
Driver's exact browser binding (get_browser_state tabs, browser.tab_state) of every browser window, the user's Chrome windows and the agent browser
alike, and binds ONLY when exactly one tab matches. Several is window_ambiguous (never the first), none is window_not_found, and a match that is a
background tab is tab_not_active: the Driver has no tab switch that provably leaves the window where it is, and the facade never raises a window."""
import re
from urllib.parse import urlsplit

import browser

BROWSER_APPS = re.compile(r'chrom|brave|edge|vivaldi|opera|\barc\b', re.I)  # the apps whose windows the Driver can bind over CDP
MAX_CANDIDATES = 8


def domain_of(url):
    host = (urlsplit(url).hostname or '') if '://' in (url or '') else ''
    return host or (url or '')[:60]


def _layer0(f, w):
    return next((r for r in f.titled_raw if r.get('pid') == w.get('pid') and r.get('window_id') == w.get('window_id')), {}).get('layer', 0) == 0


def resolve(f, needle):
    """{pid, window_id, title} of the one window showing the page, or core.WindowRefusal (candidates: titles and urls without query strings when several
    match; domains only, at most 8, when none does). A window the Driver will not attach to is skipped; permission_required is raised only when no
    window could be read at all."""
    from core import Gap, WindowRefusal
    want = (needle or '').strip().lower()
    if len(want) < 3 or len(want) > 200:
        raise Gap('bad_request: url must be 3 to 200 characters (a domain such as "myworkday.com" or part of the page url)')
    windows = [w for w in f.windows()['windows'] if BROWSER_APPS.search(w.get('app_name') or '') and _layer0(f, w)]
    matches, seen, errors, read = [], [], [], 0
    for w in windows:
        try:
            _, tabs = browser.tab_state(f, w['pid'], w['window_id'])
        except Gap as error:
            errors.append(error)
            continue
        read += 1
        for t in tabs:
            seen.append({'title': w['title'], 'app': w.get('app_name'), 'url': domain_of(t['url'])})
            if want in t['url'].lower():
                active = t['active'] or len(tabs) == 1 or (browser.remembered_tab(f, w['pid'], tabs) or {}).get('tab_id') == t['tab_id']
                matches.append((w, t, active))
    if not matches:
        if errors and not read:
            raise errors[0]
        shown = list(dict.fromkeys((c['title'], c['app'], c['url']) for c in seen))[:MAX_CANDIDATES]
        raise WindowRefusal('window_not_found', 'window_not_found: no open page url contains %r; open pages: %s' % (needle, '; '.join(d for _, _, d in shown) or 'none'),
                            [{'title': t, 'app': a, 'url': d} for t, a, d in shown], len(seen))
    if len(matches) > 1:
        cards = [{'title': w['title'], 'app': w.get('app_name'), 'url': (urlsplit(t['url']).netloc + urlsplit(t['url']).path)[:100]} for w, t, _ in matches][:MAX_CANDIDATES]
        raise WindowRefusal('window_ambiguous', 'window_ambiguous: %d open pages match %r; candidates: %s' % (len(matches), needle, '; '.join('%s: %s' % (c['title'], c['url']) for c in cards)),
                            cards, len(matches))
    w, tab, active = matches[0]
    if not active:
        raise WindowRefusal('tab_not_active', 'tab_not_active: the page is open in a background tab of the window titled %r; the facade never raises a window or switches tabs' % w['title'],
                            [{'title': w['title'], 'app': w.get('app_name'), 'url': domain_of(tab['url'])}], 1)
    return {'pid': w['pid'], 'window_id': w['window_id'], 'title': w['title']}
