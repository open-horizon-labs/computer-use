#!/usr/bin/env python3
"""Opt-in, checksum-pinned terminal-use 1.4.1 installer; no services started."""
import hashlib
import os
from pathlib import Path
import platform
import tempfile
import urllib.request

VERSION = '1.4.1'
ROOT = Path.home() / '.local/share/computer-use/terminal-use' / VERSION
# GitHub release asset digests, v1.4.1, checked 2026-10-02.
TARGETS = {
    ('Darwin', 'arm64'): ('macos_aarch64', '851b1f6f54fba5f82008279632d88b75d9ef27368dc6f1aa3261a82b1b17f75d'),
    ('Linux', 'x86_64'): ('linux_x86_64', '35ae4a705ef616f6573ed78f2971b0dd57135ace90d39b514857d216578360d3'),
    ('Linux', 'aarch64'): ('linux_aarch64', '65110adff64f2c6581c1ae8a2cbb9b72b6e86566303db818939a447a5542adfd'),
}


def install(root=ROOT, system=None, machine=None, fetch=None):
    target = TARGETS.get((system or platform.system(), machine or platform.machine()))
    if target is None:raise ValueError('No pinned terminal-use binary for this platform; see docs/TERMINALS.md')
    asset, digest = target
    destination = Path(root) / 'tu'
    if destination.is_file() and not destination.is_symlink() and hashlib.sha256(destination.read_bytes()).hexdigest() == digest:
        destination.chmod(0o755)
        return destination
    url = f'https://github.com/flipbit03/terminal-use/releases/download/v{VERSION}/tu_{asset}'
    if fetch is None:
        with urllib.request.urlopen(url, timeout=60) as response:data = response.read(32 * 1024 * 1024)
    else:data = fetch(url)
    if hashlib.sha256(data).hexdigest() != digest:raise ValueError('terminal-use checksum mismatch; installation unchanged')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        temporary.chmod(0o755)
        os.replace(temporary, destination)
    finally:temporary.unlink(missing_ok=True)
    return destination


if __name__ == '__main__':
    print(install())
