#!/usr/bin/env python3
"""Install the pinned Cua Perception extension via cua-driver's signed catalog
lifecycle (see docs/FACADE.md and the upstream perception-extension.md doc).

This is the DEFAULT step of scripts/setup_facade.sh; run it directly to
install/verify perception on its own, or with --check to report without
mutating anything. The facade itself NEVER installs or updates the extension;
tools that need it point here when it is missing (Facade.regions Gap).

Pure, network-free logic (target selection, SHA256SUMS parsing/verification,
the idempotence decision, pin validation) is exercised by
scripts/test_install_perception.py with fakes -- no network in tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

PIN = 'cua-perception-v0.2.1'
PIN_PATTERN = re.compile(r'^cua-perception-v\d+\.\d+\.\d+$')
REPO = 'trycua/cua'
DEFAULT_DRIVER = str(Path.home() / '.local/bin/cua-driver')
INSTALL_ROOT = Path.home() / '.local/share/cua-perception'

# Target table from the upstream perception-extension.md release layout.
TARGETS = {
    ('Darwin', 'arm64'): 'aarch64-apple-darwin',
    ('Linux', 'x86_64'): 'x86_64-unknown-linux-gnu',
    ('Windows', 'AMD64'): 'x86_64-pc-windows-msvc',
    ('Windows', 'x86_64'): 'x86_64-pc-windows-msvc',
}

AGPL_NOTICE = """\
Cua Perception bundles the OmniParser icon detector and its Ultralytics
components, licensed AGPL-3.0-only; the PP-OCR text detector/recognizer are
Apache-2.0. Installing or redistributing this extension, including over a
network service, carries AGPL-3.0-only source-availability obligations for the
OmniParser/Ultralytics parts. Read the perception third-party notices before
proceeding. See docs/FACADE.md for this repository's summary.
"""


class InstallError(RuntimeError):
    pass


def validate_pin(pin: str) -> str:
    if not PIN_PATTERN.match(pin):
        raise InstallError(f'--version must match cua-perception-v<major>.<minor>.<patch>, got {pin!r}')
    return pin


def select_target(system: str | None = None, machine: str | None = None) -> str:
    """Map the running platform to the upstream release target triple."""
    system = system if system is not None else platform.system()
    machine = machine if machine is not None else platform.machine()
    target = TARGETS.get((system, machine))
    if target is None:
        raise InstallError(f'Unsupported platform for cua-perception: {system}/{machine}; '
                            'see upstream perception-extension.md for the supported target table')
    return target


def parse_sha256sums(text: str) -> dict:
    """Parse a SHA256SUMS file (`<hex digest>  <filename>` per line) into
    {filename: digest}. Tolerates the one- or two-space GNU coreutils format
    and blank/comment lines; rejects a malformed digest or line shape rather
    than silently skipping it, since a skipped entry would go unverified.
    """
    result = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.rstrip('\n')
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.match(r'^([0-9a-fA-F]{64})\s+[* ]?(.+)$', line)
        if not match:
            raise InstallError(f'SHA256SUMS line {lineno} is not a valid "<64-hex digest>  <file>" entry: {line!r}')
        digest, name = match.group(1).lower(), match.group(2).strip()
        result[name] = digest
    return result


def verify_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected.lower():
        raise InstallError(f'SHA-256 mismatch for {path.name}: expected {expected}, got {digest}')


def already_satisfied(status_payload: dict, pin: str) -> bool:
    """Idempotence decision from `extension status cua-perception --json`
    output: only an EXACT pin match that also reports healthy counts; a wrong
    version, an unhealthy report, or a not-installed extension all require
    installing/repairing, never a silent skip.
    """
    version = status_payload.get('active_version')
    pinned_version = pin[len('cua-perception-v'):]
    return bool(status_payload.get('installed')) and bool(status_payload.get('healthy')) and version == pinned_version


def run_driver(driver: str, args: list, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([driver, *args], capture_output=True, text=True, timeout=kwargs.pop('timeout', 60), **kwargs)


def driver_status(driver: str) -> dict:
    result = run_driver(driver, ['extension', 'status', 'cua-perception', '--json'])
    try:
        return json.loads(result.stdout) if result.stdout.strip() else {}
    except ValueError:
        return {}


def asset_url(pin: str, filename: str) -> str:
    return f'https://github.com/{REPO}/releases/download/{pin}/{filename}'


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which('gh'):
        result = subprocess.run(
            ['gh', 'release', 'download', url.rsplit('/', 2)[-2], '--repo', REPO,
             '--pattern', dest.name, '--dir', str(dest.parent), '--clobber'],
            capture_output=True, text=True)
        if result.returncode == 0 and dest.exists():
            return
    with urllib.request.urlopen(url) as response, open(dest, 'wb') as handle:
        shutil.copyfileobj(response, handle)


def install(pin: str, check: bool, driver: str) -> int:
    status = driver_status(driver)
    if already_satisfied(status, pin):
        print(f'cua-perception {pin} already installed and healthy; nothing to do.')
        return 0
    if check:
        print(f'cua-perception is NOT satisfied for {pin}: {json.dumps(status, indent=2)}')
        return 1

    print(AGPL_NOTICE)
    target = select_target()
    version = pin[len('cua-perception-v'):]
    base = f'cua-perception-{version}-{target}'
    directory = INSTALL_ROOT / version
    catalog_path = directory / f'{base}.catalog.json'
    archive_path = directory / f'{base}.tar.gz'
    sums_path = directory / 'SHA256SUMS'

    print(f'Downloading {pin} for target {target} into {directory} ...')
    download(asset_url(pin, catalog_path.name), catalog_path)
    download(asset_url(pin, archive_path.name), archive_path)
    download(asset_url(pin, sums_path.name), sums_path)

    sums = parse_sha256sums(sums_path.read_text())
    for path in (catalog_path, archive_path):
        expected = sums.get(path.name)
        if not expected:
            raise InstallError(f'SHA256SUMS has no entry for {path.name}; refusing to install an unverified artifact')
        verify_sha256(path, expected)
    print('SHA-256 verification passed for catalog and archive.')

    inspect = run_driver(driver, ['extension', 'inspect', 'cua-perception', '--catalog', str(catalog_path), '--json'])
    print(inspect.stdout or inspect.stderr)
    if inspect.returncode != 0:
        raise InstallError(f'extension inspect failed (exit {inspect.returncode}): {inspect.stderr}')

    installed = run_driver(driver, ['extension', 'install', 'cua-perception', '--catalog', str(catalog_path)], timeout=300)
    print(installed.stdout or installed.stderr)
    if installed.returncode != 0:
        raise InstallError(f'extension install failed (exit {installed.returncode}): {installed.stderr}')

    final = run_driver(driver, ['extension', 'status', 'cua-perception', '--self-test', '--json'], timeout=120)
    print(final.stdout or final.stderr)
    payload = json.loads(final.stdout) if final.stdout.strip() else {}
    if not already_satisfied(payload, pin):
        raise InstallError(f'Post-install self-test did not report {pin} healthy: {json.dumps(payload, indent=2)}')
    print(f'cua-perception {pin} installed and self-test healthy.')
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Report install status only; make no changes.')
    parser.add_argument('--version', default=PIN, help=f'Override the pinned release tag (default {PIN}).')
    parser.add_argument('--driver', default=os.environ.get('CUA_DRIVER', DEFAULT_DRIVER),
                        help='Path to the cua-driver executable.')
    args = parser.parse_args(argv)
    try:
        pin = validate_pin(args.version)
        return install(pin, args.check, args.driver)
    except InstallError as error:
        print(f'error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
