"""computer-use doctor and bootstrap (issue #63).

    python -m computer_use doctor [--json] [--probe]
    python -m computer_use bootstrap [--yes]

doctor is read-only: every check is a small function `check_x(env) -> {name, status, detail, fix}` with status ok | warn | blocker | skipped, driven by
an `Env` whose command runner, filesystem, environment and HTTP probe are injectable, so tests use fakes (no network, no desktop). Every external call is
bounded by a timeout and a missing or hung tool is a result, never a crash or a hang. doctor never launches a GUI app and sends nothing except one HEAD/GET to
a configured provider endpoint. `--probe` additionally builds space-mover if missing and runs `display serve` briefly.

bootstrap does what can be done from a shell and prints the rest (System Settings paths). It edits ~/.claude.json only with --yes, after a backup.
"""
import argparse
import json
import os
import re
import select
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / 'computer_use' / 'server.py'
OK, WARN, BLOCKER, SKIPPED = 'ok', 'warn', 'blocker', 'skipped'
CMD_TIMEOUT = 10
HTTP_TIMEOUT = 5
MOBILE_PACKAGE = '@mobilenext/mobile-mcp@1.0.6'
NOT_PRESENT = 'not present in this checkout'

SYSTEM_SETTINGS = {
    'accessibility': 'System Settings > Privacy & Security > Accessibility: enable CuaDriver (and space-mover if you use the agent display)',
    'screen': 'System Settings > Privacy & Security > Screen & System Audio Recording: enable CuaDriver',
    'fda': 'System Settings > Privacy & Security > Full Disk Access: enable CuaDriver (only for `profile: user`, the browser profile with Chrome 154 or newer)',
    'dock': 'System Settings > Desktop & Dock > Windows > Assign To (or right-click the app in the Dock > Options > Assign To) for apps the agent owns',
}


def result(name, status, detail, fix=''):
    return {'name': name, 'status': status, 'detail': detail, 'fix': fix}


class Env:
    """The outside world, injectable. run() never raises: it returns (returncode or None, stdout, stderr); None means not found, timed out or failed to start."""

    def __init__(self, run=None, exists=None, read_text=None, environ=None, http=None, which=None, home=None, root=None, popen=None, system=None):
        self._run = run or self._real_run
        self.exists = exists or (lambda p: Path(p).exists())
        self.read_text = read_text or (lambda p: Path(p).read_text())
        self.environ = os.environ if environ is None else environ
        self.http = http or self._real_http
        self.which = which or shutil.which
        self.home = Path(home) if home else Path.home()
        self.root = Path(root) if root else ROOT
        self.popen = popen or subprocess.Popen
        self.system = system or sys.platform

    @staticmethod
    def _real_run(argv, timeout=CMD_TIMEOUT):
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
            return done.returncode, done.stdout, done.stderr
        except (OSError, subprocess.SubprocessError):
            return None, '', ''

    def run(self, argv, timeout=CMD_TIMEOUT):
        try:
            return self._run(list(argv), timeout)
        except Exception:
            return None, '', ''

    @staticmethod
    def _real_http(url, timeout=HTTP_TIMEOUT):
        """(status or None, error text). HEAD, then GET when the server refuses HEAD. No body, no credentials."""
        error = ''
        for method in ('HEAD', 'GET'):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=timeout) as response:
                    return response.status, ''
            except urllib.error.HTTPError as e:
                if method == 'HEAD' and e.code in (405, 501):
                    continue
                return e.code, ''  # the server answered: reachable
            except Exception as e:
                error = type(e).__name__
                break
        return None, error

    @property
    def driver(self):
        return self.environ.get('CUA_DRIVER') or str(self.home / '.local/bin/cua-driver')

    @property
    def runtime_path(self):
        return Path(self.environ.get('CUA_RUNTIME_CONFIG') or self.home / '.config/computer-use/runtime.json')

    @property
    def claude_json(self):
        return self.home / '.claude.json'

    @property
    def space_mover(self):
        return Path(self.environ.get('CUA_SPACE_MOVER') or self.root / 'computer_use/spaces/bin/space-mover')


def load_json(env, path):
    """(data, error) for a JSON file; data is None when missing or malformed."""
    if not env.exists(path):
        return None, 'missing'
    try:
        return json.loads(env.read_text(path)), ''
    except (OSError, ValueError) as e:
        return None, 'unreadable (%s)' % type(e).__name__


