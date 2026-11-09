"""DEAP MATLAB import and participant-wise video-held-out preference benchmark."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.io import loadmat
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .signal import GetFeature

FS = 128
CHANNELS = ["F3", "F4"]
INDICES = [2, 19]  # zero-based DEAP preprocessed EEG layout
MODES = ("change", "stimulus")
LABELS = ["valence", "arousal", "dominance", "liking"]


def extract_file(path):
    """One row per video, no synthetic conversion or peripheral channels."""
    mat = loadmat(path, variable_names=["data", "labels"])
    x, labels = mat.get("data"), mat.get("labels")
    if x is None or labels is None or x.shape != (40, 40, 8064) or labels.shape != (40, 4):
        raise ValueError(f"{path.name}: expected standard DEAP MATLAB dimensions")
    extractor = GetFeature()
    rows = []
    for vid, rating in enumerate(labels):
        row = dict(participant=path.stem, video=vid+1, **dict(zip(LABELS, rating)))
        signal = x[vid, INDICES, :].T
        b, s = signal[:3*FS], signal[3*FS:]
        if not np.isfinite(rating[3]) or not 1 <= rating[3] <= 9:
            row["quality"] = "invalid_liking"
        elif not np.isfinite(signal).all() or any(np.any(np.ptp(a, axis=0) == 0) for a in (b, s)):
            row["quality"] = "invalid_eeg"
        else:
            bp, sp = (extractor.psd(a, FS, CHANNELS) for a in (b, s))
            row["quality"] = "ok"
            for k in bp:
                # Shared epsilon in native power units, matching the synthetic pipeline.
                row["change_"+k] = 10*np.log10((sp[k]+1e-12)/(bp[k]+1e-12))
                row["stimulus_"+k] = 10*np.log10(sp[k]+1e-12)
        rows.append(row)
    return pd.DataFrame(rows)


def pair_order(y, estimate):
    """Descriptive concordance within one test fold. Never cross models."""
    i, j = np.triu_indices(len(y), 1)
    actual, predicted = np.sign(y[i]-y[j]), np.sign(estimate[i]-estimate[j])
    valid = actual != 0
    return float(np.sum((actual[valid] == predicted[valid]) + .5*(predicted[valid] == 0))), int(valid.sum())


def evaluate_person(frame, seed=42):
    if frame.participant.nunique() != 1 or frame.video.duplicated().any():
        raise ValueError("Expected one participant and one row per video")
    data = frame.loc[frame.quality == "ok"].sort_values("video").reset_index(drop=True)
    if len(data) < 10:
        return [], []
    y = data.liking.to_numpy()
    splits = list(KFold(5, shuffle=True, random_state=seed).split(data))
    scores, predictions = [], []
    for mode in MODES:
        x = data.filter(regex="^"+mode+"_").to_numpy()
        pred, dummy = np.empty(len(y)), np.empty(len(y))
        wins, n_pairs = 0., 0
        for fold, (train, test) in enumerate(splits):
            model = make_pipeline(StandardScaler(), Ridge(alpha=10))
            model.fit(x[train], y[train])
            pred[test] = np.clip(model.predict(x[test]), 1, 9)
            dummy[test] = np.median(y[train])
            w, n = pair_order(y[test], pred[test])
            wins += w
            n_pairs += n
            for i in test:
                predictions.append(dict(participant=data.participant.iloc[0], video=int(data.video[i]),
                                        method=mode, fold=fold, liking=y[i], prediction=pred[i], reference=dummy[i]))
        mae, ref = np.mean(np.abs(y-pred)), np.mean(np.abs(y-dummy))
        scores.append(dict(participant=data.participant.iloc[0], method=mode, videos=len(y),
                           mae=mae, median_reference_mae=ref, improvement=ref-mae,
                           ranked_pairs=n_pairs, pair_concordance=wins/n_pairs if n_pairs else np.nan))
    return scores, predictions


def run(directory, output, seed=42):
    paths = sorted(Path(directory).glob("s[0-9][0-9].mat"))
    if not paths:
        raise ValueError("No sNN.mat files at the specified directory")
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    trials = pd.concat([extract_file(p) for p in paths], ignore_index=True)
    scores, predictions = [], []
    for _, person in trials.groupby("participant"):
        ss, pp = evaluate_person(person, seed)
        scores.extend(ss)
        predictions.extend(pp)
    scores = pd.DataFrame(scores)
    trials.to_csv(out/"features.csv", index=False)
    scores.to_csv(out/"participants.csv", index=False)
    pd.DataFrame(predictions).to_csv(out/"predictions.csv", index=False)
    summary = dict(source="DEAP preprocessed MATLAB, real EEG", files=[p.name for p in paths], seed=seed,
                   trials=len(trials), quality=trials.quality.value_counts().to_dict(), methods={})
    if not scores.empty:
        for mode, g in scores.groupby("method"):
            summary["methods"][mode] = dict(participants=len(g), mae=g.mae.mean(),
                reference=g.median_reference_mae.mean(), better=int((g.improvement > 0).sum()),
                pair_concordance=g.pair_concordance.mean())
    (out/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    from .deap_report import write_report
    write_report(summary, out)
    print(f"{len(paths)} participants | {len(trials)} trials | {out / 'report.md'}")
