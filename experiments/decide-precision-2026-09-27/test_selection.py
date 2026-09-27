import unittest
from selection import choose,metrics

class SelectionChecks(unittest.TestCase):
 def test_tie_never_uses_candidate_order(self):
  self.assertIsNone(choose({1:.999,0:.999},.5,0))
 def test_margin_defers_ambiguous_match(self):
  self.assertIsNone(choose({0:.999,1:.998},.9,.01))
 def test_wrong_high_confidence_is_still_wrong(self):
  result=metrics([{'gold':1,'scores':[{'score':.9999},{'score':.9}]}],.99,0)
  self.assertEqual(result['wrong'],1);self.assertEqual(result['precision'],0)
  self.assertEqual(result['target_removed_acceptances'],1)
 def test_overflow_counts_against_coverage(self):
  result=metrics([{'gold':0,'deferred':'token_budget'},{'gold':0,'scores':[{'score':.99}]}],.9,0)
  self.assertEqual(result['coverage'],.5)
 def test_no_candidate_is_not_success(self):
  self.assertIsNone(choose({},.5,0))
 def test_removal_can_expose_confident_wrong_alternative(self):
  result=metrics([{'gold':0,'scores':[{'score':.999},{'score':.99}]}],.9,0)
  self.assertEqual(result['correct'],1);self.assertEqual(result['target_removed_acceptances'],1)
if __name__=='__main__':unittest.main()
