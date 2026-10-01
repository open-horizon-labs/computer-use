"""Linux fixtures (issue #37, docs/LINUX.md task L1): real captures from Chrome for Testing on Xvfb, Cua Driver 0.31.0.

The screenshot bytes are the only thing removed from the captures (see docs/LINUX.md, "Measured facts"). These tests pin what the
captures contain; L2 (the role normaliser) will flip the web-area lookup test.
"""
import json
import unittest
from pathlib import Path

from core import Facade

ROOT = Path(__file__).resolve().parent


class LinuxFixtureTest(unittest.TestCase):
    def _nodes(self, name):
        fix = json.loads((ROOT / 'fixtures' / 'linux' / f'{name}.ax.json').read_text())
        return {e['element_index']: e for e in fix['elements']}

    def test_raw_tree_has_exactly_one_document_web_node_per_capture(self):
        for name in ('booking', 'orders', 'form', 'canvas'):
            docs = [e for e in self._nodes(name).values() if e['role'] == 'document web']
            self.assertEqual(len(docs), 1, name)

    def test_macos_web_area_lookup_finds_nothing_until_the_normaliser_exists(self):
        # Measured gap (L2): Linux Chrome's web root is role "document web", not "AXWebArea".
        self.assertEqual(len(Facade._top_web_areas({'nodes': self._nodes('booking')})), 0)

    def test_page_nodes_carry_in_web_content_and_browser_chrome_does_not(self):
        nodes = list(self._nodes('booking').values())
        self.assertTrue(any(e.get('in_web_content') and e['role'] == 'push button' and e.get('label') == 'Book' for e in nodes))
        self.assertFalse(any(e.get('in_web_content') for e in nodes if e['role'] in ('tool bar', 'frame', 'page tab')))


if __name__ == '__main__':
    unittest.main()
