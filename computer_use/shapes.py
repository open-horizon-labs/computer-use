"""Synthetic page shapes for do tests and budget scenarios: the shapes a review found the two captured trees did not cover
(per-record labels, one record, toasts, big dialogs, list growth, disabled records, several web areas, canvas pages).

Helpers only, no tests. They build raw Driver-style element lists; ShapeDriver serves them through the same fakes as the live fixtures.
No tree captured from an unrelated real site exists yet (that needs the user's consent), so these are still synthetic.
"""
import random

from core import Facade
from test_core import FakeChooser
from test_live_shapes import LiveDriver, LiveReader, UnknownVision

PRESS = ['AXPress', 'AXShowMenu']
NAME_FIELDS = {'name': {'description': 'Provider name'}}
NAME_B = [{'field': 'name', 'op': 'contains', 'value': 'Dr. B'}]
PATTERNS = {'name': r'(Dr\. \w+)'}


class ShapeDriver(LiveDriver):
    def __init__(self, els, title='Demo'):
        super().__init__('live_booking_ax.json')
        self.fix = {'window_title': title, 'elements': els}


def E(els, parent, role, label=None, value=None, actions=PRESS, enabled=True):
    node = {'element_index': len(els), 'parent_index': parent, 'role': role, 'actions': actions, 'enabled': enabled}
    if label is not None:node['label'] = label
    if value is not None:node['value'] = value
    els.append(node);return node['element_index']


def base():
    els = [];E(els, None, 'AXWindow', actions=[]);web = E(els, 0, 'AXWebArea', 'Page', actions=['AXShowMenu']);return els, web


def cards(label=lambda n: 'Book', link=False, disabled=(), names='ABC'):
    """A ul of li-like groups: field text, optional Profile link, and the action button."""
    els, web = base();ul = E(els, web, 'AXList')
    for n in names:
        li = E(els, ul, 'AXGroup');E(els, li, 'AXStaticText', 'Dr. ' + n, 'Dr. ' + n)
        if link:E(els, li, 'AXLink', 'Profile')
        E(els, li, 'AXButton', label(n), enabled=n not in disabled)
    return els


def icon_rows():
    els, web = base();table = E(els, web, 'AXTable')
    for n in 'ABC':
        row = E(els, table, 'AXRow');c1 = E(els, row, 'AXCell');E(els, c1, 'AXStaticText', 'Dr. ' + n, 'Dr. ' + n);c2 = E(els, row, 'AXCell');E(els, c2, 'AXButton', '')
    return els


def grid():
    els, web = base();g = E(els, web, 'AXGroup')
    for n in 'ABC':
        c = E(els, g, 'AXGroup');E(els, c, 'AXHeading', 'Dr. ' + n, 'Dr. ' + n);E(els, c, 'AXButton', 'Book')
    return els


def nested():
    els, web = base()
    for s in 'XY':
        sec = E(els, web, 'AXGroup');E(els, sec, 'AXHeading', 'Sec ' + s, 'Sec ' + s)
        for n in 'AB':
            c = E(els, sec, 'AXGroup');E(els, c, 'AXStaticText', 'Dr. %s%s' % (n, s), 'Dr. %s%s' % (n, s));E(els, c, 'AXButton', 'Book')
    return els


def toolbar():
    els, web = base();E(els, web, 'AXButton', 'Save');E(els, web, 'AXButton', 'Export');return els


def canvas():
    els, web = base();E(els, web, 'AXGroup', 'canvas');return els


def frame(x, y, w, h):
    return {'x': x, 'y': y, 'w': w, 'h': h}


