"""m1 방식 Liking 모델: 특징 계산, 학습 도구의 저장값 재현, 세션 적용."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from backend import m1_liking as M


class M1LikingTests(unittest.TestCase):
    def test_features_shape_and_rejection(self):
        rng = np.random.default_rng(0)
        fs = 250
        t = np.arange(int(7 * fs)) / fs
        x = 10 * np.sin(2 * np.pi * 10 * t)[:, None] + rng.normal(0, 3, (len(t), 4))
        vec = M.features(x[:3 * fs], x[3 * fs:], fs)
        self.assertEqual(vec.shape, (len(M.COLUMNS),))
        alpha_abs = M.COLUMNS.index("m1_O1_alpha_abs_db")
        theta_abs = M.COLUMNS.index("m1_O1_theta_abs_db")
        self.assertGreater(vec[alpha_abs], vec[theta_abs])  # 10 Hz 성분 → 알파가 가장 큼
        spiky = x.copy(); spiky[100, 0] += 1000
        self.assertIsNone(M.features(spiky[:3 * fs], spiky[3 * fs:], fs))   # 잡음 시행 제외
        self.assertIsNone(M.features(x[:fs], x[3 * fs:], fs))                # 기준선 부족

    def test_training_tool_export_matches_pipeline_and_session(self):
        from tools import train_m1_liking as T
        rng = np.random.default_rng(1)
        rows = []
        for s in range(1, 33):
            for v in range(1, 41 if s > 1 else 4):   # 1번은 시행 3개뿐: 같은 사람 평가에서만 빠져야 한다
                f = rng.normal(size=len(M.COLUMNS))
                rows.append({"participant": s, "video": v, "liking": float(np.clip(5 + 1.5 * f[9] + rng.normal(), 1, 9)),
                             "peak_uv": 500.0 if s == 2 else 50.0, "ok": True, **dict(zip(M.COLUMNS, f))})
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pd.DataFrame(rows).to_csv(d / "features.csv", index=False)
            T.main(["--data", str(d / "none"), "--out", str(d), "--model", str(d / "m1.json")])  # 내부에서 재현 검사
            model = json.loads((d / "m1.json").read_text(encoding="utf-8"))
            self.assertEqual(model["features"], M.COLUMNS)
            self.assertEqual(len(model["selected"]), 16)
            ev = model["evaluation"]["new_participant"]
            self.assertLess(ev["mae"], ev["mae_median_baseline"])  # 신호를 심어 둔 가짜 데이터에서는 이겨야 한다
            self.assertEqual(model["evaluation"]["within_person"]["participants"], 31)
            self.assertEqual(model["participants"], 32)
            T.main(["--data", str(d / "none"), "--out", str(d), "--model", str(d / "m1_clean.json"), "--artifact-uv", "200"])
            clean = json.loads((d / "m1_clean.json").read_text(encoding="utf-8"))
            self.assertEqual((clean["participants"], clean["training_artifact_uv"]), (31, 200.0))

            # 세션 적용: 4채널 기록 + 시행 3개
            fs = 250
            t = np.arange(int(40 * fs)) / fs
            eeg = pd.DataFrame(rng.normal(0, 5, (len(t), 4)), columns=M.CHANNELS)
            eeg.insert(0, "timestamp_s", t)
            trials = pd.DataFrame({"trial_index": [0, 1, 2], "fixation_onset": [5.0, 15.0, 25.0],
                                   "stimulus_onset": [8.0, 18.0, 28.0], "stimulus_offset": [12.0, 22.0, 32.0]})
            with mock.patch.object(M, "MODEL", d / "m1.json"):
                scores, note = M.predict_session(eeg, trials, fs, {"model_input": {"eeg": "eeg.csv"}})
                self.assertEqual(sorted(scores), [0, 1, 2])
                self.assertTrue(all(1 <= v <= 9 for v in scores.values()))
                self.assertIn("3/3", note)
                _, note = M.predict_session(eeg.drop(columns=["Pz"]), trials, fs, {"model_input": {}})
                self.assertIn("Pz", note)
            with mock.patch.object(M, "MODEL", d / "missing.json"):
                scores, note = M.predict_session(eeg, trials, fs, {"model_input": {}})
                self.assertEqual(scores, {})
                self.assertIn("m1_liking.json", note)


if __name__ == "__main__":
    unittest.main()
