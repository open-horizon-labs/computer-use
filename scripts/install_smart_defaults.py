"""Install the local skill; opt into slim Spaces with --with-spaces. Python 3.11+."""
import argparse
import json
import os
import re
import shutil
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARGS = ['mcp', '--embedded', '--permissions', 'spaces:list_spaces,spaces:list_tools,spaces:call_tool']


def inventory(root):
    """Compare the whole package, including extra files and empty directories."""
    if not root.is_dir():
        return None
    return {str(p.relative_to(root)): ('link', os.readlink(p)) if p.is_symlink()
            else ('file', p.read_bytes()) if p.is_file() else ('directory',)
            for p in root.rglob('*')}


def instruction_check(home, clients):
    paths = [home / '.agents/AGENTS.md']
    if 'codex' in clients:
        paths.append(home / '.codex/AGENTS.md')
    if 'claude' in clients:
        paths.extend([home / '.claude/CLAUDE.md', home / '.claude/AGENTS.md'])
    for path in paths:
        if path.is_file() and 'cua-capability-dispatch/SKILL.md' in path.read_text():
            raise SystemExit(f'Obsolete skill reference in {path}. Update it to '
                             '~/.agents/skills/computer-use/SKILL.md (Codex) or '
                             '~/.claude/skills/computer-use/SKILL.md (Claude), and remove '
                             'obsolete mandatory selector setup. No installation changed.')


def set_enabled(text, name, value):
    pattern = rf'(\[mcp_servers\.{re.escape(name)}\]\n)(.*?)(?=\n\[|\Z)'
    def update(match):
        body = match[2]
        if re.search(r'^enabled\s*=', body, re.M):
            body = re.sub(r'^enabled\s*=.*$', f'enabled = {value}', body, flags=re.M)
        else:
            body += f'\nenabled = {value}\n'
        return match[1] + body
    result, count = re.subn(pattern, update, text, flags=re.S)
    if count != 1:
        raise SystemExit(f'Cannot identify exact Codex {name} table; no installation changed.')
    return result


def own_adapter(entry):
    return entry.get('command') == str(ROOT / '.venv-facade/bin/python') and entry.get('args') == [str(ROOT / 'computer_use/server.py')]


def spaces_match(entry, cua):
    command = entry.get('command', '')
    resolved = shutil.which(command) if command and '/' not in command else command
    return bool(resolved) and Path(resolved).resolve() == Path(cua).resolve() and entry.get('args') == ARGS


def install_package(source, dest, home):
    if inventory(source) == inventory(dest):
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.computer-use-install-', dir=dest.parent) as temp:
        staged = Path(temp) / 'package'
        shutil.copytree(source, staged)
        backup = None
        if dest.exists():
            base = home / '.local/state/computer-use/install-backups'
            base.mkdir(parents=True, exist_ok=True)
            backup = Path(tempfile.mkdtemp(prefix='skill-', dir=base)) / 'computer-use'
            dest.rename(backup)
        try:
            staged.rename(dest)
        except OSError:
            if backup is not None:
                backup.rename(dest)
            raise
        if backup is not None:
            print(f'Previous skill package preserved at {backup}')


