"""The ten jobs and how each is judged. Prompts state user intent only: never the answer, a decoy or a tool hint.

Ground truth, by kind:
  events  the fixture server's event log (booking, orders, form, upload)
  text    the agent's final message compared with a value the HARNESS obtained independently
          (compare: fixture constants; wikipedia: fetched; calculator: computed; android: getprop; ios: simctl)
  doc     the TextEdit document text, read by the harness through AppleScript before it closes the document unsaved

Outcomes: correct | wrong | no-action | timeout. `no-action` means the agent never acted (no MCP tool call, and for
events no event). Nothing here operates the desktop; the live probes take injectable callables so tests use fake data.
"""
import html
import re
import subprocess
from decimal import Decimal, InvalidOperation

import fixtures as fx

CALC_EXPRESSION = '47 x 28'
CALC_ANSWER = '1316'
TEXTEDIT_SENTENCE = 'The quarterly review moved to Thursday at ten'
WIKI_PAGE = 'Mount_Everest'
WIKI_URL = 'https://en.wikipedia.org/wiki/' + WIKI_PAGE
ANDROID_AVD = 'androidnaa-api35'
UPLOAD_NAME = 'invoice-4471-scan.txt'
UPLOAD_SIZE = 3072

_F = fx.FORM_VALUES
TASKS = {
    'booking': {'n': 1, 'surface': 'web', 'kind': 'events', 'route': '/booking', 'title': 'Clinic Slots {run}',
                'prompt': 'Book the earliest 30-minute appointment with Dr. Morgan Reyes that starts at or after 2:00 PM. Book exactly one appointment.',
                'expected': [{'action': 'book', 'id': fx.BOOKING_EXPECTED_ID}],
                'forbidden': [{'action': 'book', 'id_not': [fx.BOOKING_EXPECTED_ID]}]},
    'orders': {'n': 2, 'surface': 'web', 'kind': 'events', 'route': '/orders', 'title': 'Orders {run}',
               'prompt': 'Cancel my walnut desk lamp order that has not shipped yet. Do not cancel or change any other order.',
               'expected': [{'action': 'cancel_request', 'id': fx.ORDERS_EXPECTED_ID}, {'action': 'cancel_confirm', 'id': fx.ORDERS_EXPECTED_ID}],
               'forbidden': [{'action': 'cancel_confirm', 'id_not': [fx.ORDERS_EXPECTED_ID]}, {'action': 'cancel_request', 'id_not': [fx.ORDERS_EXPECTED_ID]}]},
    'form': {'n': 3, 'surface': 'web', 'kind': 'events', 'route': '/form', 'title': 'Intake Form {run}',
             'prompt': ('Fill in the intake form and send it. Name: %(name)s. Email: %(email)s. Phone: %(phone)s. Department: Billing. '
                        'I want an emailed copy of the request. Message: "%(message)s"' % _F),
             'expected': [{'action': 'submit', 'id': 'intake', 'values': dict(_F)}],
             'forbidden': [{'action': 'submit', 'id': 'intake', 'unless_values': dict(_F)}]},
    'upload': {'n': 4, 'surface': 'web', 'kind': 'events', 'route': '/upload', 'title': 'Support Request {run}',
               'prompt': 'Attach the file {file} to the support request form and send the request.',
               'expected': [{'action': 'upload'}], 'forbidden': []},  # judged against the prepared file's name, size and sha256
    'compare': {'n': 5, 'surface': 'web', 'kind': 'text', 'route': '/shop', 'title': 'Lamp Shop {run}',
                'prompt': 'Which lamp in this shop is the cheapest one that is currently in stock? Reply with just its name and price.'},
    'wikipedia': {'n': 6, 'surface': 'web', 'kind': 'text', 'url': WIKI_URL, 'title': 'Mount Everest - Wikipedia',
                  'prompt': ('On the English Wikipedia page for Mount Everest, what elevation does the infobox give for the highest point, in metres? '
                             'Only read the page: do not log in, edit or fill in anything.')},
    'calculator': {'n': 7, 'surface': 'mac', 'kind': 'text', 'app': 'Calculator', 'title': 'Calculator',
                   'prompt': 'Use the Calculator app to work out %s and tell me the number it shows.' % CALC_EXPRESSION},
    'textedit': {'n': 8, 'surface': 'mac', 'kind': 'doc', 'app': 'TextEdit', 'title': 'TextEdit',
                 'prompt': 'Create a new TextEdit document containing exactly this sentence and leave it open without saving: %s' % TEXTEDIT_SENTENCE},
    'android': {'n': 9, 'surface': 'android', 'kind': 'text', 'title': 'Android Emulator',
                'prompt': 'On the Android emulator, find out which Android version it is running (Settings, About) and tell me.'},
    'ios': {'n': 10, 'surface': 'ios', 'kind': 'text', 'title': 'Simulator',
            'prompt': 'In the iOS Simulator, find out which iOS version it is running (Settings, General, About) and tell me.'},
}
ORDER = sorted(TASKS, key=lambda t: TASKS[t]['n'])


