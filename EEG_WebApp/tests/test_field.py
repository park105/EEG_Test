import tempfile
import unittest
from pathlib import Path

import numpy as np

from backend.field_analysis import PaperScores, associations, evaluate, gamma_db, summarize_capture, write_json


class FieldAnalysisTests(unittest.TestCase):
    def test_camera_baseline_and_missing_shoulders(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            samples = [{"phase": phase, "smile": smile, "shoulder": None}
                       for phase, smile in (("fixation_onset", 0.1), ("stimulus_onset", 0.5))]
            write_json(directory / "capture_1.json", {"stimulus_id": "a", "camera_enabled": True, "samples": samples})
            camera = summarize_capture(directory, 1, "a")
            self.assertAlmostEqual(camera["smile_delta"], 0.4)
            self.assertIsNone(camera["shoulder_delta"])
            self.assertFalse(summarize_capture(directory, 1, "b"))

    def test_gamma_and_within_session_association(self):
        t = np.arange(512) / 128
        signal = np.tile(np.sin(2*np.pi*35*t)[:, None], (1, 4))
        self.assertAlmostEqual(gamma_db(signal, 128), 10*np.log10(0.5), places=2)
        pairs = [{"camera": {"smile_delta": v}, "gamma_db": v+2} for v in range(4)]
        self.assertAlmostEqual(associations(pairs)["smile_delta"]["rho"], 1)
        self.assertIsNone(associations(pairs[:2])["smile_delta"]["rho"])

    def test_paper_scale_and_category_unit(self):
        result = {"items": [{"stimulus_id": str(i), "category": "city", "posterior_liking": v}
                            for i, v in enumerate([3, 7, None])]}
        scores = PaperScores(level="category", scale=5, scores={"city": 4})
        report = evaluate(result, scores)
        self.assertEqual((report["n"], report["mae"], report["rmse"]), (1, 2, 2))
        with self.assertRaises(ValueError):
            evaluate(result, PaperScores(level="photo", scale=9, scores={"unknown": 7}))

