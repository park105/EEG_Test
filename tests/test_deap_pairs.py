import unittest
import numpy as np
import pandas as pd
from brainficial.deap_pairs import evaluate, credit


class PairTests(unittest.TestCase):
    def test_heldout_ratings_cannot_change_fold_model(self):
        rng = np.random.default_rng(8)
        f = pd.DataFrame(dict(participant="p", video=np.arange(20), quality="ok",
                              liking=rng.integers(1, 10, size=20)))
        for mode in ["change", "stimulus"]:
            for ch in ["F3", "F4"]:
                for band in ["theta", "alpha", "beta"]:
                    f[f"{mode}_{ch}_{band}"] = rng.normal(size=20)
        orig = pd.DataFrame(evaluate(f, 42)).query("fold == 0")
        heldout = set(orig.video_a) | set(orig.video_b)
        self.assertEqual(len(heldout), 4)
        self.assertFalse(orig.duplicated(["method","video_a","video_b"]).any())
        f.loc[f.video.isin(heldout), "liking"] = 5
        new = pd.DataFrame(evaluate(f, 42)).query("fold == 0")
        np.testing.assert_allclose(orig.direct_margin, new.direct_margin)
        self.assertTrue(new.direct_credit.isna().all())
        self.assertEqual(credit(0, -1), .5)
