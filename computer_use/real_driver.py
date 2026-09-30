"""FakeDriver over the REAL live-captured accessibility trees (computer_use/fixtures/real/, sanitized, RAW driver element format).

Captured 2026-09-28 with the facade's own Driver.observe against our fixture pages (no clicks); canvas pages also carry a real Perception parse.
Helper for tests and scripts, not a test module.
"""
import copy
import json
from pathlib import Path

from test_core import FakeDriver

REAL = Path(__file__).resolve().parent / 'fixtures' / 'real'
PAGES = ('booking', 'orders', 'invoices', 'flat_ax', 'ax_dup', 'nested', 'dynamic', 'swap', 'form', 'wizard', 'destructive',
         'canvas', 'canvas_regions', 'canvas_garbled', 'canvas_icon', 'canvas_small', 'canvas_lowcontrast')
CANVAS = tuple(p for p in PAGES if p.startswith('canvas'))


def load(name):
    return json.loads((REAL / (name + '.ax.json')).read_text())


def regions(name):
    return json.loads((REAL / (name + '.regions.json')).read_text())


class RealDriver(FakeDriver):
    """observe() serves the captured raw tree with fresh tokens per observation; `script(driver, elements)` may change it. Canvas pages get the real regions."""
    def __init__(self, page):
        super().__init__()
        self.page, self.fix, self.script, self.on_tool = page, load(page), None, None
        if page in CANVAS:
            self.perception_payload = {'installed': True, 'healthy': True, 'active_version': '0.2.1'};self.capture_id = 'cap';self.parse_result = regions(page)
    def call(self, tool, args, timeout=20):
        if self.on_tool:self.on_tool(tool)
        return super().call(tool, args, timeout)
    def observe(self, *args):
        self.version += 1
        sid = 's' + format(self.version, '08x')
        els = copy.deepcopy(self.fix['elements'])
        if self.script:els = self.script(self, els) or els
        for e in els:e.update(element_token=sid + ':' + str(e['element_index']), enabled=e.get('enabled', True))
        raw = {'snapshot_id': sid, 'pid': 1, 'window_id': 2, 'window_title': self.fix['window_title'], 'elements': els, '_image': b'pixels'}
        if self.fix.get('window_bounds'):raw['window_bounds'] = self.fix['window_bounds']
        if self.capture_id:raw['capture_id'] = self.capture_id
        return raw
