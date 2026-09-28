"""The claim to verify (CE-FACADE-005): "a deterministic look is good enough on a 100-row page; keep NuExtract in the default look only if it wins".

Runs the synthetic 100-row `invoices` page (facade/shapes.py: rows with several fields and near-duplicates, shaped like the eval suite's
`invoices` task) through cua_look without and with `fields`, then executes the plan a scripted LLM writes from each look, and reports:
response bytes, extraction calls and chunks, and whether the plan clicked the right row.

WHAT THIS DOES NOT MEASURE, and the report says so every time: with the default fake reader the numbers are STRUCTURE AND SIZE ONLY.
Extraction LATENCY and NuExtract ACCURACY cannot be measured offline (the fake reader is exact by construction and instant). Pass
`--reader package.module:callable` (a factory returning an object with extract(request, snapshot_id) and close(), for example
`page_candidates:NuExtractPage` with the fleet profile configured) for a LATER live run: the same record texts go to the real endpoint,
`ms_by_stage.extract` becomes wall time, and value accuracy is scored against the displayed strings. That run is NOT done here, so the claim
is NOT verified: what remains is the live latency of look(fields=...) on 100 rows and its accuracy against the deterministic look.

No Driver, desktop or network is used (the page is a fake tree); only a real reader you name would reach the network.
"""
import argparse
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'facade'))
sys.path.insert(0, str(ROOT / 'inference/cua-decider/capability-dispatch'))

import shapes as sh  # noqa: E402
import test_live_shapes as lv  # noqa: E402
from core import Facade  # noqa: E402
from test_core import FakeChooser  # noqa: E402
from test_do import LineReader  # noqa: E402

FIELDS = {'vendor': {'description': 'Vendor name'}, 'amount': {'description': 'Invoice amount'}, 'due': {'description': 'Due date'}}
PATTERNS = {'vendor': r'"cells": \["[^"]*", "([^"]*)"', 'amount': r'"(\$[\d,\.]+)"', 'due': r'"(\d{4}-\d{2}-\d{2})"'}
GOAL = 'Approve the invoice from Northwind Traders for $1,240.00'
WANT = ['Northwind Traders', '$1,240.00']
TARGET = 'INV-063'


def clicked_invoice(driver):
    """The invoice id of the row whose button the plan pressed (from the fake tree, never from the tool's own claim)."""
    els = {e['element_index']: e for e in sh.invoices()}
    out = []
    for click in driver.executed:
        index = int(click['element_token'].rsplit(':', 1)[1])
        row = els[els[index]['parent_index']]['parent_index']
        first = next(e for e in els.values() if e.get('parent_index') is not None and els[e['parent_index']].get('parent_index') == row and e['role'] == 'AXStaticText')
        out.append(first['value'])
    return out


def plan_from(look):
    """The scripted LLM: from the lines the look SHOWED, eq/contains conditions for what it wants; only if they single out one displayed record."""
    def holds(record, cond):
        lines = [x.lower() for x in record['lines']];value = cond['value'].lower()
        return any(x == value for x in lines) if cond['line'] == 'eq' else any(value in x for x in lines)
    every = [x.lower() for r in look['records'] for x in r['lines']]
    conds = [{'line': 'eq' if w.lower() in every else 'contains', 'value': w} for w in WANT]
    hits = [r for r in look['records'] if all(holds(r, c) for c in conds)]
    return (conds, hits[0]) if len(hits) == 1 else (None, None)


def reader_factory(spec):
    if not spec:
        return lambda: LineReader(PATTERNS), 'fake (exact by construction, instant)'
    module, _, name = spec.partition(':')
    return getattr(importlib.import_module(module), name), 'REAL %s' % spec


