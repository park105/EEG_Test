"""Nested evaluation of independent EEG-only regression targets."""
import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_selection import SelectKBest, f_regression
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold, KFold, GridSearchCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR
from threadpoolctl import threadpool_limits

from features import CHANNELS, FOUR, LABELS

SEED = 42


def outer_folds(subject, regime):
    if regime == "new_participant":
        yield from GroupKFold(4).split(subject, groups=subject)
    else:
        for person in np.unique(subject):
            rows = np.flatnonzero(subject == person)
            for a, b in KFold(5, shuffle=True, random_state=SEED).split(rows):
                yield rows[a], rows[b]


def fit_model(name, x, y, splits):
    if name == "Ridge":
        model, grid = Ridge(), {"ridge__alpha": [10, 100]}
    else:
        model, grid = SVR(kernel="rbf"), {"svr__C": [0.3, 3.0]}
    pipe = make_pipeline(StandardScaler(), SelectKBest(f_regression, k=16), model)
    search = GridSearchCV(pipe, grid, cv=splits, scoring="neg_mean_absolute_error", error_score="raise")
    return search.fit(x, y)


def evaluate(x, y, subject, video, regime, montage, target, out):
    records = []
    for fold, (train, test) in enumerate(outer_folds(subject, regime)):
        if regime == "new_participant":
            assert not np.intersect1d(subject[train], subject[test]).size
            inner = GroupKFold(3).split(train, groups=subject[train])
        else:
            assert not np.intersect1d(video[train], video[test]).size
            inner = KFold(3, shuffle=True, random_state=SEED).split(train)
        splits = list(inner)
        unit = subject if regime == "new_participant" else video
        for inner_train, inner_valid in splits:
            if np.intersect1d(unit[train[inner_train]], unit[train[inner_valid]]).size:
                raise ValueError(f"Overlapping inner split in {regime}, fold {fold}")
        np.testing.assert_array_equal(np.sort(np.concatenate([v for _, v in splits])), np.arange(len(train)))
        for name in ["Median", "Ridge", "SVR"]:
            setting = ""
            if name == "Median":
                pred = np.full(len(test), np.median(y[train]))
            else:
                fit = fit_model(name, x[train], y[train], splits)
                pred = fit.predict(x[test])
                setting = str(fit.best_params_)
                if regime == "new_participant" and montage == "4ch" and fold == 0 and name == "Ridge":
                    joblib.dump(dict(model=fit.best_estimator_, target=target, channels=FOUR,
                                     subject=int(subject[test[0]]), video=int(video[test[0]]),
                                     prediction=float(pred[0])), out / f"demo_{target}.joblib")
            records.extend((regime, montage, target, name, fold, setting, s, v, truth, p)
                           for s, v, truth, p in zip(subject[test], video[test], y[test], pred))
    return records


def summarize(frame, keys):
    rows = []
    for key, part in frame.groupby(keys):
        score = r2_score(part.truth, part.prediction) if part.truth.nunique() > 1 else np.nan
        rows.append((*key, len(part), mean_absolute_error(part.truth, part.prediction), score))
    return pd.DataFrame(rows, columns=keys + ["n", "MAE", "R2"])


def train(cache, out, familiarity):
    out.mkdir(exist_ok=True, parents=True)
    records = []
    with np.load(cache) as data:
        targets = LABELS + (["Familiarity"] if familiarity else [])
        for target in targets:
            y = data["y"][:, list(data["targets"]).index(target)]
            mask = np.isfinite(y)
            subject, video = data["subject"][mask], data["video"][mask]
            raw = data["x"][mask]
            for montage, channels in [("4ch", FOUR), ("32ch", CHANNELS)]:
                x = raw[:, [CHANNELS.index(c) for c in channels]].reshape(len(raw), -1)
                for regime in ["within_person", "new_participant"]:
                    records.extend(evaluate(x, y[mask], subject, video, regime, montage, target, out))
            print(target, "complete", flush=True)
    keys = ["regime", "montage", "target", "model"]
    frame = pd.DataFrame(records, columns=keys + ["fold", "setting", "participant", "video", "truth", "prediction"])
    if frame.duplicated(keys + ["participant", "video"]).any() or not np.isfinite(frame.prediction).all():
        raise ValueError("Invalid out-of-fold predictions")
    frame.to_csv(out / "predictions.csv", index=False)
    summarize(frame, keys).to_csv(out / "metrics.csv", index=False)
    summarize(frame, keys + ["participant"]).to_csv(out / "participant_metrics.csv", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path("results/features.npz"))
    parser.add_argument("--out", type=Path, default=Path("results"))
    parser.add_argument("--familiarity", action="store_true")
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        train(args.cache, args.out, args.familiarity)
