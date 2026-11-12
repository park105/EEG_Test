"""Audit held-out rows and replay the saved EEG demos against the OOF table."""
import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from demo import replay
from features import DEFAULT_DATA
from train import outer_folds


def verify(out, cache, root):
    predictions = pd.read_csv(out / "predictions.csv")
    with np.load(cache) as data:
        index = pd.MultiIndex.from_arrays([data["subject"], data["video"]], names=["participant", "video"])
        reference = pd.DataFrame(data["y"], index=index, columns=data["targets"])
    if not reference.index.is_unique or len(reference) != 1280:
        raise ValueError("Expected unique participant-video pairs for 32 x 40 trials")
    for target in predictions.target.unique():
        truth = reference[target].dropna()
        subjects = truth.index.get_level_values("participant").to_numpy()
        for regime in ["within_person", "new_participant"]:
            expected = np.full(len(truth), -1)
            for fold, (_, test) in enumerate(outer_folds(subjects, regime)):
                if (expected[test] != -1).any():
                    raise ValueError("Repeated outer validation trial")
                expected[test] = fold
            if (expected < 0).any():
                raise ValueError("Missing outer validation trial")
            for montage in ["4ch", "32ch"]:
                part = predictions[(predictions.target == target) & (predictions.regime == regime)
                                   & (predictions.montage == montage) & (predictions.model == "Median")]
                actual = part.set_index(["participant", "video"]).reindex(truth.index)
                np.testing.assert_array_equal(actual.fold, expected)
    for (regime, montage, target), part in predictions.groupby(["regime", "montage", "target"]):
        truth = reference[target].dropna().sort_index()
        median = part[part.model == "Median"].set_index(["participant", "video"]).sort_index()
        for model in ["Median", "Ridge", "SVR"]:
            rows = part[part.model == model].set_index(["participant", "video"]).sort_index()
            if not rows.index.equals(truth.index):
                raise ValueError((regime, montage, target, model, "coverage"))
            np.testing.assert_allclose(rows.truth, truth)
            np.testing.assert_array_equal(rows.fold, median.fold)
        median = median.reset_index()
        for fold, test in median.groupby("fold"):
            train = median[median.fold != fold]
            if regime == "within_person":
                assert test.participant.nunique() == 1
                train = train[train.participant == test.participant.iloc[0]]
                assert len(train) == 32 and len(test) == 8
                assert set(train.video).isdisjoint(test.video)
            else:
                assert set(train.participant).isdisjoint(test.participant)
            np.testing.assert_allclose(test.prediction, train.truth.median())
    for target in predictions.target.unique():
        path = out / f"demo_{target}.joblib"
        bundle = joblib.load(path)
        row = predictions.query("regime == 'new_participant' and montage == '4ch' and model == 'Ridge'")
        row = row[(row.target == target) & (row.participant == bundle["subject"]) & (row.video == bundle["video"])]
        assert len(row) == 1
        np.testing.assert_allclose(row.prediction, bundle["prediction"], rtol=0, atol=1e-9)
        replay(path, root)
    print(f"Verified {len(predictions):,} held-out predictions.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("results"))
    parser.add_argument("--cache", type=Path, default=Path("results/features.npz"))
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args()
    verify(args.out, args.cache, args.data)