def runtime_settings(env):
    data, err = load_json(env, env.runtime_path)
    if data is None:
        return {'profile': env.environ.get('CUA_PROFILE') or 'fleet'}, err
    if not isinstance(data, dict):
        return {}, 'not an object'
    profile = env.environ.get('CUA_PROFILE') or data.get('profile')
    if not profile:
        hosted = any(data.get(k) for k in ('CUA_SELECTOR_COMMAND', 'CUA_EXTRACT_URL', 'CUA_SYSTEMONE_URL')) or data.get('CUA_GENERIC_PROVIDER') == 'jev'
        julia = str(data.get('CUA_GENERIC_PROVIDER') or '').lower() in ('julia', 'julia-1') or data.get('CUA_JULIA_COMMAND')
        profile = 'local-mac' if julia and not hosted else 'fleet'
    flat = {k: v for k, v in data.items() if k.startswith('CUA_')}
    profiles = data.get('profiles') if isinstance(data.get('profiles'), dict) else {}
    flat.update(profiles.get(profile) or {})
    return {'profile': profile, **flat}, ''


# ---- Cua Driver -------------------------------------------------------------------------------------------------------------------------------

def status_text(env):
    rc, out, err = env.run([env.driver, 'status'])
    return rc, out + err


def check_driver_installed(env):
    rc, out, err = env.run([env.driver, '--version'])
    text = (out + err).strip()
    match = re.search(r'(\d+\.\d+\.\d+)', text)
    if rc is None or not match:
        return result('driver.installed', BLOCKER, 'cua-driver not found or did not answer at %s' % env.driver,
                      'install Cua Driver (https://github.com/trycua/cua), or set CUA_DRIVER to its path')
    return result('driver.installed', OK, 'cua-driver %s at %s' % (match.group(1), env.driver))


def check_driver_daemon(env):
    rc, text = status_text(env)
    if rc is None:
        return result('driver.daemon', BLOCKER, 'cua-driver status did not answer', 'install Cua Driver first')
    if 'is running' not in text:
        return result('driver.daemon', BLOCKER, 'the Driver daemon is not running',
                      'python -m computer_use bootstrap (starts it with --grant existing-profile)')
    sock = re.search(r'socket:\s*(\S+)', text)
    if sock and not env.exists(sock.group(1)):
        return result('driver.daemon', WARN, 'daemon reports a socket that does not exist: %s' % sock.group(1), 'python -m computer_use bootstrap (restarts the daemon)')
    return result('driver.daemon', OK, 'daemon running' + (', socket %s' % sock.group(1) if sock else ''))


def check_driver_grant(env):
    rc, text = status_text(env)
    pid = re.search(r'pid:\s*(\d+)', text)
    if rc is None or 'is running' not in text or not pid:
        return result('driver.grant', SKIPPED, 'daemon not running; nothing to inspect')
    prc, out, _ = env.run(['ps', '-p', pid.group(1), '-o', 'command='])
    if prc is None or not out.strip():
        return result('driver.grant', WARN, 'could not read the daemon command line', 'restart the daemon: python -m computer_use bootstrap')
    if re.search(r'--grant[ =]existing-profile', out):
        return result('driver.grant', OK, 'daemon started with --grant existing-profile')
    return result('driver.grant', BLOCKER, 'the daemon was not started with --grant existing-profile (goto, open_tab and read_pages on the user\'s browser profile are refused)',
                  'python -m computer_use bootstrap (cua-driver stop, then open -n -g -a CuaDriver --args serve --grant existing-profile)')


def check_driver_permissions(env):
    rc, out, _ = env.run([env.driver, 'permissions', 'status', '--json'])
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    if rc is None or not isinstance(data, dict):
        return result('driver.permissions', SKIPPED, 'permissions status unavailable (is the daemon running?)')
    wanted = (('accessibility', 'Accessibility', 'accessibility'), ('screen_recording', 'Screen Recording', 'screen'))
    missing = [(label, fix) for key, label, fix in wanted if data.get(key) is not True]
    if not missing:
        return result('driver.permissions', OK, 'Accessibility and Screen Recording granted to CuaDriver')
    return result('driver.permissions', BLOCKER, 'not granted to CuaDriver: ' + ', '.join(label for label, _ in missing), '; '.join(SYSTEM_SETTINGS[fix] for _, fix in missing))


