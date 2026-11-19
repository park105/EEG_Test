"""Regression checks for the six pre-experiment safety failures."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from backend import features, inference, m1_liking, posterior
from backend.config import settings
from backend.eeg.gusbamp_source import GUSBampSource
from backend.export import export_session
from backend.quality import channel_quality
from test_webapp import simulate_session, STIMULI, SURVEY


class SignalSafetyTests(unittest.TestCase):
    def test_nan_and_inf_are_bad_and_json_safe(self):
        x = np.random.default_rng(1).normal(0, 5, (512, 4))
        for bad in (np.nan, np.inf):
            x[4, 0] = bad
            q = channel_quality(x, 128, posterior.CHANNELS)
            self.assertEqual(q[0]["status"], "bad")
            self.assertEqual(q[1]["status"], "good")
            json.dumps(q, allow_nan=False)

    def test_near_flat_rejected_by_all_feature_paths(self):
        fs = 128
        x = np.tile((0.01 * np.sin(np.arange(7 * fs) * 2 * np.pi * 10 / fs))[:, None], (1, 4))
        base, stim = x[:3 * fs], x[3 * fs:]
        self.assertIsNone(posterior.extract(base, stim, fs))
        self.assertIsNone(m1_liking.features(base, stim, fs))
        self.assertEqual(features.trial_features(base, stim, fs, posterior.CHANNELS)[1], "flat_channel")
        self.assertTrue(all(c["status"] == "bad" for c in channel_quality(stim, fs, posterior.CHANNELS)))

    def test_one_missing_sample_blocks_logistic_and_ridges(self):
        with tempfile.TemporaryDirectory() as d:
            s = simulate_session(Path(d), {})
            eeg = pd.read_csv(s.dir / "eeg.csv").drop(index=4000)
            eeg.to_csv(s.dir / "eeg.csv", index=False)
            original = (s.dir / "eeg.csv").read_bytes()
            r = inference.run(s.dir, STIMULI, SURVEY, settings.feature_channels)
            self.assertEqual(r["model"]["name"], "blocked")
            self.assertEqual(r["n_usable"], 0)
            for item in r["items"]:
                for key in ("eeg_like_probability", "posterior_liking", "m1_liking", "gamma_db"):
                    self.assertIsNone(item[key], key)
            self.assertEqual(original, (s.dir / "eeg.csv").read_bytes())

    def test_nonfinite_eeg_blocks_without_zero_imputation(self):
        with tempfile.TemporaryDirectory() as d:
            s = simulate_session(Path(d), {})
            eeg = pd.read_csv(s.dir / "eeg.csv")
            eeg.iloc[4000, 1] = np.nan
            eeg.to_csv(s.dir / "eeg.csv", index=False)
            r = inference.run(s.dir, STIMULI, SURVEY, settings.feature_channels)
            self.assertEqual(r["model"]["name"], "blocked")
            self.assertTrue(all(i["eeg_like_probability"] is None for i in r["items"]))
            json.dumps(r, allow_nan=False)

    def test_delayed_block_is_sticky_and_synthetic_is_explicit(self):
        with patch.dict(os.environ, {"GDS_FAKE": "1"}):
            src = GUSBampSource(fs=256, channel_names=posterior.CHANNELS)
        self.assertTrue(src.info()["synthetic"])
        for arrived in (100.0, 101.03125, 100.0625):
            src.frames.put((arrived, np.ones((8, 4))))
            src.read()
        self.assertFalse(src.info()["transport_timing_ok"])
        self.assertEqual(src.info()["max_clock_lag_ms"], 1000)
        self.assertFalse(src.info()["hardware_sample_loss_verified"])

    def test_gusbamp_uniform_time_is_not_proof_of_no_loss(self):
        with tempfile.TemporaryDirectory() as d:
            s = simulate_session(Path(d), {})
            s.meta["source"]["kind"] = "gusbamp"
            s.record_health({"transport_timing_ok": False, "max_clock_lag_ms": 1000})
            s.record_health({"transport_timing_ok": True, "max_clock_lag_ms": 0})
            info = export_session(s.dir, 250, settings.mock_channels)
            self.assertTrue(info["eeg"]["uniform_for_loader"])
            self.assertIsNone(info["eeg"]["lost_samples_est"])
            self.assertIsNone(info["model_input"])
            self.assertTrue(info["eeg"]["recording_health"]["timing_fault"])

    def test_nonfinite_timestamps_fail_closed(self):
        from backend.export import check_eeg
        self.assertFalse(check_eeg(np.array([0.0, np.nan, 0.02]), 100)["uniform_for_loader"])

