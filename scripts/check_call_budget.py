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
    rows, problems = call_budget.all_violations()
    width = max(len(r[0]) for r in rows)
    print('%-*s  %5s  %6s  %s' % (width, 'scenario', 'calls', 'budget', 'verdict'))
    for name, calls, limit, verdict, detail in rows:
        print('%-*s  %5d  %6d  %s  (%s)' % (width, name, calls, limit, verdict, detail))
    static = [p for p in problems if p.split(':')[0] not in {r[0] for r in rows}]
    print('static checks (budget provenance, tool surface, skill default workflow): %s' % ('FAIL' if static else 'PASS'))
    for problem in problems:
        print('  - ' + problem)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
