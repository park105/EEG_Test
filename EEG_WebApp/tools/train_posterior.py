"""Train/export a fixed population Ridge and evaluate on unseen videos and participants."""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.posterior import CHANNELS, COLUMNS, MODEL, score


def fit(data):
    x = data[COLUMNS].to_numpy()
    scaler = StandardScaler().fit(x)
    ridge = Ridge(alpha=100).fit(scaler.transform(x), data.liking)
    w = ridge.coef_ / scaler.scale_
    return {"features": COLUMNS, "channels": CHANNELS, "weights": w.tolist(),
            "intercept": float(ridge.intercept_ - scaler.mean_ @ w),
            "target": "DEAP Liking 1-9", "ridge_alpha": 100}


def train(root, output):
    # report_pilot extracted each feature from the original 128-Hz MAT trial.
    raw = pd.read_csv(root / "report_pilot" / "features.csv")
    rename = {c.removeprefix("feature_").removesuffix("_db"): c for c in COLUMNS}
    frame = raw.loc[raw.quality == "ok"].rename(columns=rename)
    frame = frame[["participant", "video", "liking", *COLUMNS]].dropna()
    keys = ["participant", "video"]
    previous = pd.read_csv(root / "eeg_stages" / "predictions.csv")
    common = previous[keys + ["liking", "fold"]].merge(frame, on=keys, validate="1:1", suffixes=("_old", ""))
    np.testing.assert_allclose(common.liking_old, common.liking)
    people = np.sort(common.participant.unique())
    assert len(people) == 29 and len(common) == 1160 and len(frame) == 1280
    result = common[["participant", "video", "liking"]].copy()
    videos = np.arange(1, 41)
    for fold, (a, b) in enumerate(KFold(5, shuffle=True, random_state=42).split(videos), 1):
        train = common[common.video.isin(videos[a])]
        test = common[common.video.isin(videos[b])]
        assert test.fold.eq(fold).all()
        result.loc[test.index, "video_fold"] = fold
        result.loc[test.index, "known"] = score(test[COLUMNS].to_numpy(), fit(train))
        result.loc[test.index, "personal_median"] = test.participant.map(train.groupby("participant").liking.median())
        for pf, (pa, pb) in enumerate(KFold(5, shuffle=True, random_state=43).split(people), 1):
            independent = train[train.participant.isin(people[pa])]
            held = test[test.participant.isin(people[pb])]
            result.loc[held.index, "person_fold"] = pf
            result.loc[held.index, "new"] = score(held[COLUMNS].to_numpy(), fit(independent))
            result.loc[held.index, "group_median"] = independent.liking.median()
    assert result.notna().all().all()
    output.mkdir(parents=True, exist_ok=True)
    result.to_csv(output / "predictions.csv", index=False)
    model = fit(frame.dropna())
    model["training_trials"] = len(frame.dropna())
    MODEL.write_text(json.dumps(model, indent=2), encoding="utf-8")
    print("training trials", model["training_trials"], "evaluation trials", len(result))
    print(result[["known","personal_median","new","group_median"]].sub(result.liking,axis=0).abs().groupby(result.participant).mean().mean())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "evaluation" / "posterior")
    args = parser.parse_args()
    train(args.data, args.out)

