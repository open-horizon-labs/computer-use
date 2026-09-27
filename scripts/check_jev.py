"""One hosted Jev request; no Qwen, desktop actions or secret output."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'inference/cua-decider'))
from decision_providers import Jev


def main():
    provider = Jev()
    try:
        result = provider({'goal': 'Choose the action named Settings.',
                           'observation': 'Settings and Help are offered.'},
                          {'settings': 'Open Settings', 'help': 'Open Help'})
        print(json.dumps({k: result.get(k) for k in ('choice', 'confidence', 'model')}))
        return 0 if result.get('choice') == 'settings' else 1
    except Exception as exc:
        # Upstream exception messages may include request details; do not print them.
        print('Jev check failed: ' + type(exc).__name__ + '. Check credentials, endpoint, model and network.', file=sys.stderr)
        return 1
    finally:
        provider.close()


if __name__ == '__main__':
    raise SystemExit(main())
