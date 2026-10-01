"""doctor and bootstrap (issue #63) against fakes: no network, no desktop, no real commands."""
import io
import json
import tempfile
import unittest
from pathlib import Path

import cli
from cli import Env, OK, WARN, BLOCKER, SKIPPED

STATUS_UP = 'Cua Driver daemon is running\n  socket: /sock\n  pid: 42\n'
PERMS_OK = json.dumps({'accessibility': True, 'screen_recording': True})


def fake_env(commands=None, files=(), environ=None, http=None, home='/home/u', root='/repo', which=None, contents=None):
    """commands: {first-arg-prefix tuple -> (rc, out, err)}; files: paths that exist."""
    commands = commands or {}
    calls = []
    present = set(files) | set((contents or {}).keys())

    def run(argv, timeout):
        calls.append((list(argv), timeout))
        for prefix, answer in commands.items():
            if tuple(argv[:len(prefix)]) == prefix:
                return answer
        return None, '', ''

    env = Env(run=run, exists=lambda p: str(p) in present, read_text=lambda p: (contents or {})[str(p)], environ=environ if environ is not None else {},
              http=http or (lambda url, timeout: (200, '')), which=which or (lambda n: '/bin/' + n), home=home, root=root, system='darwin')
    env.calls = calls
    return env


D = '/home/u/.local/bin/cua-driver'


class DriverChecksTest(unittest.TestCase):
    def test_installed_ok_and_blocker(self):
        self.assertEqual(cli.check_driver_installed(fake_env({(D, '--version'): (0, 'cua-driver 0.31.0', '')}))['status'], OK)
        r = cli.check_driver_installed(fake_env())
        self.assertEqual(r['status'], BLOCKER)
        self.assertTrue(r['fix'])

    def test_daemon(self):
        self.assertEqual(cli.check_driver_daemon(fake_env({(D, 'status'): (0, STATUS_UP, '')}, files=['/sock']))['status'], OK)
        self.assertEqual(cli.check_driver_daemon(fake_env({(D, 'status'): (0, STATUS_UP, '')}))['status'], WARN)
        self.assertEqual(cli.check_driver_daemon(fake_env({(D, 'status'): (1, 'not running', '')}))['status'], BLOCKER)

    def test_grant(self):
        up = {(D, 'status'): (0, STATUS_UP, '')}
        ok = cli.check_driver_grant(fake_env({**up, ('ps',): (0, 'cua-driver serve --grant existing-profile', '')}))
        self.assertEqual(ok['status'], OK)
        self.assertEqual(cli.check_driver_grant(fake_env({**up, ('ps',): (0, 'cua-driver serve', '')}))['status'], BLOCKER)
        self.assertEqual(cli.check_driver_grant(fake_env(up))['status'], WARN)
        self.assertEqual(cli.check_driver_grant(fake_env())['status'], SKIPPED)

    def test_permissions(self):
        key = (D, 'permissions', 'status', '--json')
        self.assertEqual(cli.check_driver_permissions(fake_env({key: (0, PERMS_OK, '')}))['status'], OK)
        bad = cli.check_driver_permissions(fake_env({key: (0, json.dumps({'accessibility': True, 'screen_recording': False}), '')}))
        self.assertEqual(bad['status'], BLOCKER)
        self.assertIn('Screen & System Audio Recording', bad['fix'])
        self.assertEqual(cli.check_driver_permissions(fake_env())['status'], SKIPPED)

    def test_signing(self):
        app = '/Applications/CuaDriver.app'
        self.assertEqual(cli.check_driver_signing(fake_env())['status'], SKIPPED)
        self.assertEqual(cli.check_driver_signing(fake_env({('codesign',): (0, '', 'Authority=Developer ID')}, files=[app]))['status'], OK)
        self.assertEqual(cli.check_driver_signing(fake_env({('codesign',): (0, '', 'Signature=adhoc')}, files=[app]))['status'], WARN)

    def test_full_disk_access_is_always_a_manual_warning(self):
        r = cli.check_full_disk_access(fake_env())
        self.assertEqual(r['status'], WARN)
        self.assertIn('Full Disk Access', r['fix'])

    def test_perception(self):
        key = (D, 'extension', 'status', 'cua-perception', '--json')
        self.assertEqual(cli.check_perception(fake_env({key: (0, json.dumps({'installed': True, 'healthy': True, 'active_version': '0.2.1'}), '')}))['status'], OK)
        self.assertEqual(cli.check_perception(fake_env({key: (0, json.dumps({'installed': False}), '')}))['status'], WARN)
        self.assertEqual(cli.check_perception(fake_env({key: (0, json.dumps({'installed': True, 'healthy': False}), '')}))['status'], BLOCKER)
        self.assertEqual(cli.check_perception(fake_env())['status'], WARN)


