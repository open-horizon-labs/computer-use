"""Synthetic page shapes for cua_do tests and budget scenarios: the shapes a review found the two captured trees did not cover
(per-record labels, one record, toasts, big dialogs, list growth, disabled records, several web areas, canvas pages).

Helpers only, no tests. They build raw Driver-style element lists; ShapeDriver serves them through the same fakes as the live fixtures.
No tree captured from an unrelated real site exists yet (that needs the user's consent), so these are still synthetic.
"""
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


def run(els, goal='Book Dr. B', script=None, reader=None, chooser=None, visual=None, records='default', **kw):
    """(result, driver, reader). Defaults: records = name contains Dr. B; expect=None; no perception."""
    driver = ShapeDriver(els);driver.script = script;reader = reader or LiveReader(PATTERNS)
    chooser = chooser or FakeChooser();visual = visual or UnknownVision()
    facade = Facade(driver, generic_factory=lambda: chooser, reader_factory=lambda: reader, visual_factory=lambda: visual, sleep=lambda s: None)
    if records == 'default':records = {'fields': NAME_FIELDS, 'predicates': NAME_B}
    kw.setdefault('expect', None)
    return facade.do(goal, title='Demo', **({'records': records} if records else {}), **kw), driver, reader
