"""Linux scope, first check (issue #37, docs/LINUX.md task L1).

Documents the first test a Linux Chrome fixture must pass; skipped until the fixture is captured on an X11 desktop.
"""
import json
import unittest
from pathlib import Path

from core import Facade

LINUX = Path(__file__).resolve().parent / 'fixtures' / 'linux'


class LinuxFixtureTest(unittest.TestCase):
    @unittest.skip("Linux fixture needed, see docs/LINUX.md")
    def test_booking_has_exactly_one_top_level_web_area(self):
        fix = json.loads((LINUX / 'booking.ax.json').read_text())
        nodes = {e['element_index']: e for e in fix['elements']}
        self.assertEqual(len(Facade._top_web_areas({'nodes': nodes})), 1)


if __name__ == '__main__':
    unittest.main()
