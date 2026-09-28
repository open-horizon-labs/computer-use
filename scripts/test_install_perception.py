"""Pure, network-free coverage for scripts/install_perception.py: target
selection, SHA256SUMS parsing/verification, the idempotence decision, and pin
validation. No network access, no Driver, no desktop.
"""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install_perception as ip


class ValidatePinTests(unittest.TestCase):
    def test_accepts_well_formed_pin(self):
        self.assertEqual(ip.validate_pin('cua-perception-v0.2.1'), 'cua-perception-v0.2.1')

    def test_rejects_missing_prefix(self):
        # Tempting wrong patch: accepting a bare "0.2.1" and prepending the
        # prefix silently, which could install a caller-typo'd version.
        with self.assertRaises(ip.InstallError):
            ip.validate_pin('0.2.1')

    def test_rejects_latest_alias(self):
        with self.assertRaises(ip.InstallError):
            ip.validate_pin('cua-perception-latest')


class SelectTargetTests(unittest.TestCase):
    def test_apple_silicon(self):
        self.assertEqual(ip.select_target('Darwin', 'arm64'), 'aarch64-apple-darwin')

    def test_linux_x86_64(self):
        self.assertEqual(ip.select_target('Linux', 'x86_64'), 'x86_64-unknown-linux-gnu')

    def test_windows_amd64(self):
        self.assertEqual(ip.select_target('Windows', 'AMD64'), 'x86_64-pc-windows-msvc')

    def test_unsupported_platform_raises_rather_than_guessing(self):
        # Tempting wrong patch: falling back to the Apple Silicon target (or any
        # default) instead of refusing on an unrecognized platform pair.
        with self.assertRaises(ip.InstallError):
            ip.select_target('Darwin', 'i386')


class ParseSha256sumsTests(unittest.TestCase):
    def test_parses_two_space_gnu_format(self):
        digest = 'a' * 64
        text = f'{digest}  cua-perception-0.2.1-aarch64-apple-darwin.tar.gz\n'
        self.assertEqual(ip.parse_sha256sums(text),
                         {'cua-perception-0.2.1-aarch64-apple-darwin.tar.gz': digest})

    def test_ignores_blank_and_comment_lines(self):
        digest = 'b' * 64
        text = f'# generated\n\n{digest}  file.tar.gz\n'
        self.assertEqual(ip.parse_sha256sums(text), {'file.tar.gz': digest})

    def test_rejects_malformed_line_instead_of_skipping_it(self):
        # Tempting wrong patch: silently `continue`-ing past an unparsable line,
        # which could hide a truncated/corrupted SHA256SUMS download.
        with self.assertRaises(ip.InstallError):
            ip.parse_sha256sums('not-a-valid-line\n')

    def test_rejects_short_digest(self):
        with self.assertRaises(ip.InstallError):
            ip.parse_sha256sums('abc123  file.tar.gz\n')


class VerifySha256Tests(unittest.TestCase):
    def test_matching_digest_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'f.bin'
            path.write_bytes(b'hello world')
            ip.verify_sha256(path, hashlib.sha256(b'hello world').hexdigest())

    def test_mismatched_digest_raises(self):
        # Tempting wrong patch: only warning/logging on a hash mismatch instead
        # of refusing to proceed with an unverified artifact.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'f.bin'
            path.write_bytes(b'hello world')
            with self.assertRaises(ip.InstallError):
                ip.verify_sha256(path, 'f' * 64)


class AlreadySatisfiedTests(unittest.TestCase):
    def test_exact_healthy_pin_match_is_satisfied(self):
        self.assertTrue(ip.already_satisfied(
            {'installed': True, 'healthy': True, 'active_version': '0.2.1'}, 'cua-perception-v0.2.1'))

    def test_wrong_version_is_not_satisfied(self):
        # Tempting wrong patch: treating "any installed+healthy version" as
        # satisfying a specific pin, silently drifting off the pinned release.
        self.assertFalse(ip.already_satisfied(
            {'installed': True, 'healthy': True, 'active_version': '0.2.0'}, 'cua-perception-v0.2.1'))

    def test_unhealthy_is_not_satisfied(self):
        self.assertFalse(ip.already_satisfied(
            {'installed': True, 'healthy': False, 'active_version': '0.2.1'}, 'cua-perception-v0.2.1'))

    def test_not_installed_is_not_satisfied(self):
        self.assertFalse(ip.already_satisfied({'installed': False}, 'cua-perception-v0.2.1'))


class InstallIdempotenceTests(unittest.TestCase):
    def test_check_mode_reports_satisfied_without_mutation(self):
        driver_calls = []
        ip.driver_status = lambda driver: {'installed': True, 'healthy': True, 'active_version': '0.2.1'}
        ip.run_driver = lambda *a, **k: driver_calls.append((a, k)) or None
        self.assertEqual(ip.install('cua-perception-v0.2.1', check=True, driver='cua-driver'), 0)
        self.assertEqual(driver_calls, [])

    def test_check_mode_reports_failure_without_mutation_when_not_satisfied(self):
        # Tempting wrong patch: --check silently proceeding to install anyway.
        driver_calls = []
        ip.driver_status = lambda driver: {'installed': False}
        ip.run_driver = lambda *a, **k: driver_calls.append((a, k)) or None
        self.assertEqual(ip.install('cua-perception-v0.2.1', check=True, driver='cua-driver'), 1)
        self.assertEqual(driver_calls, [])


if __name__ == '__main__':
    unittest.main()