class ToolChecksTest(unittest.TestCase):
    def test_node(self):
        self.assertEqual(cli.check_node(fake_env({('node',): (0, 'v20.1.0', '')}))['status'], OK)
        self.assertEqual(cli.check_node(fake_env({('node',): (0, 'v16.0.0', '')}))['status'], WARN)
        self.assertEqual(cli.check_node(fake_env())['status'], WARN)
        self.assertEqual(cli.check_node(fake_env({('node',): (0, 'v20.1.0', '')}, which=lambda n: None))['status'], WARN)

    def test_adb(self):
        self.assertEqual(cli.check_adb(fake_env({('adb',): (0, 'List of devices attached\nemulator-5554\tdevice\n', '')}))['status'], OK)
        self.assertEqual(cli.check_adb(fake_env({('adb',): (0, 'List of devices attached\n', '')}))['status'], WARN)
        self.assertEqual(cli.check_adb(fake_env())['status'], SKIPPED)

    def test_simctl(self):
        booted = '== Devices ==\n    iPhone 17 Pro (ABC) (Booted)\n'
        self.assertEqual(cli.check_simctl(fake_env({('xcrun',): (0, booted, '')}))['status'], OK)
        self.assertEqual(cli.check_simctl(fake_env({('xcrun',): (0, '== Devices ==\n', '')}))['status'], WARN)
        self.assertEqual(cli.check_simctl(fake_env())['status'], SKIPPED)

    def test_space_mover(self):
        binary = '/repo/computer_use/spaces/bin/space-mover'
        self.assertEqual(cli.check_space_mover(fake_env())['status'], WARN)
        self.assertEqual(cli.check_space_mover(fake_env({(binary, 'trusted'): (0, '{"trusted": true}', '')}, files=[binary]))['status'], OK)
        untrusted = cli.check_space_mover(fake_env({(binary, 'trusted'): (3, '{"trusted": false}', '')}, files=[binary]))
        self.assertEqual(untrusted['status'], WARN)
        self.assertIn('Accessibility', untrusted['fix'])
        self.assertEqual(cli.check_space_mover(fake_env({(binary, 'trusted'): (0, 'junk', '')}, files=[binary]))['status'], WARN)

    def test_python_venv(self):
        venv = '/repo/.venv-facade/bin/python'
        self.assertEqual(cli.check_python(fake_env())['status'], BLOCKER)
        self.assertEqual(cli.check_python(fake_env({(venv,): (1, '', 'ImportError')}, files=[venv]))['status'], BLOCKER)
        self.assertEqual(cli.check_python(fake_env({(venv,): (0, '', '')}, files=[venv]))['status'], OK)


class AgentBrowserTest(unittest.TestCase):
    def test_absent_module_is_neutral(self):
        self.assertEqual(cli.check_agent_browser(fake_env(), module=cli.ABSENT)['status'], SKIPPED)
        self.assertIn('not present in this checkout', cli.check_agent_browser(fake_env(), module=cli.ABSENT)['detail'])

    def test_env_path(self):
        self.assertEqual(cli.check_agent_browser(fake_env(environ={'CUA_AGENT_BROWSER_PATH': '/b'}, files=['/b']))['status'], OK)
        self.assertEqual(cli.check_agent_browser(fake_env(environ={'CUA_AGENT_BROWSER_PATH': '/b'}))['status'], BLOCKER)

    def test_module_present(self):
        class Mod:
            installed_path = staticmethod(lambda: '/cft')
        self.assertEqual(cli.check_agent_browser(fake_env(files=['/cft']), module=Mod)['status'], OK)
        self.assertEqual(cli.check_agent_browser(fake_env(), module=Mod)['status'], WARN)
        self.assertEqual(cli.check_agent_browser(fake_env(), module=object())['status'], WARN)


