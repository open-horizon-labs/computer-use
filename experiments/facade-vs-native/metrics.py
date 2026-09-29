"""Pure aggregation and preregistered verdict logic for the eval suite. No I/O.

Constants here mirror PREREGISTRATION.md; test_suite.py fails if the two drift apart.
"""
import math
from collections import defaultdict

NOISE_FLOOR, NOISE_CAP, NOISE_DEFAULT = 0.10, 0.50, 0.25
RATE_BAND = 0.10
LARGE_LIFT_SUCCESS, LARGE_LIFT_COST = 0.20, 0.30
MIN_RUNS_PER_CELL, MIN_TASKS = 3, 12
CONTINUOUS = ('turns', 'wall_s', 'cost_usd')
METRICS = ('turns', 'wall_s', 'cost_usd', 'success_rate', 'wrong_click_rate', 'cost_per_success')
HAIKU = 'claude-haiku-4-5-20251001'


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def quantile(values, q):
    v = sorted(values)
    if not v:
        return None
    pos = (len(v) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def median_iqr(values):
    values = [x for x in values if x is not None]
    if not values:
        return {'median': None, 'iqr': None, 'n': 0}
    return {'median': quantile(values, .5), 'iqr': quantile(values, .75) - quantile(values, .25), 'n': len(values)}


def valid(rows):
    return [r for r in rows if not r.get('invalid')]


def summarize(rows):
    rows = valid(rows)
    n = len(rows)
    ok = sum(r['outcome'] == 'correct' for r in rows)
    wrong_runs = sum(r['wrong_clicks'] > 0 for r in rows)
    costs = [r['cost_usd'] for r in rows if r.get('cost_usd') is not None]
    return {
        'n': n, 'successes': ok, 'success_rate': ok / n if n else None, 'success_ci': wilson(ok, n),
        'wrong_click_runs': wrong_runs, 'wrong_click_rate': wrong_runs / n if n else None, 'wrong_click_ci': wilson(wrong_runs, n),
        'turns': median_iqr([r['turns'] for r in rows]), 'mcp_calls': median_iqr([r['mcp_calls'] for r in rows]),
        'wall_s': median_iqr([r['wall_s'] for r in rows]), 'cost_usd': median_iqr(costs),
        'total_cost_usd': sum(costs) if costs else None,
        'cost_per_success': (sum(costs) / ok) if (costs and ok) else None,
        'outcomes': {o: sum(r['outcome'] == o for r in rows) for o in ('correct', 'wrong', 'partial', 'no-action', 'timeout')},
    }


def group(rows, keyfn):
    out = defaultdict(list)
    for r in rows:
        keys = keyfn(r)
        for k in (keys if isinstance(keys, list) else [keys]):
            out[k].append(r)
    return dict(out)


def by_arm_model(rows):
    return {k: summarize(v) for k, v in sorted(group(valid(rows), lambda r: (r['arm'], r['model'])).items())}


def by_category(rows):
    g = group(valid(rows), lambda r: [(r['arm'], r['model'], t) for t in r['tags']])
    return {k: summarize(v) for k, v in sorted(g.items())}


def paired_deltas(rows, arm, baseline='native'):
    """Per (model, task): mean of (arm - baseline) over runs paired by rep."""
    idx = {(r['model'], r['task'], r['rep'], r['arm']): r for r in valid(rows)}
    acc = defaultdict(list)
    for (model, task, rep, a), r in idx.items():
        if a != arm or (model, task, rep, baseline) not in idx:
            continue
        b = idx[(model, task, rep, baseline)]
        d = {'success': int(r['outcome'] == 'correct') - int(b['outcome'] == 'correct'),
             'wrong_clicks': r['wrong_clicks'] - b['wrong_clicks']}
        for m in CONTINUOUS:
            d[m] = None if r.get(m) is None or b.get(m) is None else r[m] - b[m]
        acc[(model, task)].append(d)
    out = {}
    for key, ds in sorted(acc.items()):
        row = {'pairs': len(ds)}
        for m in ('success', 'wrong_clicks') + CONTINUOUS:
            vals = [d[m] for d in ds if d[m] is not None]
            row[m] = sum(vals) / len(vals) if vals else None
        out[key] = row
    return out


def _band(rows_base, tasks):
    """Noise band for continuous metrics from the baseline's own spread."""
    rels = []
    for t in tasks:
        cell = [r['turns'] for r in rows_base if r['task'] == t]
        if len(cell) < MIN_RUNS_PER_CELL:
            return NOISE_DEFAULT
        s = median_iqr(cell)
        rels.append(s['iqr'] / s['median'] if s['median'] else 0.0)
    if not rels:
        return NOISE_DEFAULT
    return min(NOISE_CAP, max(NOISE_FLOOR, quantile(rels, .5)))


def compare(rows, arm, baseline='native', model=None, tag=None):
    """Judge `arm` against `baseline` on the six primary metrics. Returns dict with per-metric
    'beats' | 'worse' | 'tie' plus the numbers used."""
    rows = valid(rows)
    if model:
        rows = [r for r in rows if r['model'] == model]
    if tag:
        rows = [r for r in rows if tag in r['tags']]
    a = [r for r in rows if r['arm'] == arm]
    b = [r for r in rows if r['arm'] == baseline]
    tasks = sorted({r['task'] for r in a} & {r['task'] for r in b})
    a = [r for r in a if r['task'] in tasks]
    b = [r for r in b if r['task'] in tasks]
    res = {'tasks': tasks, 'n_arm': len(a), 'n_baseline': len(b), 'metrics': {}}
    if not tasks:
        return res
    band = _band(b, tasks)
    res['band'] = band
    for m in CONTINUOUS:
        logs = []
        for t in tasks:
            va = median_iqr([r[m] for r in a if r['task'] == t and r.get(m) is not None])['median']
            vb = median_iqr([r[m] for r in b if r['task'] == t and r.get(m) is not None])['median']
            if va and vb:
                logs.append(math.log(va / vb))
        g = math.exp(sum(logs) / len(logs)) if logs else None
        res['metrics'][m] = _judge_ratio(g, band)
    sa, sb = summarize(a), summarize(b)
    ca, cb = sa['cost_per_success'], sb['cost_per_success']
    res['metrics']['cost_per_success'] = _judge_ratio(ca / cb if ca and cb else None, band)
    for m, sign in (('success_rate', 1), ('wrong_click_rate', -1)):
        d = sa[m] - sb[m]
        verdict = 'beats' if sign * d >= RATE_BAND else 'worse' if sign * d <= -RATE_BAND else 'tie'
        res['metrics'][m] = {'verdict': verdict, 'diff': d, 'arm': sa[m], 'baseline': sb[m],
                             'ci_arm': sa[m.replace('rate', 'ci') if m == 'success_rate' else 'wrong_click_ci'],
                             'ci_baseline': sb['success_ci' if m == 'success_rate' else 'wrong_click_ci']}
    return res


def _judge_ratio(g, band):
    if g is None:
        return {'verdict': 'tie', 'ratio': None}
    return {'verdict': 'beats' if g < 1 - band else 'worse' if g > 1 + band else 'tie', 'ratio': g}


def _overlap(x, y):
    return not (x[1] < y[0] or y[1] < x[0])


def stack_stronger(cmp_):
    """Decision rule 2 applied to one compare() result."""
    ms = cmp_['metrics']
    if not ms:
        return {'stronger': False, 'label': 'no-data'}
    beats = [m for m, v in ms.items() if v['verdict'] == 'beats']
    worse = [m for m, v in ms.items() if v['verdict'] == 'worse']
    if not beats or worse:
        return {'stronger': False, 'label': 'no', 'beats': beats, 'worse': worse}
    established = any(m in ('success_rate', 'wrong_click_rate') and not _overlap(ms[m]['ci_arm'], ms[m]['ci_baseline']) for m in beats)
    return {'stronger': True, 'label': 'established' if established else 'directional', 'beats': beats, 'worse': worse}


def enough_data(rows, arms, model):
    rows = [r for r in valid(rows) if r['model'] == model and r['arm'] in arms]
    cells = defaultdict(int)
    for r in rows:
        cells[(r['task'], r['arm'])] += 1
    tasks = {t for t, _ in cells}
    ok = [t for t in tasks if all(cells[(t, a)] >= MIN_RUNS_PER_CELL for a in arms)]
    return len(ok) >= MIN_TASKS


def verdict(rows, stack_arms=('stack', 'stack-advanced'), baseline='native', primary_model=HAIKU):
    """Apply decision rules 1-4. Returns a dict; never raises on missing data."""
    out = {'baseline': baseline, 'primary_model': primary_model, 'per_arm': {}}
    models = sorted({r['model'] for r in valid(rows)})
    for arm in stack_arms:
        if not any(r['arm'] == arm for r in rows):
            continue
        entry = {'models': {}}
        for model in models:
            if not enough_data(rows, (arm, baseline), model):
                entry['models'][model] = {'label': 'insufficient-data'}
                continue
            c = compare(rows, arm, baseline, model=model)
            entry['models'][model] = dict(stack_stronger(c), band=c.get('band'))
        entry['claim'] = entry['models'].get(primary_model, {'label': 'insufficient-data'})['label']
        # invalidation (rule 3): no metric where the stack beats the baseline over each scope
        scopes = {'all': compare(rows, arm, baseline), 'hard-surface': compare(rows, arm, baseline, tag='canvas'),
                  'cheap-driver': compare(rows, arm, baseline, model=primary_model)}
        entry['invalidation_scopes'] = {k: [m for m, v in c['metrics'].items() if v['verdict'] == 'beats'] for k, c in scopes.items()}
        entry['invalidated'] = all(c['tasks'] for c in scopes.values()) and not any(entry['invalidation_scopes'].values())
        entry['invalidated'] = entry['invalidated'] and entry['claim'] != 'insufficient-data'
        entry['provisional'] = baseline != 'native-skill'
        # rule 4 triggers
        h = compare(rows, arm, baseline, model=primary_model)
        cats = {t for r in valid(rows) for t in r['tags']}
        anywhere = [h] + [compare(rows, arm, baseline, model=mo) for mo in models] + [compare(rows, arm, baseline, tag=t) for t in cats]
        entry['no_advantage_anywhere'] = not any(v['verdict'] == 'beats' for c in anywhere for v in c['metrics'].values())
        lift = False
        if h['metrics']:
            sm = h['metrics']['success_rate']
            lift = (sm['diff'] >= LARGE_LIFT_SUCCESS) or (
                h['metrics']['cost_per_success']['ratio'] is not None
                and h['metrics']['cost_per_success']['ratio'] <= 1 - LARGE_LIFT_COST and sm['verdict'] != 'worse')
        entry['large_cheap_driver_lift'] = lift
        entry['action'] = ('salvage to the thin layer plus Perception' if entry['no_advantage_anywhere']
                           else 'pursue the server-side agent (D)' if lift else 'mixed: decide on per-category evidence')
        if entry['claim'] == 'insufficient-data':
            entry['action'] = 'insufficient-data: no trigger fires'
        out['per_arm'][arm] = entry
    return out