def emulator(menu_items=77, toolbar=False):
    """Android Emulator shape (#27): no web area; AXWindow at (100, 200) 400x800, the macOS menu bar (hangs above the window), the three
    title-bar buttons and one drawn surface with no controls."""
    els = [];win = E(els, None, 'AXWindow', 'Android Emulator', actions=[]);els[win]['frame'] = frame(100, 200, 400, 800)
    bar = E(els, win, 'AXMenuBar', actions=[]);els[bar]['frame'] = frame(0, 0, 1440, 24)
    for i in range(menu_items):els[E(els, bar, 'AXMenuItem', 'Item %d' % i)]['frame'] = frame(10 + i, 2, 40, 20)
    for sub in ('AXCloseButton', 'AXMinimizeButton', 'AXZoomButton'):
        b = E(els, win, 'AXButton', sub[2:-6]);els[b].update(subrole=sub, frame=frame(110, 205, 14, 14))
    if toolbar:
        t = E(els, win, 'AXToolbar', actions=[]);els[t]['frame'] = frame(100, 230, 400, 40)
        for label in ('Back', 'Home'):els[E(els, t, 'AXButton', label)]['frame'] = frame(120, 235, 30, 30)
    els[E(els, win, 'AXGroup', 'android surface', actions=[])]['frame'] = frame(100, 270, 400, 730)
    return els


def two_web_areas(nested_frame=False):
    els = [];E(els, None, 'AXWindow', actions=[]);popup = E(els, 0, 'AXWebArea', 'extension popup');E(els, popup, 'AXStaticText', 'hi', 'hi')
    web = E(els, 0, 'AXWebArea', 'Page');ul = E(els, web, 'AXList')
    for n in 'ABC':
        li = E(els, ul, 'AXGroup');E(els, li, 'AXStaticText', 'Dr. ' + n, 'Dr. ' + n);E(els, li, 'AXButton', 'Book')
    return els


def with_iframe():
    els = cards();web = 1;frame = E(els, web, 'AXWebArea', 'frame');E(els, frame, 'AXStaticText', 'ad', 'ad');return els


def after_click(add):
    """Script: once a click was delivered, `add(els, web_area_index)` puts new content on the page."""
    def script(driver, els):
        if driver.executed:add(els, 1)
    return script


def toast(text='Booked: Dr. B', buttons=('Undo',)):
    def add(els, web):
        E(els, web, 'AXStaticText', text, text)
        for b in buttons:E(els, web, 'AXButton', b)
    return after_click(add)


def dialog(labels, text='Confirm Dr. B'):
    def add(els, web):
        g = E(els, web, 'AXGroup');E(els, g, 'AXStaticText', text, text)
        for b in labels:E(els, g, 'AXButton', b)
    return after_click(add)


def dialog_then_toast(labels, text='Confirm Dr. B', done='Booked: Dr. B'):
    """First click opens a dialog; a second click closes it and shows the outcome."""
    def script(driver, els):
        clicks = len(driver.executed)
        if clicks == 1:
            g = E(els, 1, 'AXGroup');E(els, g, 'AXStaticText', text, text)
            for b in labels:E(els, g, 'AXButton', b)
        elif clicks >= 2:E(els, 1, 'AXStaticText', done, done)
    return script


def growth(link=False):
    def add(els, web):
        ul = 2;li = E(els, ul, 'AXGroup');E(els, li, 'AXStaticText', 'Dr. D', 'Dr. D')
        if link:E(els, li, 'AXLink', 'Profile')
        E(els, li, 'AXButton', 'Book')
    return after_click(add)


# --- option B (look, then plan): a 100-row list shaped like the suite's `invoices` task and a 3-step wizard -------------------------------------

_VENDORS = ['Contoso Supply', 'Fabrikam Freight', 'Tailspin Toys', 'Litware Labs', 'Adatum Corp', 'Proseware Inc', 'Wingtip Print',
            'Lucerne Publishing', 'Margie Travel', 'Alpine Ski House', 'Coho Vineyard', 'Humongous Insurance', 'Trey Research', 'Wide World Importers']
INVOICE_TARGET = 'inv-063'