class ConfigChecksTest(unittest.TestCase):
    RUNTIME = '/home/u/.config/computer-use/runtime.json'

    def test_runtime(self):
        self.assertEqual(cli.check_runtime(fake_env())['status'], OK)
        self.assertEqual(cli.check_runtime(fake_env(contents={self.RUNTIME: '{"profile": "local-mac"}'}))['status'], OK)
        self.assertEqual(cli.check_runtime(fake_env(contents={self.RUNTIME: '{bad'}))['status'], BLOCKER)

    def test_providers_each_bounded_and_classified(self):
        seen = []

        def http(url, timeout):
            seen.append((url, timeout))
            return {'https://x/extract': (200, ''), 'https://s/one': (None, 'URLError')}[url]
        rt = json.dumps({'CUA_EXTRACT_URL': 'https://x/extract', 'CUA_SYSTEMONE_URL': 'https://s/one'})
        env = fake_env(http=http, contents={self.RUNTIME: rt}, files=['/home/u/.local/share/fleet-cua-decider/select-fleet'])
        results = {r['name']: r for r in cli.check_providers(env)}
        self.assertEqual(results['provider.cua_extract_url']['status'], OK)
        self.assertEqual(results['provider.cua_systemone_url']['status'], WARN)
        self.assertEqual(results['provider.selector']['status'], OK)
        self.assertTrue(all(t <= 10 for _, t in seen))
        self.assertEqual(len(seen), 2)

    def test_provider_5xx_warns_and_unconfigured_skips(self):
        env = fake_env(environ={'CUA_EXTRACT_URL': 'https://x'}, http=lambda u, t: (503, ''))
        results = {r['name']: r for r in cli.check_providers(env)}
        self.assertEqual(results['provider.cua_extract_url']['status'], WARN)
        self.assertEqual(results['provider.cua_systemone_url']['status'], SKIPPED)

    def test_selector_command_malformed_is_blocker_and_never_run(self):
        env = fake_env(environ={'CUA_SELECTOR_COMMAND': 'not json'})
        results = {r['name']: r for r in cli.check_providers(env)}
        self.assertEqual(results['provider.selector']['status'], BLOCKER)
        self.assertEqual(env.calls, [])

    def test_local_mac_uses_no_hosted_endpoint(self):
        env = fake_env(environ={'CUA_PROFILE': 'local-mac'}, http=lambda u, t: self.fail('no request'))
        self.assertEqual(cli.check_providers(env)[0]['status'], SKIPPED)

    def test_mcp_registration(self):
        path = '/home/u/.claude.json'
        server = '/repo/computer_use/server.py'

        def with_servers(servers, files=(server,)):
            return fake_env(contents={path: json.dumps({'mcpServers': servers})}, files=files)
        good = {'computer-use-oh': {'command': 'py', 'args': [server]}}
        self.assertEqual(cli.check_mcp_registration(with_servers(good))['status'], OK)
        self.assertEqual(cli.check_mcp_registration(with_servers({}))['status'], WARN)
        stale = cli.check_mcp_registration(with_servers({**good, 'cua-task': {}}))
        self.assertEqual(stale['status'], WARN)
        self.assertIn('cua-task', stale['detail'])
        old_path = cli.check_mcp_registration(with_servers({'computer-use-oh': {'args': ['/repo/facade/server.py']}}))
        self.assertIn('computer_use/server.py', old_path['detail'])
        self.assertEqual(cli.check_mcp_registration(with_servers(good, files=()))['status'], WARN)
        self.assertEqual(cli.check_mcp_registration(fake_env())['status'], WARN)
        reserved = cli.check_mcp_registration(with_servers({'computer-use': {'command': 'py', 'args': [server]}}))
        self.assertEqual(reserved['status'], BLOCKER)
        self.assertIn('reserved name in Claude Code; run bootstrap --yes to rename', reserved['fix'])
        both = cli.check_mcp_registration(with_servers({**good, 'computer-use': {}}))
        self.assertEqual(both['status'], BLOCKER)

    def test_skill(self):
        cur = '/home/u/.claude/skills/computer-use/SKILL.md'
        self.assertEqual(cli.check_skill(fake_env(files=[cur]))['status'], OK)
        self.assertEqual(cli.check_skill(fake_env())['status'], WARN)
        stale = cli.check_skill(fake_env(files=[cur, '/home/u/.claude/skills/cua-capability-dispatch']))
        self.assertEqual(stale['status'], WARN)
        self.assertIn('cua-capability-dispatch', stale['detail'])