# ---- event-log judging -------------------------------------------------------------
def _matches(spec, event):
    if event.get('action') != spec['action']:
        return False
    if 'id' in spec and event.get('id') != spec['id']:
        return False
    if 'id_not' in spec and event.get('id') in spec['id_not']:
        return False
    if 'values' in spec and (event.get('values') or {}) != spec['values']:
        return False
    if 'unless_values' in spec and (event.get('values') or {}) == spec['unless_values']:
        return False
    return True


def judge_events(task, events, timed_out=False):
    """(outcome, detail) from the server log. Any forbidden event is wrong; all expected in order is correct."""
    spec = TASKS[task]
    events = sorted(events, key=lambda e: e.get('ts', 0))
    forbidden = [e for e in events if any(_matches(s, e) for s in spec['forbidden'])]
    if forbidden:
        return 'wrong', {'wrong_events': len(forbidden)}
    want, done = spec['expected'], 0
    for e in events:
        if done < len(want) and _matches(want[done], e):
            done += 1
    if done == len(want):
        return 'correct', {}
    if events:
        return 'wrong', {'note': 'acted but did not complete (%d of %d expected events)' % (done, len(want))}
    return ('timeout' if timed_out else 'no-action'), {}


def judge_upload(events, expected, timed_out=False):
    """expected = {filename, size, sha256} of the file the harness prepared."""
    ups = [e for e in events if e.get('action') == 'upload']
    if not ups:
        return ('timeout' if timed_out else 'no-action'), {}
    ok = [e for e in ups if (e.get('values') or {}) == {'filename': expected['filename'], 'size': str(expected['size']), 'sha256': expected['sha256']}]
    if ok and len(ok) == len(ups):
        return 'correct', {}
    return 'wrong', {'uploads': [e.get('values') for e in ups]}


# ---- text judging --------------------------------------------------------------------
def numbers_in(text):
    """Decimals found in text, thousands separators removed ('8,848.86 m' -> {Decimal('8848.86')})."""
    out = set()
    for token in re.findall(r'\d[\d,]*(?:\.\d+)?', text or ''):
        try:
            out.add(Decimal(token.replace(',', '')))
        except InvalidOperation:
            pass
    return out


def version_tokens(text):
    return set(re.findall(r'\d+(?:\.\d+)*', text or ''))


def _version_equal(token, truth):
    strip = lambda v: re.sub(r'(\.0)+$', '', v)
    return strip(token) == strip(truth)


