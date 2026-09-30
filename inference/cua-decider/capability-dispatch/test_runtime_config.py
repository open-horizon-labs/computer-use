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
    def test_default_profile_is_fleet_and_selects_jev(self):
        # User decision 2026-09-30: "Jev is the default". Wrong patch: leave the clean-install default at local-mac (Julia-1).
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            config = Path(tmp) / 'runtime.json'
            self.assertFalse(config.exists(), 'a clean install has no runtime.json')
            with patch.dict(os.environ, {'CUA_RUNTIME_CONFIG': str(config)}, clear=True):
                values = load_runtime_config()
                self.assertEqual(values['profile'], 'fleet')
                self.assertEqual(os.environ['CUA_GENERIC_PROVIDER'], 'jev')
                self.assertEqual(os.environ['CUA_PAGE_EXTRACTION'], '1')
                self.assertEqual(os.environ['CUA_PROFILE'], 'fleet')

    def test_local_mac_stays_selectable_by_an_explicit_profile(self):
        # Wrong patch: drop local-mac from PROFILES, or let the fleet default override an explicit selection.
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'runtime.json'
            config.write_text(json.dumps({'profile': 'local-mac'}))
            with patch.dict(os.environ, {'CUA_RUNTIME_CONFIG': str(config)}, clear=True):
                self.assertEqual(load_runtime_config()['profile'], 'local-mac')
                self.assertEqual(os.environ['CUA_GENERIC_PROVIDER'], 'julia-1')
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {'CUA_RUNTIME_CONFIG': str(Path(tmp) / 'runtime.json'), 'CUA_PROFILE': 'local-mac'}, clear=True):
                self.assertEqual(load_runtime_config()['profile'], 'local-mac')
                self.assertEqual(os.environ['CUA_GENERIC_PROVIDER'], 'julia-1')

    def test_the_fleet_default_does_not_weaken_local_mac_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'runtime.json'
            config.write_text(json.dumps({'profile': 'local-mac'}))
            with patch.dict(os.environ, {'CUA_RUNTIME_CONFIG': str(config), 'CUA_SYSTEMONE_URL': 'https://example.invalid'}, clear=True):
                with self.assertRaisesRegex(ValueError, 'refuses hosted'):
                    load_runtime_config()

    def test_an_existing_julia_configuration_is_never_moved_to_a_hosted_profile(self):
        # Wrong patch: every configuration without a `profile` key becomes fleet (a Julia operator's page content would start going to hosted services).
        for legacy in ({'CUA_GENERIC_PROVIDER': 'julia-1', 'CUA_JULIA_COMMAND': '["/x/python", "/x/julia_worker.py", "/x/ckpt"]'},
                       {'CUA_JULIA_COMMAND': '["/x/python", "/x/julia_worker.py", "/x/ckpt"]'}):
            with tempfile.TemporaryDirectory() as tmp:
                config = Path(tmp) / 'runtime.json'
                config.write_text(json.dumps(legacy))
                with patch.dict(os.environ, {'CUA_RUNTIME_CONFIG': str(config)}, clear=True):
                    self.assertEqual(load_runtime_config()['profile'], 'local-mac', legacy)
                    self.assertEqual(os.environ['CUA_GENERIC_PROVIDER'], 'julia-1')

    def test_a_configuration_with_no_chooser_or_hosted_setting_is_a_clean_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'runtime.json'
            config.write_text(json.dumps({'CUA_PAGE_EXTRACTION': '1'}))
            with patch.dict(os.environ, {'CUA_RUNTIME_CONFIG': str(config)}, clear=True):
                self.assertEqual(load_runtime_config()['profile'], 'fleet')

    def test_fleet_profile_is_selectable_explicitly(self):
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
