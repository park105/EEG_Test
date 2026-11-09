"""Optional stimulus-level permutation diagnostic, separate from trial-level CV.

Assumptions: exchangeable stimuli, equal retained repeats, one binary label per
stimulus, no neutral trials. This is not evidence of preference specificity.
"""
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def _score(x, y, splits):
    predictions = np.empty(len(y), dtype=int)
    for train, test in splits:
        # A permutation may leave a single training class; do not discard it.
        if len(np.unique(y[train])) == 1:
            model = DummyClassifier(strategy="most_frequent")
        else:
            model = make_pipeline(StandardScaler(), LogisticRegression(
                C=1, class_weight="balanced", random_state=0))
        model.fit(x[train], y[train])
        predictions[test] = model.predict(x[test])
    return float(balanced_accuracy_score(y, predictions))


def permutation_check(features, n_permutations=199, seed=42, exchangeable=False):
    if not isinstance(n_permutations, int) or n_permutations < 0:
        raise ValueError("n_permutations must be a nonnegative integer")
    def skip(reason):
        return {"status": "not_run", "reason": reason}
    if n_permutations == 0:
        return skip("Not requested")
    if not exchangeable:
        return skip("Stimulus exchangeability must be justified before permutation inference")
    if features.empty or (features.rating == 3).any():
        return skip("Requires usable data without neutral ratings")
    df = features.copy()
    df["binary_label"] = (df.rating >= 4).astype(int)
    grouped = df.groupby("stimulus_id", sort=True)
    if grouped.binary_label.nunique().max() != 1:
        return skip("Repeated ratings cross the binary boundary; no automatic label collapse")
    if grouped.size().nunique() != 1:
        return skip("Unequal retained repeats; requires a different permutation design")
    cols = [c for c in df if c.startswith("feature_")]
    x = grouped[cols].mean().to_numpy()
    y = grouped.binary_label.first().to_numpy()
    if len(np.unique(y)) != 2 or min(np.bincount(y)) < 3:
        return skip("Requires >=3 stimuli per label")
    if not cols or not np.isfinite(x).all():
        raise ValueError("Finite EEG features required")
    # Label-independent fixed folds, kept unchanged for every permutation.
    ids = np.arange(len(y))
    splits = list(GroupKFold(n_splits=3).split(x, groups=ids))
    observed = _score(x, y, splits)
    rng = np.random.default_rng(seed)
    scores = [_score(x, rng.permutation(y), splits) for _ in range(n_permutations)]
    exceedances = sum(value >= observed for value in scores)
    return {"status": "ok", "method": "stimulus_mean_fixed_groupkfold3_label_permutation",
            "n_stimuli": len(y), "n_permutations": n_permutations,
            "observed_balanced_accuracy": observed,
            "p_value": (1+exceedances)/(1+n_permutations),
            "null_scores": scores, "seed": seed,
            "interpretation": "Exploratory association under stimulus exchangeability; not preference specificity, causal proof, or external validation",
            "separate_statistic": "Averages features per stimulus; different from the trial-level primary score"}
