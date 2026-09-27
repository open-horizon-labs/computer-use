"""Bundle authoritative sketch for copied skill installs; --check detects drift."""
import argparse
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root / 'inference/cua-decider/capability-dispatch/SKETCH.md'
target = root / 'skills/cua-capability-dispatch/references/sketch.md'
# The only repo-relative source link is rewritten for the installed copy.
text = source.read_text().replace('`../README.md#reusable-bounded-selector`',
    '`inference/cua-decider/README.md#reusable-bounded-selector` in the runtime checkout')
text = '> Bundled policy snapshot. Runtime checkout is authoritative; see [setup](setup.md). Regenerate with scripts/sync_skill_references.py.\n\n' + text
parser = argparse.ArgumentParser()
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
if args.check:
    if not target.exists() or target.read_text() != text:
        raise SystemExit('Skill sketch snapshot is stale; run scripts/sync_skill_references.py')
else:
    target.write_text(text)
