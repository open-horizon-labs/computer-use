"""Product setup regressions; use disposable client configs, never the real home."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import install_smart_defaults as installer


class SmartDefaultsInstall(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.cua = self.home / 'cua'
        self.cua.write_text('fixture executable path')
        self.claude = self.home / '.claude.json'
        self.codex = self.home / '.codex/config.toml'
        self.codex.parent.mkdir()
        self.old = {'command': str(installer.ROOT / '.venv-facade/bin/python'), 'args': [str(installer.ROOT / 'computer_use/server.py')]}
        self.claude.write_text(json.dumps({'mcpServers': {'native': {'command': 'keep'}, 'computer-use-oh': self.old, 'cua-spaces': {'command': str(self.cua), 'args': installer.ARGS, 'timeout': 42, 'env': {'EXTRA': 'keep'}}}, 'other': 'keep'}))
        self.codex.write_text('# preserve comment\n[mcp_servers.native]\ncommand="keep"\n[mcp_servers.computer-use-oh]\ncommand=' + json.dumps(self.old['command']) + '\nargs=' + json.dumps(self.old['args']) + '\nenabled=true\n[mcp_servers.cua-spaces]\ncommand=' + json.dumps(str(self.cua)) + '\nargs=' + json.dumps(installer.ARGS) + '\nenabled=false\n')
        self.enterContext(patch.object(Path, 'home', return_value=self.home))
        self.enterContext(patch.object(installer.shutil, 'which', return_value=str(self.cua)))

    def run_install(self, check=False):
        with patch('sys.argv', ['install', '--check'] if check else ['install']):
            installer.main()

    def test_preserves_native_options_repairs_disabled_profile_and_is_idempotent(self):
        self.run_install()
        first = (self.claude.read_bytes(), self.codex.read_bytes())
        self.run_install()
        self.run_install(check=True)
        self.assertEqual(first, (self.claude.read_bytes(), self.codex.read_bytes()))
        data = json.loads(first[0])
        self.assertEqual(data['mcpServers']['native'], {'command': 'keep'})
        self.assertEqual(data['mcpServers']['cua-spaces']['env']['EXTRA'], 'keep')
        self.assertEqual(data['mcpServers']['cua-spaces']['timeout'], 42)
        self.assertIn(b'# preserve comment', first[1])

    def test_foreign_registration_is_not_overwritten(self):
        data = json.loads(self.claude.read_text())
        data['mcpServers']['computer-use-oh']['command'] = 'foreign-wrapper'
        self.claude.write_text(json.dumps(data))
        before = (self.claude.read_bytes(), self.codex.read_bytes())
        with self.assertRaises(SystemExit):
            self.run_install()
        self.assertEqual(before, (self.claude.read_bytes(), self.codex.read_bytes()))
        self.assertFalse((self.home / '.agents/skills').exists())

    def test_read_only_check_detects_old_setup_without_mutating_it(self):
        before = (self.claude.read_bytes(), self.codex.read_bytes())
        with self.assertRaises(AssertionError):
            self.run_install(check=True)
        self.assertEqual(before, (self.claude.read_bytes(), self.codex.read_bytes()))


if __name__ == '__main__':
    unittest.main()
