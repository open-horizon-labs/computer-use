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
        kw.setdefault('owner_scan', lambda: [])
        c = SpaceMover(binary=fake_binary(self.tmp.name, script), fault_path=Path(self.tmp.name) / ('fault-%d.json' % len(self._cleanups)), **kw)
        # Explicit test-only operator cleanup: these owners are disposable shell fakes.
        # Production stop must retain uncertain real display owners.
        self.addCleanup(self.recover_fake, c)
        return c

    @staticmethod
    def recover_fake(c):
        import subprocess
        from spaces_client import RETAINED_OWNERS
        if isinstance(c._serve, subprocess.Popen):
            if c._serve.poll() is None:
                c._serve.terminate()
            c._serve.wait(timeout=3)
            if c._serve.stdout:c._serve.stdout.close()
            if c._serve in RETAINED_OWNERS:RETAINED_OWNERS.remove(c._serve)
        if c._journal_fd is not None:
            os.close(c._journal_fd)
            c._journal_fd = None

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
                ' displays) echo \'{"inventory":"online","displays":[]}\';;\n'
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

    def test_partial_line_times_out_without_killing_or_retrying_owner(self):
        # Wrong patch: select + readline hangs, or timeout kills the owner and retries.
        c = self.client("printf '{'; exec sleep 30\n", serve_timeout=0.05)
        with self.assertRaises(SpaceMoverUnavailable):c.ensure_agent_display()
        owner = c._serve
        self.addCleanup(lambda: (owner.terminate(), owner.wait(), owner.stdout.close()))
        self.assertIsNone(owner.poll())
        c.stop()
        self.assertIsNone(owner.poll())
        with self.assertRaises(SpaceMoverUnavailable):c.ensure_agent_display()
        self.assertIs(c._serve, owner)
        fresh = SpaceMover(binary=c.binary, fault_path=c.fault_path, owner_scan=lambda: [])
        with self.assertRaises(SpaceMoverUnavailable):fresh.ensure_agent_display()
        self.assertIsNone(fresh._serve)

    def test_invalid_display_identity_latches_instead_of_accepting_boolean(self):
        c = self.client('echo \'{"created":true,"active":true,"id":true}\'\n')
        with self.assertRaises(SpaceMoverUnavailable):c.ensure_agent_display()
        owner = c._serve
        self.addCleanup(lambda: (owner.wait(), owner.stdout.close()))
        self.assertTrue(c.fault_path.exists())

    def test_teardown_never_kills_a_stalled_owner(self):
        from unittest.mock import Mock
        import subprocess
        c = self.client('exit 0\n', stop_timeout=0.01)
        owner = Mock(pid=123, stdout=None)
        owner.poll.return_value = None
        owner.wait.side_effect = subprocess.TimeoutExpired('fake', 0.01)
        c._serve, c._display = owner, 7
        with self.assertRaises(SpaceMoverUnavailable):c.stop()
        owner.terminate.assert_called_once()
        owner.kill.assert_not_called()
        c.stop()
        owner.terminate.assert_called_once()

    def test_owner_exit_is_not_proof_of_display_removal(self):
        c = self.client(self.serve_script('echo \'{"moved":true}\'').replace('"displays":[]', '"displays":[{"id":7}]'))
        c.ensure_agent_display()
        with self.assertRaises(SpaceMoverUnavailable):c.stop()
        self.assertTrue(c.fault_path.exists())

    def test_active_only_empty_inventory_cannot_prove_online_retirement(self):
        c = self.client(self.serve_script('echo \'{"moved":true}\'').replace('"inventory":"online",', ''))
        c.ensure_agent_display()
        with self.assertRaises(SpaceMoverUnavailable):c.stop()
        self.assertTrue(c.fault_path.exists())

    def test_other_known_owners_refuse_before_journal_claim(self):
        c = self.client(self.serve_script('echo \'{"moved":true}\''), owner_scan=lambda: [123])
        with self.assertRaisesRegex(SpaceMoverUnavailable, 'other known display owners'):c.ensure_agent_display()
        self.assertIsNone(c._serve)
        self.assertFalse(c.fault_path.exists())

    def test_dead_owner_is_not_automatically_replaced(self):
        c = self.client(self.serve_script('echo \'{"moved":true}\''))
        c.ensure_agent_display()
        owner = c._serve
        owner.terminate();owner.wait()
        self.addCleanup(owner.stdout.close)
        with self.assertRaises(SpaceMoverUnavailable):c.ensure_agent_display()
        self.assertIs(c._serve, owner)

    def test_pending_ownership_excludes_another_client_until_verified_teardown(self):
        c = self.client(self.serve_script('echo \'{"moved":true}\''))
        c.ensure_agent_display()
        other = SpaceMover(binary=c.binary, fault_path=c.fault_path, owner_scan=lambda: [])
        with self.assertRaises(SpaceMoverUnavailable):other.ensure_agent_display()
        self.assertIsNone(other._serve)
        c.stop()
        self.assertFalse(c.fault_path.exists())
        other.ensure_agent_display()
        other.stop()

    def test_corrupt_pending_record_never_allows_new_creation(self):
        c = self.client('exit 0\n')
        c.fault_path.write_text('{')
        with self.assertRaises(SpaceMoverUnavailable):c.ensure_agent_display()
        self.assertIsNone(c._serve)

    def test_startup_output_is_bounded(self):
        c = self.client("python3 -c 'import sys; sys.stdout.write(\"x\"*20000); sys.stdout.flush()'\n", serve_timeout=3)
        with self.assertRaises(SpaceMoverUnavailable) as caught:c.ensure_agent_display()
        owner = c._serve
        self.addCleanup(lambda: (owner.wait(), owner.stdout.close()))
        self.assertIn('output limit', str(caught.exception))

    def test_deep_json_latches_instead_of_escaping_untyped(self):
        c = self.client("python3 -c 'print(\"[\"*2000 + \"0\" + \"]\"*2000)'\n", serve_timeout=3)
        with self.assertRaises(SpaceMoverUnavailable):c.ensure_agent_display()
        self.assertEqual(c._fault['code'], 'display_lifecycle_uncertain')

    def test_teardown_signal_error_latches_without_retry(self):
        from unittest.mock import Mock
        c = self.client('exit 0\n')
        c._serve = Mock(pid=123, stdout=None)
        c._serve.poll.return_value = None
        c._serve.terminate.side_effect = ProcessLookupError()
        with self.assertRaises(SpaceMoverUnavailable):c.stop()
        c.stop()
        c._serve.terminate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
