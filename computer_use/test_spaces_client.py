"""space-mover client (issue #60): title matching rule and error mapping against a fake binary script. No Swift runs."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from spaces_client import (SpaceMover, SpaceMoverUnavailable, SpaceMoverUntrusted, WindowNotMoved,
                           select_thumbnail, title_matches)

LONG = 'Quarterly planning document for the platform team - draft 7'


class TitleMatchTest(unittest.TestCase):
    def test_exact(self):
        self.assertTrue(title_matches('Inbox', 'Inbox'))

    def test_middle_ellipsis(self):
        self.assertTrue(title_matches('Quarterly planning…draft 7', LONG))
        self.assertTrue(title_matches('Quarterly planning…', LONG))

    def test_short_prefix_refused(self):
        self.assertFalse(title_matches('Quart…draft 7', LONG))

    def test_wrong_suffix_or_prefix(self):
        self.assertFalse(title_matches('Quarterly planning…draft 8', LONG))
        self.assertFalse(title_matches('Monthly planning!…draft 7', LONG))

    def test_none_and_plain_mismatch(self):
        self.assertFalse(title_matches(None, 'x'))
        self.assertFalse(title_matches('Inbox', 'Outbox'))


class SelectThumbnailTest(unittest.TestCase):
    TREE = json.loads((Path(__file__).parent / 'fixtures' / 'spaces' / 'mc_thumbnails.json').read_text())

    def test_unique_match_in_active_space_of_same_app(self):
        kind, t = select_thumbnail(self.TREE, 'Report', 'com.apple.TextEdit', 68)
        self.assertEqual((kind, t['AXIdentifier']), ('found', 'com.apple.TextEdit.space.68'))

    def test_same_title_in_other_space_is_ignored(self):
        kind, _ = select_thumbnail(self.TREE, 'Report', 'com.apple.TextEdit', 194)
        self.assertEqual(kind, 'found')

    def test_two_matches_are_ambiguous(self):
        kind, _ = select_thumbnail(self.TREE, LONG, 'com.apple.Safari', 68)
        self.assertEqual(kind, 'ambiguous')

    def test_none(self):
        self.assertEqual(select_thumbnail(self.TREE, 'Nope nope nope', 'com.apple.Safari', 68)[0], 'none')

    def test_other_app_not_matched(self):
        self.assertEqual(select_thumbnail(self.TREE, 'Report', 'com.apple.Notes', 68)[0], 'none')


def fake_binary(directory, script):
    path = Path(directory) / 'space-mover'
    path.write_text('#!/bin/sh\n' + script)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def client(self, script, **kw):
        c = SpaceMover(binary=fake_binary(self.tmp.name, script), **kw)
        self.addCleanup(c.stop)
        return c

    def test_missing_binary_is_unavailable(self):
        with self.assertRaises(SpaceMoverUnavailable):
            SpaceMover(binary=Path(self.tmp.name) / 'nope').spaces()

    def test_non_json_is_unavailable(self):
        with self.assertRaises(SpaceMoverUnavailable):
            self.client('echo garbage\n').spaces()

    def test_exit_3_is_untrusted(self):
        c = self.client('echo \'{"trusted":false,"reason":"grant it"}\'\nexit 3\n')
        with self.assertRaises(SpaceMoverUntrusted):
            c.run('move', '--window-id', 1)
        self.assertFalse(c.trusted())

    def test_exit_4_is_unavailable(self):
        with self.assertRaises(SpaceMoverUnavailable):
            self.client('echo \'{"reason":"no cgs"}\'\nexit 4\n').spaces()

    def test_spaces_parsed(self):
        c = self.client('echo \'{"spaces":[{"index":1,"visible":true}]}\'\n')
        self.assertEqual(c.spaces()[0]['index'], 1)

    def serve_script(self, move):
        return ('case "$1" in\n'
                ' display) echo \'{"created":true,"active":true,"id":7}\'; exec sleep 30;;\n'
                ' move) ' + move + ';;\n'
                'esac\n')

    def test_park_moves_to_agent_display_and_caches_it(self):
        c = self.client(self.serve_script('echo "{\\"moved\\":true,\\"display_id\\":$5}"'))
        self.assertEqual(c.park(11)['display_id'], 7)
        self.assertEqual(c.ensure_agent_display(), 7)
        pid = c._serve.pid
        c.ensure_agent_display()
        self.assertEqual(c._serve.pid, pid)
        c.stop()
        self.assertIsNone(c._serve)

    def test_unverified_move_raises_window_not_moved(self):
        c = self.client(self.serve_script('echo \'{"moved":false,"code":"not_verified","reason":"bounds off"}\'; exit 1'))
        with self.assertRaises(WindowNotMoved) as cm:
            c.park(11)
        self.assertEqual(cm.exception.detail['code'], 'not_verified')

    def test_space_fallback_only_when_configured(self):
        script = self.serve_script('if [ "$4" = "--display" ]; then echo \'{"moved":false,"reason":"x"}\'; exit 1; '
                                   'else echo \'{"moved":true,"code":"moved"}\'; fi')
        with self.assertRaises(WindowNotMoved):
            self.client(script).park(11)
        self.assertTrue(self.client(script, fallback_space=2).park(11)['moved'])

    def test_display_serve_failure_is_unavailable(self):
        c = self.client('echo \'{"created":false,"reason":"no classes"}\'\nexit 4\n', serve_timeout=3)
        with self.assertRaises(SpaceMoverUnavailable):
            c.ensure_agent_display()


if __name__ == '__main__':
    unittest.main()
