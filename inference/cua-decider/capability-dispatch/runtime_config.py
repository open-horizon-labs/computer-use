"""Load the operator's persistent local CUA configuration without shell setup."""
import json
import os
from pathlib import Path

SETTING_KEYS = {'CUA_GENERIC_PROVIDER', 'CUA_PAGE_EXTRACTION', 'CUA_EXTRACT_URL',
        'CUA_JULIA_COMMAND', 'CUA_SPAN_COMMAND', 'CUA_VISUAL_COMMAND',
        'CUA_SYSTEMONE_URL', 'CUA_EXTRACT_COMMAND', 'CUA_SELECTOR_COMMAND'}
KEYS = {'profile', 'profiles'} | SETTING_KEYS

PROFILES = {
    'fleet': {  # the default (DEFAULT_PROFILE): Jev chooser, NuExtract3 page reading, hosted services as configured
        'CUA_GENERIC_PROVIDER': 'jev',
        'CUA_PAGE_EXTRACTION': '1',
    },
    'local-mac': {  # explicit opt-in: Julia-1 chooser, refuses every hosted route
        'CUA_GENERIC_PROVIDER': 'julia-1',
        'CUA_PAGE_EXTRACTION': '1',
    },
}


DEFAULT_PROFILE = 'fleet'  # user decision 2026-09-30: "Jev is the default". A clean install sends page content to the configured hosted services.


def legacy_profile(values):
    """The profile a configuration with no `profile` key belongs to. Explicit Jev or hosted settings mean fleet. Explicit Julia settings and no hosted
    settings stay local-mac: an operator who configured Julia-1 is never moved to a hosted profile by the default changing. Nothing either way (no
    runtime.json, or only neutral settings) is a clean install: DEFAULT_PROFILE."""
    hosted = any(values.get(key) for key in ('CUA_SELECTOR_COMMAND', 'CUA_EXTRACT_URL', 'CUA_SYSTEMONE_URL'))
    if values.get('CUA_GENERIC_PROVIDER') == 'jev' or hosted:
        return 'fleet'
    if str(values.get('CUA_GENERIC_PROVIDER') or '').lower() in ('julia', 'julia-1') or values.get('CUA_JULIA_COMMAND'):
        return 'local-mac'
    return DEFAULT_PROFILE


def load_runtime_config():
    path = Path(os.environ.get('CUA_RUNTIME_CONFIG',
                str(Path.home() / '.config/computer-use/runtime.json')))
    values = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(values, dict) or set(values) - KEYS:
        raise ValueError('Unsupported local CUA configuration key')
    profiles = values.get('profiles', {})
    if not isinstance(profiles, dict) or set(profiles) - set(PROFILES):
        raise ValueError('profiles must contain only local-mac and fleet settings')
    for name, settings in profiles.items():
        if not isinstance(settings, dict) or set(settings) - SETTING_KEYS:
            raise ValueError('Unsupported provider setting in profile ' + name)
        if any(not isinstance(value, str) for value in settings.values()):
            raise ValueError('Provider profile values must be strings')
    # A clean install (no runtime.json) resolves to the fleet profile (Jev chooser,
    # hosted services). An existing operator's explicit Jev or Julia settings keep
    # their profile (see legacy_profile); local-mac is selected explicitly.
    default_profile = legacy_profile(values)
    profile = os.environ.get('CUA_PROFILE', values.get('profile', default_profile))
    if profile not in PROFILES:
        raise ValueError('CUA_PROFILE must be local-mac or fleet')
    # Profile values are defaults; explicit runtime-file settings and process
    # environment always win. In particular, local-mac never inherits a hosted
    # provider from the fleet profile.
    # Legacy flat settings remain active until the profile switcher migrates
    # them into a named profile. New configurations keep overrides isolated.
    legacy = {k: v for k, v in values.items() if k in SETTING_KEYS}
    settings = {**PROFILES[profile], **legacy, **profiles.get(profile, {})}
    for key, value in settings.items():
        if not isinstance(value, str):
            raise ValueError('Local CUA configuration values must be strings')
        os.environ.setdefault(key, value)
    if profile == 'local-mac':
        if os.environ.get('CUA_GENERIC_PROVIDER') != 'julia-1':
            raise ValueError('local-mac profile requires Julia-1; hosted chooser override refused')
        if any(os.environ.get(key) for key in ('CUA_SELECTOR_COMMAND', 'CUA_EXTRACT_URL', 'CUA_SYSTEMONE_URL')):
            raise ValueError('local-mac profile refuses hosted selector, extraction, or visual endpoints')
    os.environ.setdefault('CUA_PROFILE', profile)
    return {'profile': profile, **settings}