def check_driver_signing(env):
    app = '/Applications/CuaDriver.app'
    if not env.exists(app):
        return result('driver.signing', SKIPPED, '%s not found (a local build has no app bundle here)' % app)
    rc, out, err = env.run(['codesign', '-dv', '--verbose=2', app])
    text = out + err
    if rc is None:
        return result('driver.signing', SKIPPED, 'codesign unavailable')
    if 'Signature=adhoc' in text or 'Authority=' not in text:
        return result('driver.signing', WARN, 'CuaDriver.app is ad-hoc signed (a local build): macOS may ask for its grants again after each rebuild',
                      'install the signed release if grants keep resetting')
    return result('driver.signing', OK, 'CuaDriver.app is signed by a developer identity')


def check_full_disk_access(env):
    """Full Disk Access belongs to CuaDriver's own identity and cannot be read from another process without triggering a prompt."""
    return result('driver.full_disk_access', WARN,
                  'cannot be verified read-only; only `profile: user` (the user\'s own Chrome profile, TCC-protected since Chrome 154) needs it',
                  SYSTEM_SETTINGS['fda'])


def check_perception(env):
    rc, out, _ = env.run([env.driver, 'extension', 'status', 'cua-perception', '--json'])
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    if rc is None or not isinstance(data, dict):
        return result('perception', WARN, 'Cua Perception status unavailable', 'python scripts/install_perception.py')
    if not data.get('installed'):
        return result('perception', WARN, 'Cua Perception is not installed (canvas pages degrade to a Gap naming the installer)', 'python scripts/install_perception.py')
    if not data.get('healthy'):
        return result('perception', BLOCKER, 'Cua Perception %s is installed but unhealthy' % data.get('active_version'), 'python scripts/install_perception.py')
    return result('perception', OK, 'Cua Perception %s healthy' % data.get('active_version'))


# ---- Node, devices ------------------------------------------------------------------------------------------------------------------------------

def check_node(env):
    rc, out, _ = env.run(['node', '--version'])
    m = re.match(r'v(\d+)', out.strip())
    if rc is None or not m:
        return result('node', WARN, 'Node.js not found: Android/iOS device targets and Chrome for Testing need it (Mac windows do not)', 'install Node.js 18 or newer (https://nodejs.org)')
    if int(m.group(1)) < 18:
        return result('node', WARN, 'Node.js %s is older than 18' % out.strip(), 'upgrade Node.js to 18 or newer')
    if not env.which('npx'):
        return result('node', WARN, 'node %s found but npx is not on PATH' % out.strip(), 'install npm/npx with Node.js')
    return result('node', OK, 'node %s, npx present' % out.strip())


def check_adb(env):
    rc, out, _ = env.run(['adb', 'devices'])
    if rc is None:
        return result('adb', SKIPPED, 'adb not installed (only needed for Android devices)', 'install Android platform-tools to use Android targets')
    devices = [l.split()[0] for l in out.splitlines()[1:] if l.strip().endswith('device')]
    if not devices:
        return result('adb', WARN, 'adb present, no device or emulator attached', 'start an emulator or attach a device with USB debugging')
    return result('adb', OK, 'adb devices: ' + ', '.join(devices))


def check_simctl(env):
    rc, out, _ = env.run(['xcrun', 'simctl', 'list', 'devices', 'booted'])
    if rc is None or rc != 0:
        return result('simctl', SKIPPED, 'xcrun simctl not available (only needed for iOS simulators)', 'install Xcode command line tools')
    booted = [l.strip() for l in out.splitlines() if '(Booted)' in l]
    if not booted:
        return result('simctl', WARN, 'simctl present, no booted simulator', 'boot a simulator (Simulator app, or xcrun simctl boot <udid>)')
    return result('simctl', OK, '%d booted simulator(s): %s' % (len(booted), booted[0].split(' (')[0]))


# ---- space-mover --------------------------------------------------------------------------------------------------------------------------------

