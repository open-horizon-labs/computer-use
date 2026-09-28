"""Load the operator's persistent local CUA configuration without shell setup."""
import json
import os
from pathlib import Path

KEYS = {'CUA_GENERIC_PROVIDER', 'CUA_PAGE_EXTRACTION', 'CUA_EXTRACT_URL',
        'CUA_JULIA_COMMAND', 'CUA_SPAN_COMMAND', 'CUA_VISUAL_COMMAND',
        'CUA_SYSTEMONE_URL', 'CUA_EXTRACT_COMMAND', 'CUA_SELECTOR_COMMAND'}


def load_runtime_config():
    path = Path(os.environ.get('CUA_RUNTIME_CONFIG',
                str(Path.home() / '.config/computer-use/runtime.json')))
    if not path.exists():
        return {}
    values = json.loads(path.read_text())
    if not isinstance(values, dict) or set(values) - KEYS:
        raise ValueError('Unsupported local CUA configuration key')
    for key, value in values.items():
        if not isinstance(value, str):
            raise ValueError('Local CUA configuration values must be strings')
        os.environ.setdefault(key, value)
    return values
