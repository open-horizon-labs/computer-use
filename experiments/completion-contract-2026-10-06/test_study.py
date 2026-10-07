import asyncio,unittest
from study import trial
class ContractOwners(unittest.IsolatedAsyncioTestCase):
 async def test_combined_rejects_early_and_late_rejection(self):
  for scenario in ('reject','late_reject'):
   r=await trial('combined',scenario);self.assertEqual(r['terminal'],'rejected')
 async def test_evidence_does_not_trust_optimistic_echo(self):
  r=await trial('evidence','late_reject');self.assertEqual(r['terminal'],'rejected')
 async def test_missing_ack_is_not_completion(self):
  r=await trial('combined','missing_ack');self.assertEqual(r['terminal'],'ack_unavailable')
 async def test_wrong_record_stops(self):
  r=await trial('combined','record_change');self.assertEqual(r['terminal'],'context_changed');self.assertEqual(r['writes'],1)
 async def test_dependent_write_fenced_after_rejection(self):
  r=await trial('combined','dependent');self.assertEqual(r['terminal'],'rejected');self.assertEqual(r['writes'],1)
 async def test_partial_failure_is_not_hidden_by_second_success(self):
  r=await trial('combined','partial_failure');self.assertEqual(r['terminal'],'rejected');self.assertEqual(r['writes'],2)
 async def test_caller_cancellation_keeps_supervision(self):
  r=await trial('combined','cancel');self.assertTrue(r['supervisor_alive']);self.assertEqual(r['terminal'],'complete')
 async def test_stable_final_values(self):
  for mode in ('serial','supervision','evidence','combined'):
   r=await trial(mode);self.assertEqual(r['terminal'],'complete');self.assertEqual(r['state']['values'],{'name':'Alice','email':'a@example.test'})
 async def test_mutants_fail_keepers(self):
  echo=await trial('evidence','late_reject','trust_echo');self.assertNotEqual(echo['terminal'],'rejected')
  cancel=await trial('combined','cancel','cancel_watchers');self.assertEqual(cancel['terminal'],'supervision_cancelled')
  fence=await trial('supervision','reject','skip_fence');self.assertEqual(fence['terminal'],'complete')

 async def test_acknowledgement_bound_to_transaction_field_record_generation(self):
  for field in ('tx','key','record','generation'):
   r=await trial('combined','ack_fault_'+field);self.assertEqual(r['terminal'],'ack_binding')