def check_space_mover(env):
    binary = env.space_mover
    if not env.exists(binary):
        return result('space_mover.built', WARN, 'space-mover is not built (only needed for the agent display)', 'python -m computer_use bootstrap (runs scripts/build_space_mover.sh)')
    rc, out, _ = env.run([str(binary), 'trusted'])
    try:
        trusted = bool(json.loads(out.strip().splitlines()[-1]).get('trusted'))
    except (ValueError, IndexError, AttributeError):
        trusted = None
    if trusted is None:
        return result('space_mover.built', WARN, 'space-mover is built but did not answer `trusted`', 'rebuild: scripts/build_space_mover.sh')
    if not trusted:
        return result('space_mover.built', WARN, 'space-mover is built but not trusted for Accessibility', SYSTEM_SETTINGS['accessibility'])
    return result('space_mover.built', OK, 'space-mover built and trusted (%s)' % binary)


def check_space_mover_probe(env, timeout=10):
    """--probe: create a virtual display with `display serve` and drop it. Bounded; the child is always stopped."""
    binary = env.space_mover
    if not env.exists(binary):
        rc, _, _ = env.run(['/bin/sh', str(env.root / 'scripts/build_space_mover.sh')], timeout=180)
        if rc != 0 or not env.exists(binary):
            return result('space_mover.probe', WARN, 'space-mover is missing and could not be built', 'install Xcode command line tools, then scripts/build_space_mover.sh')
    try:
        proc = env.popen([str(binary), 'display', 'serve', '--width', '640', '--height', '480'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError as e:
        return result('space_mover.probe', WARN, 'display serve did not start (%s)' % type(e).__name__, 'rebuild: scripts/build_space_mover.sh')
    try:
        ready, _, _ = select.select([proc.stdout], [], [], timeout)
        line = proc.stdout.readline() if ready else ''
        try:
            info = json.loads(line)
        except ValueError:
            info = {}
        if info.get('created') and info.get('active'):
            return result('space_mover.probe', OK, 'created and dropped a virtual display (id %s)' % info.get('id'))
        return result('space_mover.probe', WARN, 'display serve did not create a display: %s' % (info.get('reason') or 'no answer in %ds' % timeout),
                      'needs macOS with the private CGVirtualDisplay classes and a logged-in session')
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.stdout.close()
        except Exception:
            pass


# ---- optional modules from sibling PRs ----------------------------------------------------------------------------------------------------------

def _optional(name):
    try:
        return __import__(name)
    except Exception:
        return None


ABSENT = object()  # pass module=ABSENT to mean 'the module is not present in this checkout' (tests); None means 'try to import it'


def check_agent_browser(env, module=None):
    path = env.environ.get('CUA_AGENT_BROWSER_PATH')
    mod = None if module is ABSENT else (module if module is not None else _optional('agent_browser'))
    if path:
        if env.exists(path):
            return result('agent_browser', OK, 'CUA_AGENT_BROWSER_PATH: %s' % path)
        return result('agent_browser', BLOCKER, 'CUA_AGENT_BROWSER_PATH points at a missing file: %s' % path, 'fix or unset CUA_AGENT_BROWSER_PATH')
    if mod is None:
        return result('agent_browser', SKIPPED, 'agent browser: %s' % NOT_PRESENT)
    for attr in ('find_installed', 'installed_path', 'find_browser', 'browser_path'):
        finder = getattr(mod, attr, None)
        if callable(finder):
            try:
                found = finder(getattr(mod, 'CACHE', Path.home() / '.cache' / 'computer-use') / 'browsers') if attr == 'find_installed' else finder()
            except Exception:
                found = None
            if found and env.exists(found):
                return result('agent_browser', OK, 'Chrome for Testing at %s' % found)
            break
    return result('agent_browser', WARN, 'no agent browser (Chrome for Testing) installed and CUA_AGENT_BROWSER_PATH unset', 'python -m computer_use bootstrap')


# ---- providers and config -----------------------------------------------------------------------------------------------------------------------

def check_runtime(env):
    data, err = load_json(env, env.runtime_path)
    if err == 'missing':
        return result('runtime.profile', OK, 'no runtime.json: a clean install resolves to the fleet profile (hosted routes unconfigured, nothing is sent)')
    if not isinstance(data, dict):
        return result('runtime.profile', BLOCKER, 'runtime.json is %s: %s' % (err or 'not an object', env.runtime_path), 'fix or remove it (see skills/computer-use/references/setup.md)')
    settings, _ = runtime_settings(env)
    return result('runtime.profile', OK, 'profile %s (%s)' % (settings['profile'], env.runtime_path))


def check_providers(env):
    """One bounded request to each configured hosted endpoint; the command-based selector is checked for its executable, never run."""
    settings, _ = runtime_settings(env)
    if settings.get('profile') == 'local-mac':
        return [result('provider', SKIPPED, 'profile local-mac uses no hosted endpoint')]
    out = []
    for key, label in (('CUA_EXTRACT_URL', 'NuExtract3 page extraction'), ('CUA_SYSTEMONE_URL', 'SystemOne screenshots')):
        url = env.environ.get(key) or settings.get(key)
        name = 'provider.' + key.lower()
        if not url:
            out.append(result(name, SKIPPED, '%s: %s not configured (that route is unavailable, nothing is sent)' % (label, key)))
            continue
        status, err = env.http(url, HTTP_TIMEOUT)
        if status is None:
            out.append(result(name, WARN, '%s: %s unreachable (%s)' % (label, key, err or 'no answer'), 'check the endpoint and network; see docs/PROVIDERS.md'))
        elif status >= 500:
            out.append(result(name, WARN, '%s: answered HTTP %d' % (label, status), 'the service is up but failing; try later'))
        else:
            out.append(result(name, OK, '%s: reachable (HTTP %d)' % (label, status)))
    raw = env.environ.get('CUA_SELECTOR_COMMAND') or settings.get('CUA_SELECTOR_COMMAND')
    try:
        argv = json.loads(raw) if raw else [str(env.home / '.local/share/fleet-cua-decider/select-fleet')]
    except ValueError:
        argv = None
    if not isinstance(argv, list) or not argv or not isinstance(argv[0], str):
        out.append(result('provider.selector', BLOCKER, 'CUA_SELECTOR_COMMAND is not a JSON argv array', 'set it to a JSON array, e.g. ["/path/select-fleet","--fast","jev"]'))
    elif env.exists(argv[0]) or env.which(argv[0]):
        out.append(result('provider.selector', OK, 'Jev selector command present: %s' % argv[0]))
    else:
        out.append(result('provider.selector', WARN, 'Jev selector command not found: %s' % argv[0], 'install the Fleet selector or set CUA_SELECTOR_COMMAND'))
    return out


def check_mcp_registration(env):
    data, err = load_json(env, env.claude_json)
    if data is None:
        return result('mcp.registration', WARN, '~/.claude.json %s; other clients (codex) are not inspected' % err, 'claude mcp add computer-use -- <venv python> %s' % SERVER)
    servers = data.get('mcpServers') if isinstance(data, dict) else None
    servers = servers if isinstance(servers, dict) else {}
    entry = servers.get('computer-use')
    if entry is None and 'cua-task' not in servers:
        return result('mcp.registration', WARN, 'no `computer-use` MCP server registered in ~/.claude.json', 'python -m computer_use bootstrap --yes (or: claude mcp add computer-use -- <venv python> %s)' % SERVER)
    problems = []
    if 'cua-task' in servers:
        problems.append('stale server key `cua-task` (renamed to `computer-use`)')
    if entry is not None:
        args = [str(a) for a in (entry.get('args') or [])]
        server_args = [a for a in args if a.endswith('server.py')]
        if not server_args or not server_args[0].endswith('computer_use/server.py'):
            problems.append('args do not point at computer_use/server.py (%s)' % (', '.join(args) or 'none'))
        elif not env.exists(server_args[0]):
            problems.append('args path does not exist: %s' % server_args[0])
    if problems:
        return result('mcp.registration', WARN, '; '.join(problems), 'python -m computer_use bootstrap --yes')
    return result('mcp.registration', OK, 'server computer-use -> %s' % server_args[0])


def check_skill(env):
    dirs = [env.home / '.claude/skills', env.home / '.agents/skills', env.home / '.codex/skills']
    current = [str(d) for d in dirs if env.exists(d / 'computer-use/SKILL.md')]
    stale = [str(d / 'cua-capability-dispatch') for d in dirs if env.exists(d / 'cua-capability-dispatch')]
    if current and not stale:
        return result('skill', OK, 'skill computer-use installed in ' + ', '.join(current))
    if stale:
        return result('skill', WARN, 'old skill name cua-capability-dispatch still installed: ' + ', '.join(stale),
                      'npx skills add open-horizon-labs/computer-use --skill computer-use, then remove the old copy')
    return result('skill', WARN, 'skill computer-use not installed', 'npx skills add open-horizon-labs/computer-use --skill computer-use')


def check_python(env):
    venv = env.root / '.venv-facade/bin/python'
    if not env.exists(venv):
        return result('python.venv', BLOCKER, '.venv-facade not found', 'scripts/setup_facade.sh')
    rc, _, _ = env.run([str(venv), '-c', 'import mcp'])
    if rc != 0:
        return result('python.venv', BLOCKER, '.venv-facade cannot import `mcp` (requirements missing)', 'scripts/setup_facade.sh')
    return result('python.venv', OK, '.venv-facade present, requirements import')


STATIC_CHECKS = (check_driver_installed, check_driver_daemon, check_driver_grant, check_driver_permissions, check_driver_signing, check_full_disk_access,
                 check_perception, check_node, check_adb, check_simctl, check_space_mover, check_agent_browser, check_runtime, check_providers,
                 check_mcp_registration, check_skill, check_python)


def run_checks(env, probe=False):
    results = []
    for check in STATIC_CHECKS:
        try:
            out = check(env)
        except Exception as e:  # a check bug must not hide the other results
            out = result(check.__name__.replace('check_', ''), WARN, 'check failed: %s' % type(e).__name__)
        results.extend(out if isinstance(out, list) else [out])
    if probe:
        results.append(check_space_mover_probe(env))
    return results


def exit_code(results):
    return 1 if any(r['status'] == BLOCKER for r in results) else 0


def render(results):
    tag = {OK: 'ok     ', WARN: 'warn   ', BLOCKER: 'BLOCKER', SKIPPED: 'skipped'}
    lines = []
    for r in results:
        lines.append('[%s] %s: %s' % (tag[r['status']], r['name'], r['detail']))
        if r['fix'] and r['status'] in (WARN, BLOCKER):
            lines.append('          fix: %s' % r['fix'])
    counts = {s: sum(1 for r in results if r['status'] == s) for s in (OK, WARN, BLOCKER, SKIPPED)}
    lines.append('%d ok, %d warn, %d blocker, %d skipped' % (counts[OK], counts[WARN], counts[BLOCKER], counts[SKIPPED]))
    return '\n'.join(lines)


def doctor(env, as_json=False, probe=False, out=None):
    out = out or sys.stdout
    results = run_checks(env, probe)
    code = exit_code(results)
    if as_json:
        out.write(json.dumps({'ok': code == 0, 'checks': results}, indent=2) + '\n')
    else:
        out.write(render(results) + '\n')
    return code


# ---- bootstrap ----------------------------------------------------------------------------------------------------------------------------------

def register_mcp(env, yes):
    """Rename a stale `cua-task` key and point args at this checkout's server. Only with yes; the backup is written first."""
    path = env.claude_json
    data, err = load_json(env, path)
    if not isinstance(data, dict):
        return result('bootstrap.mcp', SKIPPED, '~/.claude.json %s; nothing to edit' % (err or 'is not an object'), 'claude mcp add computer-use -- <venv python> %s' % (env.root / 'computer_use/server.py'))
    servers = data.setdefault('mcpServers', {})
    if not isinstance(servers, dict):
        return result('bootstrap.mcp', SKIPPED, 'mcpServers in ~/.claude.json is not an object; not touching it')
    server = str(env.root / 'computer_use/server.py')
    entry = servers.get('computer-use') or servers.get('cua-task')
    new = dict(entry) if isinstance(entry, dict) else {'type': 'stdio', 'command': str(env.root / '.venv-facade/bin/python'), 'env': {}}
    new['args'] = [server]
    if servers.get('computer-use') == new and 'cua-task' not in servers:
        return result('bootstrap.mcp', OK, 'MCP registration already current')
    if not yes:
        return result('bootstrap.mcp', SKIPPED, 'would edit ~/.claude.json (rename cua-task, set args to %s); not editing without --yes' % server, 'rerun: python -m computer_use bootstrap --yes')
    backup = path.with_name('.claude.json.bak-%s' % time.strftime('%Y%m%d-%H%M%S'))
    backup.write_text(env.read_text(path))
    servers.pop('cua-task', None)
    servers['computer-use'] = new
    path.write_text(json.dumps(data, indent=2) + '\n')
    return result('bootstrap.mcp', OK, 'updated ~/.claude.json (backup: %s)' % backup)


def restart_daemon(env):
    if env.system != 'darwin':
        return result('bootstrap.daemon', SKIPPED, 'not macOS')
    env.run([env.driver, 'stop'], timeout=15)
    rc, _, err = env.run(['open', '-n', '-g', '-a', 'CuaDriver', '--args', 'serve', '--grant', 'existing-profile'], timeout=15)
    if rc != 0:
        return result('bootstrap.daemon', WARN, 'could not start CuaDriver with the grant: %s' % (err.strip()[:120] or 'open failed'), 'open -n -g -a CuaDriver --args serve --grant existing-profile')
    return result('bootstrap.daemon', OK, 'daemon restarted with --grant existing-profile')


def bootstrap(env, yes=False, out=None):
    out = out or sys.stdout
    steps = []
    if env.exists(env.space_mover):
        steps.append(result('bootstrap.space_mover', OK, 'space-mover already built'))
    else:
        rc, _, err = env.run(['/bin/sh', str(env.root / 'scripts/build_space_mover.sh')], timeout=180)
        steps.append(result('bootstrap.space_mover', OK if rc == 0 else WARN, 'built space-mover' if rc == 0 else 'build failed: %s' % err.strip()[-120:], '' if rc == 0 else 'install Xcode command line tools'))
    if env.which('npm'):
        rc, _, _ = env.run(['npm', 'cache', 'add', MOBILE_PACKAGE], timeout=120)
        steps.append(result('bootstrap.mobile_mcp', OK if rc == 0 else WARN, 'prefetched %s' % MOBILE_PACKAGE if rc == 0 else 'could not prefetch (it is fetched on first device use)'))
    else:
        steps.append(result('bootstrap.mobile_mcp', SKIPPED, 'npm not found; install Node.js 18+ for device targets'))
    rc, _, err = env.run([sys.executable, str(env.root / 'scripts/install_perception.py')], timeout=400)
    steps.append(result('bootstrap.perception', OK if rc == 0 else WARN, 'Cua Perception installed and healthy' if rc == 0 else 'install_perception.py failed: %s' % err.strip()[-120:], '' if rc == 0 else 'python scripts/install_perception.py'))
    mod = _optional('agent_browser')
    installer = next((getattr(mod, n) for n in ('install', 'install_chrome_for_testing') if mod is not None and callable(getattr(mod, n, None))), None)
    if installer is None:
        steps.append(result('bootstrap.agent_browser', SKIPPED, 'agent browser: %s' % NOT_PRESENT))
    else:
        try:
            installer()
            steps.append(result('bootstrap.agent_browser', OK, 'Chrome for Testing installed'))
        except Exception as e:
            steps.append(result('bootstrap.agent_browser', WARN, 'Chrome for Testing install failed (%s)' % type(e).__name__))
    steps.append(register_mcp(env, yes))
    steps.append(restart_daemon(env))
    out.write(render(steps) + '\n\nManual steps (macOS cannot grant these from a shell):\n')
    for key in ('accessibility', 'screen', 'fda', 'dock'):
        out.write('  - %s\n' % SYSTEM_SETTINGS[key])
    out.write('\nThen run: python -m computer_use doctor\n')
    return 0


def main(argv=None, env=None, out=None):
    parser = argparse.ArgumentParser(prog='python -m computer_use', description='computer-use doctor and bootstrap')
    sub = parser.add_subparsers(dest='command', required=True)
    d = sub.add_parser('doctor', help='check every dependency and grant (read-only); exit 1 on a blocker')
    d.add_argument('--json', action='store_true')
    d.add_argument('--probe', action='store_true', help='also create and drop a virtual display (builds space-mover if missing)')
    b = sub.add_parser('bootstrap', help='do the fixable setup and print the manual steps')
    b.add_argument('--yes', action='store_true', help='allow editing ~/.claude.json (a backup is kept)')
    args = parser.parse_args(argv)
    env = env or Env()
    if args.command == 'doctor':
        return doctor(env, args.json, args.probe, out)
    return bootstrap(env, args.yes, out)


if __name__ == '__main__':
    sys.exit(main())
