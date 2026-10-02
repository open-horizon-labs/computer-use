"""Same fixtures/prompts as baseline, with only OH's server path replaced."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import runner


def with_runtime(command, runtime):
    key = 'mcp_servers.computer-use-oh.args='
    replacement = key + runner.toml([str(runtime / 'computer_use/server.py')])
    found = [i for i, arg in enumerate(command) if arg.startswith(key)]
    if len(found) != 1:
        raise ValueError('expected exactly one OH server argument')
    copied = list(command)
    copied[found[0]] = replacement
    return copied


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args, rest = parser.parse_known_args()
    runtime = args.runtime.resolve()
    if not (runtime / 'computer_use/server.py').is_file():
        raise SystemExit('runtime must contain computer_use/server.py')
    args.out.mkdir(parents=True, exist_ok=True)
    git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=runtime, text=True, capture_output=True, check=True)
    files = {str(p.relative_to(runtime)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (runtime / 'computer_use').glob('*.py')}
    provenance = {'runtime_commit': git.stdout.strip(), 'runtime_files_sha256': files,
                  'wrapper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'baseline_harness_sha256': hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest()}
    path = args.out / 'post-provenance.json'
    if path.exists():
        raise SystemExit('use a fresh output folder for each runtime revision')
    path.write_text(json.dumps(provenance, indent=2) + '\n')
    original = runner.argv
    def argv(arm, task, prompt):
        command = original(arm, task, prompt)
        return with_runtime(command, runtime) if arm == 'oh' else command
    runner.argv = argv
    sys.argv = [sys.argv[0], *rest, '--out', str(args.out)]
    runner.main()


if __name__ == '__main__':
    main()
