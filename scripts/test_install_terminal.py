import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import install_terminal as installer


class TerminalInstallerTests(unittest.TestCase):
    def test_checksum_failure_preserves_existing_install(self):
        with tempfile.TemporaryDirectory() as raw:
            binary=Path(raw)/'tu';binary.write_bytes(b'old')
            with self.assertRaisesRegex(ValueError,'checksum mismatch'):
                installer.install(raw,'Darwin','arm64',fetch=lambda _:b'corrupt')
            self.assertEqual(binary.read_bytes(),b'old')

    def test_atomic_install_is_idempotent_and_executable(self):
        payload=b'fixture'
        with tempfile.TemporaryDirectory() as raw,patch.dict(installer.TARGETS,{('Test','Test'):('fixture',hashlib.sha256(payload).hexdigest())}):
            calls=[]
            def fetch(url):calls.append(url);return payload
            for _ in range(2):destination=installer.install(raw,'Test','Test',fetch=fetch)
            self.assertEqual(len(calls),1)
            self.assertIn('/v1.4.1/tu_fixture',calls[0])
            self.assertEqual(destination.read_bytes(),payload)
            self.assertEqual(destination.stat().st_mode & 0o777,0o755)

    def test_unsupported_platform_does_not_fetch(self):
        with self.assertRaisesRegex(ValueError,'No pinned'):
            installer.install('/unused','Windows','AMD64',fetch=lambda _:self.fail('download attempted'))