def invoice_rows(n=100):
    """The same 100 deterministic rows as experiments/facade-vs-native/pages.py (eval-suite `invoices`): exactly one is (Northwind Traders, $1,240.00);
    the rest include near-duplicates on the vendor alone, the amount alone, and a transposed amount. (Copied, not imported: that module lives on another branch.)"""
    rng = random.Random(7)
    rows = []
    for k in range(1, n + 1):
        vendor = rng.choice(_VENDORS);amount = rng.randrange(20000, 400000) / 100.0
        if abs(amount - 1240.0) < 0.5:amount += 3.0
        rows.append([f'inv-{k:03d}', vendor, amount, f'2026-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}'])
    fixed = {17: ('Northwind Trading', 1240.00), 29: ('Contoso Supply', 1240.00), 41: ('Northwind Traders', 1204.00), 55: ('Northwind Traders', 980.00),
             63: ('Northwind Traders', 1240.00), 78: ('Northwind Traders', 12400.00), 90: ('Northwind Traders', 240.00)}
    for k, (vendor, amount) in fixed.items():
        if k <= n:rows[k - 1][1], rows[k - 1][2] = vendor, amount
    return rows


def invoices(n=100):
    """A Chrome-shaped table: a header row, then per row four text cells and an Approve button cell."""
    els, web = base();E(els, web, 'AXHeading', 'Invoices', 'Invoices');table = E(els, web, 'AXTable')
    head = E(els, table, 'AXRow')
    for title in ('Invoice', 'Vendor', 'Amount', 'Due', ''):
        c = E(els, head, 'AXCell')
        if title:E(els, c, 'AXStaticText', title, title)
    for ident, vendor, amount, due in invoice_rows(n):
        row = E(els, table, 'AXRow')
        for value in (ident.upper(), vendor, '${:,.2f}'.format(amount), due):
            c = E(els, row, 'AXCell');E(els, c, 'AXStaticText', value, value)
        c = E(els, row, 'AXCell');E(els, c, 'AXButton', 'Approve')
    return els


def approved_status(driver, els):
    """Script for invoices(): once a click was delivered, the page states which invoice was approved (from the row of the clicked button)."""
    if not driver.executed:return None
    index = int(driver.executed[-1]['element_token'].rsplit(':', 1)[1])
    by = {e['element_index']: e for e in els}
    row = by[by[index]['parent_index']]['parent_index']
    first = next(e for e in els if e.get('parent_index') is not None and by[e['parent_index']].get('parent_index') == row and e['role'] == 'AXStaticText')
    text = 'Approved ' + first['value'];E(els, 1, 'AXStaticText', text, text)


def wizard_els(step):
    """One wizard screen per step (a Back button from step 2 on); the text of each screen is ONE static text so an expect can prove it."""
    els, web = base()
    if step >= 4:
        E(els, web, 'AXStaticText', 'Setup complete.', 'Setup complete.');return els
    title = 'Step %d of 3: %s' % (step, {1: 'Plan', 2: 'Billing', 3: 'Review'}[step])
    E(els, web, 'AXStaticText', title, title)
    if step == 3:E(els, web, 'AXStaticText', 'Plan: pro, billing: annual', 'Plan: pro, billing: annual')
    if step > 1:E(els, web, 'AXButton', 'Back')
    E(els, web, 'AXButton', 'Finish' if step == 3 else 'Next');E(els, web, 'AXButton', 'Cancel')
    return els


def wizard_script(driver, els):
    """Every delivered click advances the wizard one screen (the tests only click Next, Next, Finish)."""
    return wizard_els(1 + len(driver.executed))


def run(els, goal='Book Dr. B', script=None, reader=None, chooser=None, visual=None, records='default', **kw):
    """(result, driver, reader). Defaults: records = name contains Dr. B; expect=None; no perception."""
    driver = ShapeDriver(els);driver.script = script;reader = reader or LiveReader(PATTERNS)
    chooser = chooser or FakeChooser();visual = visual or UnknownVision()
    facade = Facade(driver, generic_factory=lambda: chooser, reader_factory=lambda: reader, visual_factory=lambda: visual, sleep=lambda s: None)
    if records == 'default':records = {'fields': NAME_FIELDS, 'predicates': NAME_B}
    kw.setdefault('expect', None)
    return facade.do(goal, title='Demo', **({'records': records} if records else {}), **kw), driver, reader
