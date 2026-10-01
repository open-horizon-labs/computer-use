"""One command for the call-budget guardrails; nonzero exit on any violation.

Needs the facade requirements (mcp): run with .venv-facade/bin/python or any interpreter that has them.
Never operates the desktop or a model: fixtures and fakes only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'computer_use'))

try:
    import call_budget
    import server  # noqa: F401  (the real tool functions are what get measured)
except ImportError as error:
    raise SystemExit('check_call_budget needs the facade requirements (%s); run .venv-facade/bin/python scripts/check_call_budget.py' % error)


def main():
    rows, problems, measured, listing = call_budget.all_violations(with_measure=True)
    width = max(len(r[0]) for r in rows)
    print('%-*s  %5s  %6s  %s' % (width, 'scenario', 'calls', 'budget', 'verdict'))
    for name, calls, limit, verdict, detail in rows:
        print('%-*s  %5d  %6d  %s  (%s)' % (width, name, calls, limit, verdict, detail))
    print()
    print('response bytes (JSON the server returned) and simulated waits, per scenario and call; ceilings in computer_use/RESPONSE_BUDGET.json (CE-FACADE-011)')
    print('%-*s  %7s  %6s  %s' % (width, 'scenario', 'total', 'wait_s', 'bytes per call [stage ms per call]'))
    for name, per_call, total, wait, ms in call_budget.response_table(measured, listing):
        print('%-*s  %7d  %6.2f  %s %s' % (width, name, total, wait, per_call, ms))
    sizes = listing['tools']
    print('tools/list per session: instructions %d + do %d+%d + look %d+%d (description+schema) = %d bytes' % (
        listing['instructions'], sizes['do']['description'], sizes['do']['schema'], sizes['look']['description'], sizes['look']['schema'],
        listing['instructions'] + sum(v['description'] + v['schema'] for v in sizes.values())))
    static = [p for p in problems if p.split(':')[0] not in {r[0] for r in rows}]
    print('static checks (budget and response-budget provenance, tool surface, skill default workflow): %s' % ('FAIL' if static else 'PASS'))
    for problem in problems:
        print('  - ' + problem)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
