import unittest
import numpy as np
import pandas as pd
from brainficial.inference import permutation_check, _score


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "stimulus_id": np.repeat([f"s{i:02d}" for i in range(12)], 2),
            "rating": np.repeat([1, 5]*6, 2),
            "feature_signal": np.repeat([-5., 5.]*6, 2),
        })

    def test_reproducible_pvalue_and_correction(self):
        result = permutation_check(self.frame, 19, exchangeable=True)
        self.assertEqual(result, permutation_check(self.frame, 19, exchangeable=True))
        self.assertEqual(result["observed_balanced_accuracy"], 1)
        self.assertEqual(len(result["null_scores"]), 19)
        self.assertEqual(result["p_value"], (1+sum(v >= 1 for v in result["null_scores"]))/20)
        self.assertGreater(result["p_value"], 0)

    def test_repeat_count_not_pseudoreplication(self):
        a = permutation_check(self.frame, 9, exchangeable=True)
        b = permutation_check(pd.concat([self.frame]*3), 9, exchangeable=True)
        self.assertEqual(a, b)
        self.assertEqual(a["n_stimuli"], 12)

    def test_assumptions_fail_closed(self):
        self.assertEqual(permutation_check(self.frame, 9)["status"], "not_run")
        for frame in [self.frame.drop(index=0), self.frame.assign(rating=3)]:
            self.assertEqual(permutation_check(frame, 9, exchangeable=True)["status"], "not_run")
        self.frame.loc[0, "rating"] = 5
        self.assertEqual(permutation_check(self.frame, 9, exchangeable=True)["status"], "not_run")

    def test_single_class_train_permutation_is_not_discarded(self):
        x = np.arange(4).reshape(-1, 1)
        y = np.array([0, 0, 1, 1])
        splits = [(np.array([0, 1]), np.array([2, 3])),
                  (np.array([2, 3]), np.array([0, 1]))]
        self.assertEqual(_score(x, y, splits), 0)

    def test_invalid_count(self):
        with self.assertRaises(ValueError):
            permutation_check(self.frame, -1, exchangeable=True)


if __name__ == "__main__":
    unittest.main()