class ProbeTest(unittest.TestCase):
    class FakeProc:
        def __init__(self, line):
            import os
            r, w = os.pipe()
            os.write(w, line.encode())
            os.close(w)
            self.stdout = os.fdopen(r)
            self.stopped = False

        def terminate(self):
            self.stopped = True

        def wait(self, timeout=None):
            return 0

    def probe(self, line):
        procs = []

        def popen(argv, **kw):
            procs.append(self.FakeProc(line))
            return procs[0]
        binary = '/repo/computer_use/spaces/bin/space-mover'
        env = fake_env(files=[binary])
        env.popen = popen
        return cli.check_space_mover_probe(env, timeout=2), procs[0]

    def test_ok_and_child_stopped(self):
        r, proc = self.probe('{"created": true, "active": true, "id": 7}\n')
        self.assertEqual(r['status'], OK)
        self.assertTrue(proc.stopped)

    def test_failure_warns_and_child_stopped(self):
        r, proc = self.probe('{"created": false, "reason": "no classes"}\n')
        self.assertEqual(r['status'], WARN)
        self.assertIn('no classes', r['detail'])
        self.assertTrue(proc.stopped)

    def test_probe_builds_when_missing(self):
        env = fake_env({('/bin/sh',): (1, '', 'boom')})
        self.assertEqual(cli.check_space_mover_probe(env)['status'], WARN)
        self.assertEqual(env.calls[0][1], 180)


