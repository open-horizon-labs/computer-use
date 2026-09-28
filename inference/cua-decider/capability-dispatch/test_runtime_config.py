import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime_config import load_runtime_config
from providers import FleetGeneric
import importlib.util

switcher_path = Path(__file__).resolve().parents[3] / 'scripts/set_profile.py'
spec = importlib.util.spec_from_file_location('set_profile', switcher_path)
switcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(switcher)


class RuntimeProfileTests(unittest.TestCase):
    def test_default_profile_is_local_and_selects_julia(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            config = Path(tmp) / 'runtime.json'
            with patch.dict(os.environ, {'CUA_RUNTIME_CONFIG': str(config)}, clear=True):
                values = load_runtime_config()
                self.assertEqual(values['profile'], 'local-mac')
                self.assertEqual(os.environ['CUA_GENERIC_PROVIDER'], 'julia-1')
                self.assertEqual(os.environ['CUA_PAGE_EXTRACTION'], '1')

    def test_fleet_profile_is_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'runtime.json'
            config.write_text(json.dumps({'profile': 'fleet'}))
            with patch.dict(os.environ, {'CUA_RUNTIME_CONFIG': str(config)}, clear=True):
                values = load_runtime_config()
                self.assertEqual(values['profile'], 'fleet')
                self.assertEqual(os.environ['CUA_GENERIC_PROVIDER'], 'jev')

    def test_legacy_jev_config_migrates_to_fleet(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'runtime.json'
            config.write_text(json.dumps({'CUA_GENERIC_PROVIDER': 'jev'}))
            with patch.dict(os.environ, {'CUA_RUNTIME_CONFIG': str(config)}, clear=True):
                values = load_runtime_config()
                self.assertEqual(values['profile'], 'fleet')
                self.assertEqual(os.environ['CUA_GENERIC_PROVIDER'], 'jev')

    def test_local_profile_rejects_hosted_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'runtime.json'
            config.write_text(json.dumps({'profile': 'local-mac',
                                          'CUA_EXTRACT_URL': 'https://example.invalid'}))
            with patch.dict(os.environ, {'CUA_RUNTIME_CONFIG': str(config)}, clear=True):
                with self.assertRaisesRegex(ValueError, 'refuses hosted'):
                    load_runtime_config()

    def test_local_profile_rejects_jev_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'runtime.json'
            config.write_text(json.dumps({'profile': 'local-mac'}))
            with patch.dict(os.environ, {'CUA_RUNTIME_CONFIG': str(config),
                                         'CUA_GENERIC_PROVIDER': 'jev'}, clear=True):
                with self.assertRaisesRegex(ValueError, 'requires Julia-1'):
                    load_runtime_config()

    def test_local_profile_rejects_direct_fleet_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'runtime.json'
            config.write_text(json.dumps({'profile': 'local-mac'}))
            with patch.dict(os.environ, {'CUA_RUNTIME_CONFIG': str(config)}, clear=True):
                with self.assertRaisesRegex(ValueError, 'FleetGeneric is unavailable'):
                    FleetGeneric()

    def test_switching_profiles_preserves_fleet_settings_and_isolates_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'runtime.json'
            config.write_text(json.dumps({
                'CUA_GENERIC_PROVIDER': 'jev',
                'CUA_EXTRACT_URL': 'http://fleet.example/extract',
                'CUA_PAGE_EXTRACTION': '1',
            }))
            switcher.switch(config, 'local-mac')
            local = json.loads(config.read_text())
            self.assertEqual(local['profile'], 'local-mac')
            self.assertEqual(local['profiles']['fleet']['CUA_GENERIC_PROVIDER'], 'jev')
            with patch.dict(os.environ, {'CUA_RUNTIME_CONFIG': str(config)}, clear=True):
                active = load_runtime_config()
                self.assertEqual(active['profile'], 'local-mac')
                self.assertEqual(os.environ['CUA_GENERIC_PROVIDER'], 'julia-1')
                self.assertNotIn('CUA_EXTRACT_URL', os.environ)
            switcher.switch(config, 'fleet')
            with patch.dict(os.environ, {'CUA_RUNTIME_CONFIG': str(config)}, clear=True):
                active = load_runtime_config()
                self.assertEqual(active['profile'], 'fleet')
                self.assertEqual(os.environ['CUA_GENERIC_PROVIDER'], 'jev')
                self.assertEqual(os.environ['CUA_EXTRACT_URL'], 'http://fleet.example/extract')


if __name__ == '__main__':
    unittest.main()
