import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from brainficial.deap import evaluate_person, extract_file, pair_order


class DEAPTests(unittest.TestCase):
    def test_fourth_label_baseline_and_preprocessed_layout(self):
        waveform = np.sin(2*np.pi*10*np.arange(8064)/128)
        waveform[384:] *= 2
        data = np.broadcast_to(waveform, (40, 40, 8064))
        labels = np.tile([1, 2, 3, 7.6], (40, 1))
        with patch("brainficial.deap.loadmat", return_value=dict(data=data, labels=labels)):
            f = extract_file(Path("s01.mat"))
        self.assertTrue(f.liking.eq(7.6).all())
        np.testing.assert_allclose(f.change_F3_alpha, 10*np.log10(4), atol=1e-5)
        self.assertEqual(len(f.filter(regex="^change_").columns), 6)

    def test_holdout_and_training_only_reference(self):
        f = pd.DataFrame(dict(participant="s01", video=np.arange(40),
            quality="ok", liking=np.linspace(1, 9, 40),
            change_x=np.arange(40), stimulus_x=np.arange(40)))
        _, predictions = evaluate_person(f)
        p = pd.DataFrame(predictions)
        self.assertTrue(p.groupby("video").fold.nunique().eq(1).all())
        self.assertFalse(p.duplicated(["method", "video"]).any())
        for _, g in p.groupby("fold"):
            self.assertTrue(g.reference.eq(f.loc[~f.video.isin(g.video), "liking"].median()).all())
        with self.assertRaises(ValueError):
            evaluate_person(pd.concat([f, f]))

    def test_ties_in_pair_order(self):
        self.assertEqual(pair_order(np.array([1, 1, 2]), np.array([1, 2, 2])), (1.5, 2))
