"""Rank task losses without counting quick failures or missing usage as wins."""
import argparse
import json
from pathlib import Path
from statistics import median


def rank(rows, repetitions=3):
    results = []
    for task in sorted({r['task'] for r in rows}):
        cells = {arm: [r for r in rows if r['task'] == task and r['arm'] == arm]
                 for arm in ('native', 'oh')}
        if any(len(cell) < repetitions for cell in cells.values()):
            continue
        if any(r['outcome'] in ('infrastructure-blocked', 'permission-blocked') for cell in cells.values() for r in cell):
            results.append({'task': task, 'audit_reasons': ['comparison_unavailable'],
                            'completion': {arm: sum(r['outcome'] == 'correct' for r in cell) for arm, cell in cells.items()},
                            'median_wall_s': None, 'wall_excess_s': None, 'median_total_tokens': None, 'token_excess': None})
            continue
        correct = {arm: sum(r['outcome'] == 'correct' for r in cell) for arm, cell in cells.items()}
        wall = {arm: median(r['wall_s'] for r in cell) for arm, cell in cells.items()}
        usage_complete = all(all(r.get('total_tokens') is not None for r in cell) for cell in cells.values())
        tokens = {arm: median(r['total_tokens'] for r in cell) for arm, cell in cells.items()} if usage_complete else None
        losses = []
        if correct['oh'] < correct['native']: losses.append('completion')
        if wall['oh'] > wall['native']: losses.append('wall')
        if tokens and tokens['oh'] > tokens['native']: losses.append('tokens')
        # Completion ties at less than full success still need an audit.
        if correct['oh'] < len(cells['oh']) and 'completion' not in losses: losses.append('incomplete')
        if not usage_complete: losses.append('usage_unavailable')
        if losses:
            results.append({'task': task, 'audit_reasons': losses, 'completion': correct,
                            'median_wall_s': wall, 'wall_excess_s': wall['oh'] - wall['native'],
                            'median_total_tokens': tokens,
                            'token_excess': tokens['oh'] - tokens['native'] if tokens else None})
    return sorted(results, key=lambda r: (-max(0, r['completion']['native'] - r['completion']['oh']),
                                         -max(0, r['wall_excess_s'] or 0), -(r['token_excess'] or 0)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('metrics', type=Path)
    parser.add_argument('--repetitions', type=int, default=3)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.metrics.read_text().splitlines()]
    print(json.dumps(rank(rows, args.repetitions), indent=2))
