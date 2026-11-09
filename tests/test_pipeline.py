import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from brainficial import EEGLoader, CompSig, CompLike, EventLogger, ExperimentRunner, ExperimentTemplate
from brainficial.adapters import CSVDeviceAdapter
from brainficial.synthetic import generate
from brainficial.validation import validate_events
from brainficial.signal import GetFeature


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.eeg, self.events_path = generate(self.root)
        self.rec = EEGLoader().load(self.eeg, 128, ["F3", "F4"])
        self.events = pd.read_csv(self.events_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_pipeline_and_disjoint_groups(self):
        features, quality = CompSig().extract(self.rec, self.events, erp=True)
        self.assertEqual(len(features), 24)
        self.assertTrue(quality.status.eq("ok").all())
        self.assertTrue(any("erp_300_500" in c for c in features))
        metrics, pred = CompLike().evaluate(features)
        self.assertEqual(metrics["status"], "ok")
        self.assertEqual(len(pred), 24)
        self.assertEqual(pred.groupby("stimulus_id").fold.nunique().max(), 1)
        self.assertTrue(all(c.startswith("feature_") for c in metrics["feature_columns"]))
        for fold in metrics["folds"]:
            self.assertFalse(set(fold["train_stimuli"]) & set(fold["test_stimuli"]))
        self.assertGreater(metrics["balanced_accuracy"], .8)  # injected fixture only

    def test_duplicate_timestamp_rejected(self):
        df = pd.read_csv(self.eeg)
        df.loc[1, "timestamp_s"] = df.loc[0, "timestamp_s"]
        df.to_csv(self.eeg, index=False)
        with self.assertRaisesRegex(ValueError, "Nonuniform"):
            EEGLoader().load(self.eeg, 128, ["F3"])

    def test_dropped_sample_rejected(self):
        df = pd.read_csv(self.eeg).drop(index=20)
        df.to_csv(self.eeg, index=False)
        with self.assertRaises(ValueError):
            EEGLoader().load(self.eeg, 128, ["F3"])

    def test_units_and_adapter(self):
        df = pd.read_csv(self.eeg).rename(columns={"timestamp_s": "ms", "F3": "vendor"})
        df["ms"] *= 1000
        df["vendor"] /= 1e6
        source = self.root/"vendor.csv"
        df.to_csv(source, index=False)
        converted = CSVDeviceAdapter(source, "ms", {"vendor": "F3"}, time_scale=.001,
                                     voltage_scale_to_uv=1e6).export(self.root/"converted.csv")
        result = EEGLoader().load(converted, 128, ["F3"])
        np.testing.assert_allclose(result.samples[:, 0], self.rec.samples[:, 0], atol=1e-8)

    def test_invalid_event_orders_ratings_and_coverage(self):
        for column, value in [("offset_s", 3), ("baseline_start_s", -1), ("rating", 6),
                              ("rating", 2.5), ("rating_time_s", 5), ("onset_s", 1.5)]:
            events = self.events.copy()
            events[column] = events[column].astype(float)
            events.loc[0, column] = value
            with self.subTest(column=column, value=value), self.assertRaises(ValueError):
                validate_events(events, self.rec)

    def test_overlap_and_participant_mixing_rejected(self):
        events = self.events.copy()
        events.loc[1, "baseline_start_s"] = 7
        with self.assertRaises(ValueError):
            validate_events(events)
        events = self.events.copy()
        events.loc[1, "participant_id"] = "other"
        with self.assertRaises(ValueError):
            validate_events(events)

    def test_artifact_is_excluded_and_logged(self):
        self.rec.samples[int(4.5*128), 0] = 999
        features, quality = CompSig().extract(self.rec, self.events)
        self.assertEqual(len(features), 23)
        self.assertEqual(quality.iloc[0].status, "amplitude_artifact")

    def test_flatline_and_all_rejected(self):
        self.rec.samples[:] = 0
        features, quality = CompSig().extract(self.rec, self.events)
        metrics, _ = CompLike().evaluate(features)
        self.assertEqual(metrics["status"], "insufficient_data")
        self.assertTrue(quality.status.eq("flat_channel").all())

    def test_missing_class_and_neutral(self):
        features, _ = CompSig().extract(self.rec, self.events)
        features["rating"] = 4
        metrics, _ = CompLike().evaluate(features)
        self.assertEqual(metrics["status"], "insufficient_data")
        features["rating"] = 3
        metrics, _ = CompLike().evaluate(features)
        self.assertEqual(metrics["status"], "insufficient_data")

    def test_trial_local_filtering(self):
        before, _ = CompSig().extract(self.rec, self.events)
        self.rec.samples[self.rec.time >= self.events.iloc[-1].baseline_start_s] *= 2
        after, _ = CompSig().extract(self.rec, self.events)
        cols = [c for c in before if c.startswith("feature_")]
        np.testing.assert_allclose(before.iloc[:-1][cols], after.iloc[:-1][cols])

    def test_generator_repeatable_and_null_has_no_rating_injection(self):
        e2, _ = generate(self.root/"repeat")
        self.assertEqual(self.eeg.read_bytes(), e2.read_bytes())
        null, _ = generate(self.root/"null", null=True)
        self.assertNotEqual(self.eeg.read_bytes(), null.read_bytes())

    def test_runner_records_measured_onset_offset_and_ratings(self):
        class FakePresenter:
            t = 0.
            def blank(self): self.t += .01
            def show(self, stimulus): self.t += .02
            def wait(self, seconds): self.t += seconds
            def rating(self):
                self.t += .5
                return 4
        presenter = FakePresenter()
        path = self.root/"live.csv"
        template = ExperimentTemplate.example()
        template.repeats = 1
        ExperimentRunner(presenter, clock=lambda: presenter.t).run(template, EventLogger(path))
        logged = pd.read_csv(path)
        validate_events(logged)
        self.assertTrue(np.allclose(logged.offset_s-logged.onset_s, 4.01))
        self.assertTrue(logged.rating.eq(4).all())
        self.assertEqual(len(path.with_suffix(".markers.jsonl").read_text().splitlines()), 48)
        with self.assertRaises(FileExistsError):
            EventLogger(path)

    def test_all_templates(self):
        for kind in ["color", "person", "music"]:
            template = ExperimentTemplate.example(kind)
            schedule = template.schedule()
            self.assertEqual(len(schedule), 24)
            self.assertEqual(len({s.stimulus_id for s in schedule}), 12)

    def test_psd_known_sine_power(self):
        t = np.arange(4*128)/128
        x = (10*np.sin(2*np.pi*10*t))[:, None]
        power = GetFeature().psd(x, 128, ["F3"])
        self.assertAlmostEqual(power["F3_alpha"], 50, places=4)
        self.assertLess(power["F3_beta"], 1e-8)

    def test_offset_sample_excluded(self):
        # The exact offset belongs to the post-stimulus period, never the feature.
        before, _ = CompSig().extract(self.rec, self.events)
        self.rec.samples[int(self.events.iloc[0].offset_s*128)] = 9999
        after, _ = CompSig().extract(self.rec, self.events)
        pd.testing.assert_frame_equal(before, after)

    def test_rating_does_not_change_features(self):
        before, _ = CompSig().extract(self.rec, self.events)
        self.events["rating"] = 6-self.events["rating"]
        after, _ = CompSig().extract(self.rec, self.events)
        cols = [c for c in before if c.startswith("feature_")]
        pd.testing.assert_frame_equal(before[cols], after[cols])


if __name__ == "__main__":
    unittest.main()