class DoctorOutputTest(unittest.TestCase):
    def run_doctor(self, env, *flags):
        out = io.StringIO()
        code = cli.main(['doctor', *flags], env=env, out=out)
        return code, out.getvalue()

    def healthy(self):
        venv = '/repo/.venv-facade/bin/python'
        return fake_env({(D, '--version'): (0, 'cua-driver 0.31.0', ''), (D, 'status'): (0, STATUS_UP, ''), ('ps',): (0, 'x --grant existing-profile', ''),
                         (D, 'permissions', 'status', '--json'): (0, PERMS_OK, ''), (venv,): (0, '', ''),
                         (D, 'extension', 'status', 'cua-perception', '--json'): (0, '{"installed": true, "healthy": true, "active_version": "1"}', '')},
                        files=['/sock', venv])

    def test_json_shape_and_exit_zero(self):
        code, text = self.run_doctor(self.healthy(), '--json')
        data = json.loads(text)
        self.assertEqual(code, 0)
        self.assertTrue(data['ok'])
        for check in data['checks']:
            self.assertEqual(set(check), {'name', 'status', 'detail', 'fix'})
            self.assertIn(check['status'], {OK, WARN, BLOCKER, SKIPPED})

    def test_blocker_exits_one_and_human_line_has_fix(self):
        code, text = self.run_doctor(fake_env())
        self.assertEqual(code, 1)
        self.assertIn('[BLOCKER] driver.installed', text)
        self.assertIn('fix:', text)
        self.assertIn('blocker', text.splitlines()[-1])

    def test_warnings_alone_exit_zero(self):
        code, _ = self.run_doctor(self.healthy())
        self.assertEqual(code, 0)

    def test_json_blocker(self):
        code, text = self.run_doctor(fake_env(), '--json')
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(text)['ok'])

    def test_a_crashing_check_becomes_a_warning(self):
        original = cli.STATIC_CHECKS
        cli.STATIC_CHECKS = (lambda env: 1 / 0,)
        try:
            results = cli.run_checks(fake_env())
        finally:
            cli.STATIC_CHECKS = original
        self.assertEqual(results[0]['status'], WARN)

    def test_doctor_is_read_only(self):
        env = self.healthy()
        self.run_doctor(env)
        forbidden = ('open', 'stop', 'npm')
        self.assertFalse([c for c, _ in env.calls if c[0] in forbidden or (len(c) > 1 and c[1] in ('stop', 'serve'))])
        self.assertTrue(all(t <= 10 for _, t in env.calls))


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.root = self.home / 'checkout'
        self.path = self.home / '.claude.json'
        self.original = json.dumps({'mcpServers': {'cua-task': {'type': 'stdio', 'command': 'py', 'args': ['/old/facade/server.py'], 'env': {}}}, 'other': 1})
        self.path.write_text(self.original)

    def env(self):
        calls = []

        def run(argv, timeout):
            calls.append(list(argv))
            return 0, '', ''
        env = Env(run=run, environ={}, which=lambda n: '/bin/' + n, home=self.home, root=self.root, system='darwin')
        env.calls = calls
        return env

    def run_bootstrap(self, *flags):
        out = io.StringIO()
        env = self.env()
        code = cli.main(['bootstrap', *flags], env=env, out=out)
        return code, out.getvalue(), env

    def backups(self):
        return list(self.home.glob('.claude.json.bak-*'))

    def test_refuses_to_edit_claude_json_without_yes(self):
        code, text, _ = self.run_bootstrap()
        self.assertEqual(code, 0)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertEqual(self.backups(), [])
        self.assertIn('not editing without --yes', text)

    def test_yes_migrates_each_old_key_never_leaving_both(self):
        for old in ('computer-use', 'cua-task'):
            self.path.write_text(json.dumps({'mcpServers': {old: {'type': 'stdio', 'command': 'py', 'args': ['/old/server.py'], 'env': {}}}}))
            self.run_bootstrap('--yes')
            self.assertEqual(list(json.loads(self.path.read_text())['mcpServers']), ['computer-use-oh'], old)
        self.path.write_text(json.dumps({'mcpServers': {'computer-use': {'command': 'a', 'args': []}, 'cua-task': {'command': 'b', 'args': []}}}))
        self.run_bootstrap('--yes')
        self.assertEqual(list(json.loads(self.path.read_text())['mcpServers']), ['computer-use-oh'])

    def test_yes_backs_up_then_renames_and_repoints(self):
        _, text, _ = self.run_bootstrap('--yes')
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), self.original)
        data = json.loads(self.path.read_text())
        self.assertNotIn('cua-task', data['mcpServers'])
        self.assertEqual(data['mcpServers']['computer-use-oh']['args'], [str(self.root / 'computer_use/server.py')])
        self.assertEqual(data['mcpServers']['computer-use-oh']['command'], 'py')
        self.assertEqual(list(data['mcpServers']), ['computer-use-oh'])
        self.assertEqual(data['other'], 1)
        self.assertIn('updated ~/.claude.json', text)

    def test_second_run_is_a_no_op(self):
        self.run_bootstrap('--yes')
        self.run_bootstrap('--yes')
        self.assertEqual(len(self.backups()), 1)

    def test_steps_and_manual_instructions(self):
        _, text, env = self.run_bootstrap()
        joined = [' '.join(c) for c in env.calls]
        self.assertTrue(any('build_space_mover.sh' in c for c in joined))
        self.assertTrue(any(c.startswith('npm cache add @mobilenext/mobile-mcp@1.0.6') for c in joined))
        self.assertTrue(any('install_perception.py' in c for c in joined))
        stop = next(i for i, c in enumerate(joined) if c.endswith('cua-driver stop'))
        start = joined.index('open -n -g -a CuaDriver --args serve --grant existing-profile')
        self.assertLess(stop, start)
        self.assertIn('Privacy & Security > Accessibility', text)
        self.assertIn('Full Disk Access', text)
        self.assertIn('Assign To', text)
        self.assertIn('agent browser: not present in this checkout', text)

    def test_missing_claude_json_is_left_alone(self):
        self.path.unlink()
        code, text, _ = self.run_bootstrap('--yes')
        self.assertFalse(self.path.exists())
        self.assertEqual(code, 0)


if __name__ == '__main__':
    unittest.main()
