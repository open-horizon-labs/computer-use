import unittest
from cascade import Cascade

C={'a':'First action','b':'Second action','reobserve':'Observe','abstain':'Stop'}
class Fake:
    def __init__(self,choice='a',confidence=.99,raises=False):self.choice=choice;self.confidence=confidence;self.calls=0;self.raises=raises
    def __call__(self,state,candidates):
        self.calls+=1
        if self.raises:raise RuntimeError('private provider details')
        return {'choice':self.choice,'confidence':self.confidence}
class Routing(unittest.TestCase):
    def make(self,**kwargs):
        self.fast=Fake();self.fallback=Fake('b');return Cascade(self.fast,self.fallback,**kwargs)
    def test_confident_choice_uses_fast(self):
        r=self.make();self.assertEqual(r.select('goal','page',C)['choice'],'a');self.assertEqual(self.fallback.calls,0)
    def test_low_confidence_before_execution(self):
        r=self.make();self.fast.confidence=.4;result=r.select('goal','page',C)
        self.assertEqual(result['choice'],'b');self.assertEqual(result['reason'],'low_confidence_or_defer')
    def test_no_progress_and_unchanged_cannot_reset_budget(self):
        r=self.make();r.select('goal','page',C)
        result=r.select('goal','page',C,feedback='verified_progress')
        self.assertEqual(result['route'],'fallback');self.assertEqual(self.fast.calls,1)
    def test_failure_on_changed_page_escalates(self):
        r=self.make();r.select('goal','page',C)
        self.assertEqual(r.select('goal','different',C,feedback='failed')['route'],'fallback')
    def test_verified_progress_resets(self):
        r=self.make();r.select('goal','page',C);r.select('goal','page',C)
        self.assertEqual(r.select('goal','new page',C,feedback='verified_progress')['route'],'fast')
    def test_explicit_safe_retry_has_bound(self):
        r=self.make(max_fast_attempts=2);r.select('goal','page',C)
        self.assertEqual(r.select('goal','new',C,feedback='safe_retry')['route'],'fast')
        self.assertEqual(r.select('goal','newer',C,feedback='safe_retry')['route'],'fallback')
    def test_provider_error_and_invalid_choice_escalate(self):
        for invalid in [True,False]:
            r=self.make();self.fast.raises=invalid;self.fast.choice='unapproved'
            self.assertEqual(r.select('goal','page',C)['choice'],'b')
    def test_fallback_error_fails_closed_without_private_text(self):
        r=self.make();self.fast.raises=True;self.fallback.raises=True
        with self.assertRaisesRegex(RuntimeError,'no action authorized') as ctx:r.select('goal','page',C)
        self.assertNotIn('private provider details',str(ctx.exception))
    def test_bad_fallback_id_never_authorized(self):
        r=self.make();self.fast.confidence=0;self.fallback.choice='unapproved'
        with self.assertRaises(RuntimeError):r.select('goal','page',C)
    def test_reserved_choices_and_nan_escalate(self):
        for choice,confidence in [('reobserve',.99),('abstain',.99),('a',float('nan'))]:
            r=self.make();self.fast.choice=choice;self.fast.confidence=confidence
            self.assertEqual(r.select('goal','page',C)['route'],'fallback')
if __name__=='__main__':unittest.main()
