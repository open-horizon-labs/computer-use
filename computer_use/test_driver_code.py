"""Driver.call keeps the Driver's own stdout code on a nonzero exit (deep test 2026-09-30: invalid_action_target was invisible)."""
import subprocess
import unittest
from unittest import mock

from core import Driver, DriverCallFailed


def failing(stdout):
    def run(*a, **k):raise subprocess.CalledProcessError(1, a[0], output=stdout, stderr='secret stderr text')
    return run


class DriverCode(unittest.TestCase):
    def call(self, stdout):
        with mock.patch('core.subprocess.run', failing(stdout)):
            with self.assertRaises(DriverCallFailed) as ctx:Driver('/bin/false').call('click', {})
        return ctx.exception

    def test_a_json_code_on_stdout_is_kept(self):
        # Wrong patch: drop stdout on exit 1 (the canvas bug stayed invisible as a bare driver_call_failed).
        e = self.call('{\n  "code": "invalid_action_target"\n}')
        self.assertEqual((e.kind, e.code), ('exit', 'invalid_action_target'))
        self.assertIn('invalid_action_target', str(e))

    def test_no_other_driver_text_leaks(self):
        # Wrong patch: echo stdout or stderr (Driver text may carry page or path content).
        for out in ('navigation failed: net::ERR_HTTP_RESPONSE_CODE_FAILURE', '{"code": "Has Spaces And /paths"}', ''):
            e = self.call(out)
            self.assertIsNone(e.code, out)
            self.assertNotIn('net::', str(e));self.assertNotIn('secret', str(e));self.assertNotIn('/paths', str(e))


if __name__ == '__main__':
    unittest.main()
