import unittest
from decider_adapter import validate_answer


class ProviderBoundary(unittest.TestCase):
    def setUp(self):
        self.criteria = {
            "type": "Enter the token",
            "reobserve": "Refresh",
            "abstain": "Stop",
        }
        self.answer = {
            "choice": "type",
            "confidence": 0.9,
            "probabilities": {"type": 0.9, "reobserve": 0.05, "abstain": 0.05},
        }

    def test_constrained_generation_requires_explicit_verification(self):
        answer = dict(choice="type", confidence=None, probabilities=None,
                      method="constrained_generation", requires_verification=True)
        self.assertEqual(validate_answer(answer, self.criteria), ("type", None, None))
        for update in [dict(choice="unknown"), dict(method=None), dict(requires_verification=False)]:
            with self.assertRaises(ValueError):
                validate_answer(dict(answer, **update), self.criteria)

    def test_valid(self):
        self.assertEqual(validate_answer(self.answer, self.criteria)[0], "type")

    def test_direct_scores_are_not_confidence(self):
        answer = dict(choice='type', confidence=None, probabilities=None,
                      scores=self.answer['probabilities'], method='single_position_logits',
                      requires_verification=True, calibrated=False, thinking=False, output_positions=1)
        self.assertEqual(validate_answer(answer, self.criteria), ('type', None, None))
        for patch in [dict(confidence=.9), dict(thinking=True), dict(scores={'type': 1}), dict(calibrated=True)]:
            with self.assertRaises(ValueError):
                validate_answer(answer | patch, self.criteria)

    def test_unknown_or_missing_candidate(self):
        for p in [{"type": 1.0}, {"type": 0.9, "reobserve": 0.05, "shell": 0.05}]:
            with self.assertRaises(ValueError):
                validate_answer(dict(self.answer, probabilities=p), self.criteria)

    def test_nonfinite_and_inconsistent(self):
        for update in [
            {"confidence": float("nan")},
            {"choice": "abstain"},
            {"confidence": True},
            {"probabilities": {"type": 0.9, "reobserve": 0.1, "abstain": 0.1}},
        ]:
            with self.assertRaises(ValueError):
                validate_answer(dict(self.answer, **update), self.criteria)


if __name__ == "__main__":
    unittest.main()