def judge_text(task, text, truth, acted, timed_out=False):
    """(outcome, detail) comparing the agent's final message with the harness's independent value."""
    text = (text or '').strip()
    if not text or not acted:
        return ('timeout' if timed_out else 'no-action'), {}
    if task == 'compare':
        nums = numbers_in(text)
        has = Decimal(truth['price']) in nums and truth['name'].lower() in text.lower()
        decoys = [p for p in fx.COMPARE_DECOY_PRICES if Decimal(p) in nums]
        # Mentioning the decoys while explaining the choice is fine (both arms did on 2026-10-01); the answer must name the right lamp
        # and price, and must not name a decoy lamp as the answer in its first line.
        first = text.splitlines()[0].lower() if text else ''
        wrong_lead = any(n.lower() in first for n in getattr(fx, 'COMPARE_DECOY_NAMES', ()))
        return ('correct' if has and not wrong_lead else 'wrong'), ({'decoy_prices_mentioned': decoys} if decoys else {})
    if task in ('wikipedia', 'calculator'):
        raw = str(truth).strip()
        try:
            return ('correct' if Decimal(raw.replace(',', '')) in numbers_in(text.replace(',', '')) else 'wrong'), {}
        except InvalidOperation:  # a non-numeric truth (e.g. a name or a date): normalised substring match
            norm = lambda v: re.sub(r'\s+', ' ', v).strip().lower()
            return ('correct' if norm(raw) in norm(text) else 'wrong'), {'truth_kind': 'text'}
    if task in ('android', 'ios'):
        return ('correct' if any(_version_equal(t, str(truth)) for t in version_tokens(text)) else 'wrong'), {}
    raise ValueError('no text judge for %s' % task)


def judge_doc(doc_text, acted, timed_out=False):
    """TextEdit: the document the harness read must hold exactly the sentence (surrounding whitespace ignored)."""
    if doc_text is None or not doc_text.strip():
        return ('timeout' if timed_out else 'no-action'), {}
    return ('correct' if doc_text.strip() == TEXTEDIT_SENTENCE else 'wrong'), {'document': doc_text.strip()[:200]}


def judge(task, *, events=(), text='', truth=None, doc=None, acted=False, timed_out=False):
    kind = TASKS[task]['kind']
    if task == 'upload':
        return judge_upload(list(events), truth, timed_out)
    if kind == 'events':
        return judge_events(task, list(events), timed_out)
    if kind == 'doc':
        return judge_doc(doc, acted, timed_out)
    return judge_text(task, text, truth, acted, timed_out)


# ---- independent ground-truth probes (harness side) ------------------------------------
def parse_infobox_value(page_html, label='Elevation'):
    """First number of an infobox row, as a string without separators ('8848.86'), or None."""
    for th, td in re.findall(r'<th[^>]*infobox-label[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>', page_html, re.S):
        if html.unescape(re.sub(r'<[^>]+>', '', th)).strip().lower() == label.lower():
            m = re.search(r'\d[\d,]*(?:\.\d+)?', html.unescape(re.sub(r'<[^>]+>', '', td)))
            return m.group(0).replace(',', '') if m else None
    return None


def wikipedia_truth(fetch=None):
    """Elevation of Mount Everest from the page's lead infobox (MediaWiki parse API), fetched by the harness."""
    import json
    import urllib.request
    url = 'https://en.wikipedia.org/w/api.php?action=parse&page=%s&prop=text&section=0&format=json&formatversion=2' % WIKI_PAGE
    if fetch is None:
        fetch = lambda u: urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'computer-use-surfaces-ab/1.0'}), timeout=20).read().decode()
    value = parse_infobox_value(json.loads(fetch(url))['parse']['text'])
    if value is None:
        raise RuntimeError('could not read the infobox elevation from Wikipedia')
    return value


def _sh(argv, timeout=30):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def android_truth(sh=_sh, serial=None):
    """Android release string from the running emulator (`adb shell getprop ro.build.version.release`)."""
    argv = ['adb'] + (['-s', serial] if serial else []) + ['shell', 'getprop', 'ro.build.version.release']
    out = sh(argv).stdout.strip()
    if not out:
        raise RuntimeError('adb getprop returned nothing')
    return out


def ios_truth(udid, sh=_sh):
    """iOS version of the simulator: the booted device's runtime from `simctl list devices -j` (e.g. ...iOS-26-5 -> 26.5)."""
    import json
    data = json.loads(sh(['xcrun', 'simctl', 'list', 'devices', '-j']).stdout)
    for runtime, devices in data.get('devices', {}).items():
        for d in devices:
            if d.get('udid') == udid:
                m = re.search(r'iOS-(\d+(?:-\d+)*)$', runtime)
                if m:
                    return m.group(1).replace('-', '.')
    raise RuntimeError('simulator %s not found in simctl list' % udid)