def run_variant(name, look_kwargs, make_reader, real):
    driver = sh.ShapeDriver(sh.invoices());driver.script = sh.approved_status
    reader_holder = {}
    def factory():
        reader_holder['r'] = make_reader();return reader_holder['r']
    facade = Facade(driver, generic_factory=FakeChooser, reader_factory=factory, visual_factory=lv.UnknownVision, sleep=lambda s: None)
    look = facade.look('Demo', **look_kwargs)
    size = len(json.dumps(look))
    extraction = look.get('extraction') or {'calls': 0, 'chunks': 0}
    conds, record = plan_from(look)
    row = {'variant': name, 'bytes': size, 'shown': len(look['records']), 'of': look['counts']['records'], 'cut': look['truncated'],
           'extraction_calls': extraction['calls'], 'extraction_chunks': extraction['chunks'], 'look_id': look['look_id'],
           'extract_ms': look['ms_by_stage'].get('extract', 0) if real else None, 'plan': None, 'clicked': None, 'correct': None, 'values_correct': None}
    if look_kwargs.get('fields') and real:
        good = sum(1 for r in look['records'] if r.get('values') and r['values'].get('vendor') == r['lines'][1] and r['values'].get('amount') == r['lines'][2])
        row['values_correct'] = '%d/%d' % (good, len(look['records']))
    if conds is None:
        row['plan'] = 'none (the target record is not among the %d shown)' % row['shown']
        return row
    done = facade.do(GOAL, title='Demo', expect=None, look_id=look['look_id'], steps=[{'do': 'press', 'where': {'lines': conds}, 'expect': 'Approved ' + record['lines'][0]}])
    row['plan'] = done['status']
    row['clicked'] = clicked_invoice(driver)
    row['correct'] = row['clicked'] == [TARGET]
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--reader', help='package.module:callable returning a reader (extract/close) for a LATER live run; default: the fake reader')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    make_reader, label = reader_factory(args.reader)
    real = bool(args.reader)
    variants = [('deterministic, default caps', {}),
                ('deterministic, all 100 rows', {'max_records': 100, 'max_bytes': 30000}),
                ('deterministic, focus=Northwind', {'focus': 'Northwind'}),
                ('fields, all 100 rows', {'fields': FIELDS, 'max_records': 100, 'max_bytes': 60000}),
                ('fields, focus=Northwind', {'fields': FIELDS, 'focus': 'Northwind'})]
    rows = [run_variant(n, kw, make_reader, real) for n, kw in variants]
    if args.json:
        print(json.dumps({'reader': label, 'rows': rows}, indent=1))
        return 0
    print('reader: %s' % label)
    print('%-32s %6s %9s %5s %7s  %s' % ('variant', 'bytes', 'shown', 'calls', 'chunks', 'plan target'))
    for r in rows:
        target = r['plan'] if r['correct'] is None else '%s, clicked %s -> %s' % (r['plan'], ','.join(r['clicked']), 'CORRECT' if r['correct'] else 'WRONG')
        extra = ''
        if real:
            extra = '  extract_ms=%s values_correct=%s' % (r['extract_ms'], r['values_correct'])
        print('%-32s %6d %4d/%-4d %5d %7d  %s%s' % (r['variant'], r['bytes'], r['shown'], r['of'], r['extraction_calls'], r['extraction_chunks'], target, extra))
    print()
    if not real:
        print('OFFLINE NUMBERS ARE STRUCTURE AND SIZE ONLY. The fake reader is exact by construction and instant: extraction LATENCY and NuExtract ACCURACY are NOT measured here.')
    print('THE CLAIM IS NOT VERIFIED BY THIS SCRIPT. Remaining, to be measured live: (1) wall time of look(fields=...) on 100 rows (%d reader calls of at most 10 records each; the real extractor has a 20 s whole-call deadline and chunks 5 records internally); '
          '(2) NuExtract accuracy on those records against the displayed strings (--reader ... prints values_correct); (3) whether an LLM writes correct plans from the deterministic look alone on messy pages.' % next(r['extraction_calls'] for r in rows if r['variant'] == 'fields, all 100 rows'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
