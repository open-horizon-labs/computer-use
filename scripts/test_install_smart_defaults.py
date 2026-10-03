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
        self.cua.chmod(0o700)
        self.claude = self.home / '.claude.json'
        self.codex = self.home / '.codex/config.toml'
        self.codex.parent.mkdir()
        self.old = {'command': str(installer.ROOT / '.venv-facade/bin/python'), 'args': [str(installer.ROOT / 'computer_use/server.py')]}
        self.claude.write_text(json.dumps({'mcpServers': {'native': {'command': 'keep'}, 'computer-use-oh': self.old, 'cua-spaces': {'command': str(self.cua), 'args': installer.ARGS, 'timeout': 42, 'env': {'EXTRA': 'keep'}}}, 'other': 'keep'}))
        self.codex.write_text('# preserve comment\n[mcp_servers.native]\ncommand="keep"\n[mcp_servers.computer-use-oh]\ncommand=' + json.dumps(self.old['command']) + '\nargs=' + json.dumps(self.old['args']) + '\nenabled=true\n[mcp_servers.cua-spaces]\ncommand=' + json.dumps(str(self.cua)) + '\nargs=' + json.dumps(installer.ARGS) + '\nenabled=false\n')
        self.enterContext(patch.object(Path, 'home', return_value=self.home))
        self.enterContext(patch.object(installer.shutil, 'which', side_effect=lambda command: str(self.cua) if command == 'cua' else None))

    def run_install(self, check=False, spaces=True, client='both'):
        argv = ['install', '--client', client]
        if check:
            argv.append('--check')
        if spaces:
            argv.append('--with-spaces')
        with patch('sys.argv', argv):
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
        with self.assertRaises(SystemExit):
            self.run_install(check=True)
        self.assertEqual(before, (self.claude.read_bytes(), self.codex.read_bytes()))


    def test_native_install_needs_no_cua_and_does_not_register_spaces(self):
        self.claude.unlink()
        self.codex.unlink()
        self.cua.unlink()
        with patch.object(installer.shutil, 'which', return_value=None):
            self.run_install(spaces=False)
            self.run_install(check=True, spaces=False)
        self.assertFalse(self.claude.exists())
        self.assertFalse(self.codex.exists())
        self.assertTrue((self.home / '.agents/skills/computer-use/SKILL.md').is_file())

    def test_skill_only_upgrade_retires_legacy_but_preserves_spaces(self):
        before = json.loads(self.claude.read_text())['mcpServers']['cua-spaces']
        self.run_install(spaces=False)
        after = json.loads(self.claude.read_text())['mcpServers']
        self.assertEqual(after['cua-spaces'], before)
        self.assertNotIn('computer-use-oh', after)
        self.assertIn('enabled = false', self.codex.read_text())
        self.run_install(check=True, spaces=False)

    def test_stale_mandatory_instructions_fail_before_any_write(self):
        self.run_install()
        stale = self.home / '.codex/AGENTS.md'
        stale.write_text('Read ~/.agents/skills/cua-capability-dispatch/SKILL.md first.')
        before = (self.claude.read_bytes(), self.codex.read_bytes())
        for check in (False, True):
            with self.assertRaisesRegex(SystemExit, 'Obsolete skill reference'):
                self.run_install(check=check)
        self.assertEqual(before, (self.claude.read_bytes(), self.codex.read_bytes()))
        self.assertIn('cua-capability-dispatch', stale.read_text())

    def test_extra_files_are_detected_and_backed_up_outside_skill_discovery(self):
        self.run_install()
        dest = self.home / '.agents/skills/computer-use'
        extra = dest / 'references/retired-route.md'
        extra.write_text('retired instructions')
        with self.assertRaisesRegex(SystemExit, 'Skill package differs'):
            self.run_install(check=True)
        self.assertTrue(extra.is_file())
        self.run_install()
        self.assertFalse(extra.exists())
        backups = list((self.home / '.local/state/computer-use/install-backups').rglob('retired-route.md'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), 'retired instructions')
        self.assertEqual(installer.inventory(dest), installer.inventory(installer.ROOT / 'skills/computer-use'))
        self.run_install(check=True)

    def test_single_client_install_does_not_change_other_client(self):
        before = self.claude.read_bytes()
        self.run_install(client='codex')
        self.assertEqual(before, self.claude.read_bytes())
        self.assertFalse((self.home / '.claude/skills').exists())
        self.run_install(check=True, client='codex')

    def test_spaces_opt_in_requires_executable_before_writing(self):
        self.cua.chmod(0o600)
        before = (self.claude.read_bytes(), self.codex.read_bytes())
        with self.assertRaisesRegex(SystemExit, 'executable Cua CLI'):
            self.run_install()
        self.assertEqual(before, (self.claude.read_bytes(), self.codex.read_bytes()))
        self.assertFalse((self.home / '.agents/skills').exists())

    def test_fresh_spaces_install_creates_only_spaces_registration(self):
        self.claude.unlink()
        self.codex.unlink()
        self.run_install()
        import tomllib
        servers = tomllib.loads(self.codex.read_text())['mcp_servers']
        self.assertEqual(set(servers), {'cua-spaces'})
        self.run_install(check=True)

    def test_foreign_spaces_registration_is_preserved(self):
        data = json.loads(self.claude.read_text())
        data['mcpServers']['cua-spaces']['command'] = 'foreign-cua'
        self.claude.write_text(json.dumps(data))
        before = (self.claude.read_bytes(), self.codex.read_bytes())
        with self.assertRaisesRegex(SystemExit, 'cua-spaces differs'):
            self.run_install()
        self.assertEqual(before, (self.claude.read_bytes(), self.codex.read_bytes()))
        self.assertFalse((self.home / '.agents/skills').exists())

    def test_changed_symlink_is_not_replaced_or_modified(self):
        source = self.home / 'my-skill'
        source.mkdir()
        (source / 'SKILL.md').write_text('name: computer-use\\ncustom instructions')
        dest = self.home / '.agents/skills/computer-use'
        dest.parent.mkdir(parents=True)
        dest.symlink_to(source, target_is_directory=True)
        before = (self.claude.read_bytes(), self.codex.read_bytes())
        with self.assertRaisesRegex(SystemExit, 'Skill symlink differs'):
            self.run_install()
        self.assertTrue(dest.is_symlink())
        self.assertIn('custom instructions', (source / 'SKILL.md').read_text())
        self.assertEqual(before, (self.claude.read_bytes(), self.codex.read_bytes()))
        self.assertFalse((self.home / '.claude/skills').exists())

    def test_exact_source_symlink_is_supported(self):
        dest = self.home / '.agents/skills/computer-use'
        dest.parent.mkdir(parents=True)
        dest.symlink_to(installer.ROOT / 'skills/computer-use', target_is_directory=True)
        self.run_install()
        self.run_install(check=True)
        self.assertTrue(dest.is_symlink())

    def test_dangling_symlink_refuses_before_other_destinations_change(self):
        dest = self.home / '.agents/skills/computer-use'
        dest.parent.mkdir(parents=True)
        dest.symlink_to(self.home / 'missing-source', target_is_directory=True)
        before = (self.claude.read_bytes(), self.codex.read_bytes())
        with self.assertRaisesRegex(SystemExit, 'Skill symlink differs'):
            self.run_install()
        self.assertEqual(before, (self.claude.read_bytes(), self.codex.read_bytes()))
        self.assertTrue(dest.is_symlink())
        self.assertFalse((self.home / '.claude/skills').exists())


if __name__ == '__main__':
    unittest.main()
