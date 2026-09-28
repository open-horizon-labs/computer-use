"""scripts/look_compare.py: the look claim's offline structure, and the promise that it never claims verification."""
import contextlib
import io
import json
import re
import unittest

import look_compare

class Real:
    """A stand-in for a REAL reader: the script only needs a factory returning extract/close (instant here, so no latency claim)."""
    def __init__(self):
        from test_do import LineReader
        self.inner = LineReader(look_compare.PATTERNS);self.requests = self.inner.requests
    def extract(self, req, sid):return self.inner.extract(req, sid)
    def close(self):pass


def make_reader():
    return Real()


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = look_compare.main(list(argv))
    return code, out.getvalue()


class LookCompare(unittest.TestCase):
    def test_structure_of_the_five_variants(self):
        code, text = run('--json')
        rows = {r['variant']: r for r in json.loads(text)['rows']}
        self.assertEqual(code, 0)
        default = rows['deterministic, default caps']
        self.assertEqual((default['shown'], default['of'], default['plan'], default['correct']), (40, 100, 'none (the target record is not among the 40 shown)', None))
        for name in ('deterministic, all 100 rows', 'deterministic, focus=Northwind', 'fields, all 100 rows', 'fields, focus=Northwind'):
            self.assertTrue(rows[name]['correct'], name);self.assertEqual(rows[name]['clicked'], ['INV-063'])
        self.assertEqual((rows['deterministic, focus=Northwind']['extraction_calls'], rows['deterministic, all 100 rows']['extraction_calls']), (0, 0))
        self.assertEqual((rows['fields, all 100 rows']['extraction_calls'], rows['fields, all 100 rows']['extraction_chunks']), (10, 10))
        self.assertEqual(rows['fields, focus=Northwind']['extraction_calls'], 1)
        self.assertLess(rows['deterministic, focus=Northwind']['bytes'], rows['deterministic, default caps']['bytes'])
        self.assertLess(rows['deterministic, all 100 rows']['bytes'], rows['fields, all 100 rows']['bytes'])
        self.assertLessEqual(default['bytes'], 6000)

    def test_the_report_says_offline_numbers_are_structure_and_size_only_and_never_claims_verification(self):
        # Wrong patch: print the fake reader's exact, instant numbers as if they were latency or accuracy, or declare the claim verified.
        code, text = run()
        self.assertIn('STRUCTURE AND SIZE ONLY', text);self.assertIn('NOT measured', text);self.assertIn('NOT VERIFIED', text)
        self.assertIn('LATENCY', text);self.assertIn('ACCURACY', text)
        self.assertNotRegex(text, r'(?i)claim is verified|confirmed|proved')
        self.assertNotIn('extract_ms=', text);self.assertNotIn('values_correct=', text)  # no latency or accuracy column with the fake reader

    def test_a_real_reader_can_be_passed_for_a_later_live_run(self):
        code, text = run('--reader', 'test_look_compare:make_reader')
        self.assertEqual(code, 0);self.assertIn('reader: REAL test_look_compare:make_reader', text)
        self.assertIn('extract_ms=', text);self.assertIn('values_correct=', text)
        self.assertNotIn('STRUCTURE AND SIZE ONLY', text)  # the disclaimer is for the fake reader; the claim line still says NOT VERIFIED
        self.assertIn('NOT VERIFIED', text)
        self.assertRegex(text, r'values_correct=\d+/\d+')


if __name__ == '__main__':unittest.main()
