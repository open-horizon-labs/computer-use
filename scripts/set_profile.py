#!/usr/bin/env python3
"""Select a CUA provider profile without losing existing provider settings."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       'inference/cua-decider/capability-dispatch'))
from runtime_config import PROFILES, SETTING_KEYS, legacy_profile


def switch(path, profile):
    if path.exists():
        data = json.loads(path.read_text())
    else:
        data = {}
    if not isinstance(data, dict):
        raise ValueError('runtime config must be a JSON object')
    profiles = data.get('profiles', {})
    if not isinstance(profiles, dict) or set(profiles) - set(PROFILES):
        raise ValueError('runtime config contains invalid named profiles')

    # Move a legacy flat configuration under its current profile before
    # changing the selector, preserving endpoints, commands and credentials.
    legacy = {key: data.pop(key) for key in list(data) if key in SETTING_KEYS}
    if legacy:
        prior = data.get('profile')
        if prior not in PROFILES:
            prior = legacy_profile(legacy)
        existing = profiles.setdefault(prior, {})
        if not isinstance(existing, dict):
            raise ValueError('named profile settings must be an object')
        existing.update(legacy)
    data['profiles'] = profiles
    data['profile'] = profile

    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix='.runtime-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2)
            stream.write('\n')
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {name: len(settings) for name, settings in profiles.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=sorted(PROFILES))
    args = parser.parse_args()
    path = Path(os.environ.get('CUA_RUNTIME_CONFIG',
                               str(Path.home() / '.config/computer-use/runtime.json')))
    counts = switch(path, args.profile)
    print('Selected ' + args.profile + ' in ' + str(path))
    print('Preserved settings per profile: ' + json.dumps(counts, sort_keys=True))
    print('Start a fresh Codex session to load the selected provider profile.')


if __name__ == '__main__':
    main()
