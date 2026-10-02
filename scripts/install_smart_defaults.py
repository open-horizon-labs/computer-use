"""Install skill-first defaults for local Claude/Codex; --check is read-only."""
import argparse
import json
import re
import shutil
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARGS = ['mcp', '--embedded', '--permissions', 'spaces:list_spaces,spaces:list_tools,spaces:call_tool']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    home = Path.home()
    cua = shutil.which('cua') or str(home / '.local/bin/cua')
    if not Path(cua).is_file():
        raise SystemExit('Install Cua CLI first; no client configuration changed.')
    claude = home / '.claude.json'
    codex = home / '.codex/config.toml'
    cd = json.loads(claude.read_text()) if claude.exists() else {}
    ct = codex.read_text() if codex.exists() else ''
    td = tomllib.loads(ct)
    legacy_args = [str(ROOT / 'computer_use/server.py')]
    legacy_command = str(ROOT / '.venv-facade/bin/python')
    legacy = cd.get('mcpServers', {}).get('computer-use-oh')
    if legacy and (legacy.get('args') != legacy_args or legacy.get('command') != legacy_command):
        raise SystemExit('Claude computer-use-oh points elsewhere; refusing to alter that registration.')
    servers = td.get('mcp_servers', {})
    for label, entry in [('Claude', cd.get('mcpServers', {}).get('cua-spaces')), ('Codex', servers.get('cua-spaces'))]:
        if entry and (entry.get('command') != cua or entry.get('args') != ARGS):
            raise SystemExit(f'{label} cua-spaces differs; refusing to replace unrelated configuration.')
    old = servers.get('computer-use-oh')
    if old and (old.get('args') != legacy_args or old.get('command') != legacy_command):
        raise SystemExit('Codex computer-use-oh points elsewhere; refusing to alter that registration.')
    source = ROOT / 'skills/computer-use'
    destinations = [home / '.claude/skills/computer-use', home / '.agents/skills/computer-use', home / '.codex/skills/computer-use']
    if not args.check:
        mcp = cd.setdefault('mcpServers', {})
        mcp.pop('computer-use-oh', None)
        spaces = mcp.setdefault('cua-spaces', {})
        spaces.update({'type': 'stdio', 'command': cua, 'args': ARGS})
        spaces.setdefault('env', {}).update({'CUA_CACHE_AUTO_GC': '0', 'CUA_TELEMETRY': '0'})
        if old:
            pattern = r'(\[mcp_servers\.computer-use-oh\]\n)(.*?)(?=\n\[|\Z)'
            def disabled(match):
                body = match[2]
                if re.search(r'^enabled\s*=', body, re.M):
                    body = re.sub(r'^enabled\s*=.*$', 'enabled = false', body, flags=re.M)
                else:
                    body += '\nenabled = false\n'
                return match[1] + body
            ct, count = re.subn(pattern, disabled, ct, flags=re.S)
            if count != 1:
                raise SystemExit('Cannot identify exact Codex OH table; no config written.')
        if 'cua-spaces' not in servers:
            ct += '\n[mcp_servers.cua-spaces]\ncommand = ' + json.dumps(cua) + '\nargs = ' + json.dumps(ARGS) + '\nenabled = true\n\n[mcp_servers.cua-spaces.env]\nCUA_CACHE_AUTO_GC = "0"\nCUA_TELEMETRY = "0"\n'
        if servers.get('cua-spaces', {}).get('enabled') is False:
            pattern = r'(\[mcp_servers\.cua-spaces\]\n)(.*?)(?=\n\[|\Z)'
            ct, count = re.subn(pattern, lambda match: match[1] + re.sub(r'^enabled\s*=.*$', 'enabled = true', match[2], flags=re.M), ct, flags=re.S)
            if count != 1:
                raise SystemExit('Cannot identify exact Codex Spaces table; no installation written.')
        tomllib.loads(ct)
        for dest in destinations:
            shutil.copytree(source, dest, dirs_exist_ok=True)
        claude.parent.mkdir(parents=True, exist_ok=True)
        codex.parent.mkdir(parents=True, exist_ok=True)
        claude.write_text(json.dumps(cd, indent=2) + '\n')
        codex.write_text(ct)
    cd = json.loads(claude.read_text())
    td = tomllib.loads(codex.read_text())
    assert 'computer-use-oh' not in cd.get('mcpServers', {})
    assert td.get('mcp_servers', {}).get('computer-use-oh', {}).get('enabled', False) is False
    for entry in [cd['mcpServers']['cua-spaces'], td['mcp_servers']['cua-spaces']]:
        assert entry['args'] == ARGS and entry['command'] == cua
        assert entry.get('enabled', True) is True
    for dest in destinations:
        for original in source.rglob('*'):
            if original.is_file():
                assert (dest / original.relative_to(source)).read_bytes() == original.read_bytes()
    print('PASS: skill copies match; slim Spaces registered in both clients; OH adapter not loaded by default. Reconnect clients.')


if __name__ == '__main__':
    main()
