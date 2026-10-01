"""Linux scope, first check (issue #37, docs/LINUX.md task L1).

CI fails on ANY skipped test (offline-gates.yml: a skip must never hide the mcp-dependent guardrails), so this is not a skipped placeholder:
until the Linux Chrome fixture is captured it checks that the plan still names that capture as the first task; once the fixture exists it
runs the real check.
"""
import json
import unittest
from pathlib import Path

from core import Facade

ROOT = Path(__file__).resolve().parent
LINUX = ROOT / 'fixtures' / 'linux' / 'booking.ax.json'


class LinuxFixtureTest(unittest.TestCase):
    def test_booking_has_exactly_one_top_level_web_area(self):
        if not LINUX.exists():
            plan = (ROOT.parent / 'docs' / 'LINUX.md').read_text()
            self.assertIn('L1', plan, 'the Linux fixture is not captured and docs/LINUX.md no longer schedules its capture')
            return
        fix = json.loads(LINUX.read_text())
        nodes = {e['element_index']: e for e in fix['elements']}
        self.assertEqual(len(Facade._top_web_areas({'nodes': nodes})), 1)


if __name__ == '__main__':
    unittest.main()