def write_config(path, text):
    if path.exists() and path.read_text() == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as temp:
        staged = Path(temp.name)
        try:
            temp.write(text)
            temp.flush()
            os.fchmod(temp.fileno(), path.stat().st_mode & 0o777 if path.exists() else 0o600)
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify without changing files; does not test live tools.')
    parser.add_argument('--client', choices=['claude', 'codex', 'both'], default='both')
    parser.add_argument('--with-spaces', action='store_true', help='Also register/verify the optional slim Spaces server; requires Cua CLI.')
    args = parser.parse_args()
    home = Path.home()
    clients = ['claude', 'codex'] if args.client == 'both' else [args.client]
    instruction_check(home, clients)
    cua = None
    if args.with_spaces:
        cua = shutil.which('cua') or str(home / '.local/bin/cua')
        if not Path(cua).is_file() or not os.access(cua, os.X_OK):
            raise SystemExit('Install executable Cua CLI first for --with-spaces; no installation changed.')
    source = ROOT / 'skills/computer-use'
    destinations = []
    if 'claude' in clients:
        destinations.append(home / '.claude/skills/computer-use')
    if 'codex' in clients:
        destinations.extend([home / '.agents/skills/computer-use', home / '.codex/skills/computer-use'])
    configs = []
    for client in clients:
        path = home / ('.claude.json' if client == 'claude' else '.codex/config.toml')
        text = path.read_text() if path.exists() else ''
        try:
            data = json.loads(text) if text and client == 'claude' else tomllib.loads(text) if client == 'codex' else {}
        except (ValueError, tomllib.TOMLDecodeError):
            raise SystemExit(f'Invalid client configuration at {path}; no installation changed.') from None
        servers = data.get('mcpServers' if client == 'claude' else 'mcp_servers', {})
        old = servers.get('computer-use-oh')
        if old and not own_adapter(old):
            raise SystemExit(f'{client} computer-use-oh points elsewhere; refusing to alter unrelated configuration.')
        spaces = servers.get('cua-spaces')
        if args.with_spaces and spaces and not spaces_match(spaces, cua):
            raise SystemExit(f'{client} cua-spaces differs; refusing to replace unrelated configuration.')
        if args.check:
            if old and (client == 'claude' or old.get('enabled', True)):
                raise SystemExit(f'{client} legacy OH adapter is active; run the installer to migrate it.')
            if args.with_spaces and (not spaces or not spaces.get('enabled', True)):
                raise SystemExit(f'{client} slim Spaces server is missing or disabled.')
            continue
        if client == 'claude':
            if old or args.with_spaces:
                servers = data.setdefault('mcpServers', {})
                servers.pop('computer-use-oh', None)
                if args.with_spaces:
                    spaces = servers.setdefault('cua-spaces', {})
                    spaces.update({'type': 'stdio', 'command': cua, 'args': ARGS})
                    spaces.pop('enabled', None)
                    spaces.setdefault('env', {}).update({'CUA_CACHE_AUTO_GC': '0', 'CUA_TELEMETRY': '0'})
                configs.append((path, json.dumps(data, indent=2) + '\n'))
        else:
            updated = set_enabled(text, 'computer-use-oh', 'false') if old else text
            if args.with_spaces:
                if spaces and spaces.get('enabled') is False:
                    updated = set_enabled(updated, 'cua-spaces', 'true')
                elif not spaces:
                    updated += '\n[mcp_servers.cua-spaces]\ncommand = ' + json.dumps(cua) + '\nargs = ' + json.dumps(ARGS) + '\nenabled = true\n\n[mcp_servers.cua-spaces.env]\nCUA_CACHE_AUTO_GC = "0"\nCUA_TELEMETRY = "0"\n'
            tomllib.loads(updated)
            if updated != text:
                configs.append((path, updated))
    for dest in destinations:
        if args.check:
            if inventory(dest) != inventory(source):
                raise SystemExit(f'Skill package differs or is missing at {dest}; run the installer to repair it.')
        elif inventory(dest) != inventory(source) and (dest.exists() or dest.is_symlink()):
            if dest.is_symlink():
                raise SystemExit(f'Skill symlink differs at {dest}; update its source or unlink it explicitly. No installation changed.')
            entry = dest / 'SKILL.md'
            if not entry.is_file() or not re.search(r'^name:\s*computer-use\s*$', entry.read_text(), re.M):
                raise SystemExit(f'Unrecognized skill directory at {dest}; refusing to replace it. No installation changed.')
    if not args.check:
        for dest in destinations:
            install_package(source, dest, home)
        for path, text in configs:
            write_config(path, text)
    detail = '; slim Spaces registered' if args.with_spaces else '; optional Spaces configuration unchanged'
    print(f'PASS: complete skill packages match for {args.client}; legacy OH adapter inactive{detail}. '
          'This verifies local files/configuration, not live tools or ChatGPT workspace installation.')


if __name__ == '__main__':
    main()
