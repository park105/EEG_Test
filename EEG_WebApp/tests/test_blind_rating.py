import os
os.environ.setdefault("EEG_SOURCE", "mock")  # 테스트는 모의 EEG로 돈다(앱 기본값은 장비 미선택 none)
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import field_analysis, inference, main
from backend.config import settings
from test_webapp import simulate_session, STIMULI, SURVEY


class BlindRatingTests(unittest.TestCase):
    def test_predictions_invariant_to_live_responses(self):
        with tempfile.TemporaryDirectory() as root:
            s = simulate_session(Path(root), {})
            # Match the field protocol: live responses never enter the ratings CSV.
            ratings = s.dir / "ratings.csv"
            ratings.write_text(ratings.read_text().splitlines()[0] + "\n")
            s.meta["blind_rating"] = True
            s.save_meta()
            s.start_recording(settings.mock_channels)
            with patch.object(main.state, "session", s):
                def run_with(value):
                    for i, sid in enumerate(s.meta["order"]):
                        main.save_capture(s.id, i, field_analysis.TrialCapture(
                            stimulus_id=sid, camera_enabled=False, live_liking=value))
                    result = inference.run(s.dir, STIMULI, SURVEY, settings.mock_channels)
                    scores = [r["posterior_liking"] for r in result["items"]]
                    return scores, field_analysis.live_evaluation(s.dir, result)
                try:
                    first, evaluation1 = run_with(1)
                    second, evaluation9 = run_with(9)
                    self.assertTrue(any(v is not None for v in first))
                    self.assertEqual(first, second)
                    self.assertNotEqual(evaluation1["mae"], evaluation9["mae"])
                    self.assertNotIn("live_liking", (s.dir / "capture_0.json").read_text())
                    self.assertEqual(len(ratings.read_text().splitlines()), 1)
                finally:
                    s.stop_recording()

