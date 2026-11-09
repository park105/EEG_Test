"""Stimulus-disjoint out-of-fold evaluation. Ratings and IDs are never predictors."""
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


class CompLike:
    def evaluate(self, features, seed=42):
        if features.empty:
            return {"status": "insufficient_data", "reason": "No usable trials"}, pd.DataFrame()
        df = features.loc[features.rating != 3].reset_index(drop=True)
        y = (df.rating >= 4).astype(int).to_numpy()
        columns = [c for c in df if c.startswith("feature_")]
        groups = df.stimulus_id.astype(str).to_numpy()
        if len(set(y)) != 2 or not columns or any(len(set(groups[y == c])) < 3 for c in [0, 1]):
            return {"status": "insufficient_data", "reason": "Need both labels, each spanning >=3 stimulus IDs"}, pd.DataFrame()
        x = df[columns].to_numpy(float)
        if not np.isfinite(x).all():
            raise ValueError("Nonfinite features")
        splitter = StratifiedGroupKFold(n_splits=3, shuffle=True, random_state=seed)
        splits = list(splitter.split(x, y, groups))
        if any(len(set(y[a])) != 2 or len(set(y[b])) != 2 for a, b in splits):
            return {"status": "insufficient_data", "reason": "A grouped fold lacks a class; collect more diverse stimuli"}, pd.DataFrame()
        prediction = np.zeros(len(y), dtype=int)
        dummy_prediction = prediction.copy()
        fold_ids = prediction.copy()
        folds = []
        for fold, (train, test) in enumerate(splits):
            assert not set(groups[train]) & set(groups[test])
            model = make_pipeline(StandardScaler(), LogisticRegression(C=1, class_weight="balanced", random_state=seed))
            model.fit(x[train], y[train])
            prediction[test] = model.predict(x[test])
            dummy = DummyClassifier(strategy="most_frequent").fit(x[train], y[train])
            dummy_prediction[test] = dummy.predict(x[test])
            fold_ids[test] = fold
            folds.append({"fold": fold, "train_stimuli": sorted(set(groups[train])),
                          "test_stimuli": sorted(set(groups[test])),
                          "balanced_accuracy": float(balanced_accuracy_score(y[test], prediction[test]))})
        pred = df[["trial_id", "stimulus_id", "rating"]].copy()
        pred["label"], pred["prediction"], pred["dummy_prediction"], pred["fold"] = y, prediction, dummy_prediction, fold_ids
        return {"status": "ok", "balanced_accuracy": float(balanced_accuracy_score(y, prediction)),
                "dummy_balanced_accuracy": float(balanced_accuracy_score(y, dummy_prediction)),
                "n_evaluated": len(y), "neutral_excluded": int((features.rating == 3).sum()),
                "feature_columns": columns, "folds": folds,
                "interpretation": "Exploratory within-person/session held-out-stimulus association; no causal or mind-reading claim"}, pred
