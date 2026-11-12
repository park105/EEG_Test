"""Matched nested Ridge comparisons and training-fold coefficient summaries."""
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold, KFold
from threadpoolctl import threadpool_limits

from features import CHANNELS, FOUR
from train import SEED, fit_model, outer_folds, summarize

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "interpretation"
PANELS = {"Frontal": FOUR[:2], "Central": FOUR[2:], "Combined": FOUR, "Full": CHANNELS}
MODES = {"joint": [0, 1], "absolute": [0], "change": [1]}
BANDS = ["theta", "alpha", "beta", "gamma"]
TIMES = ["0-20", "20-40", "40-60"]
KEYS = ["regime", "target", "panel", "mode"]


def run():
    OUT.mkdir(exist_ok=True)
    rows, weights = [], []
    with np.load(ROOT / "results/features.npz") as data:
        raw, ratings = data["x"], data["y"]
        for j, target in enumerate(data["targets"]):
            mask = np.isfinite(ratings[:, j])
            y, person, video = ratings[mask, j], data["subject"][mask], data["video"][mask]
            modes = MODES if target in ("Valence", "Dominance") else ["joint"]
            for panel, channels in PANELS.items():
                signals = raw[mask][:, [CHANNELS.index(c) for c in channels]]
                for mode in modes:
                    x = signals[:, :, :, MODES[mode], :].reshape(len(y), -1)
                    names = list(product(channels, TIMES, MODES[mode], BANDS))
                    for regime in ["within_person", "new_participant"]:
                        count = np.zeros(len(y), dtype=int)
                        unit = video if regime == "within_person" else person
                        for fold, (tr, te) in enumerate(outer_folds(person, regime)):
                            np.testing.assert_equal(np.intersect1d(unit[tr], unit[te]).size, 0)
                            if regime == "within_person":
                                cv = KFold(3, shuffle=True, random_state=SEED).split(tr)
                            else:
                                cv = GroupKFold(3).split(tr, groups=person[tr])
                            splits = list(cv)
                            for a, b in splits:
                                assert not np.intersect1d(unit[tr[a]], unit[tr[b]]).size
                            fit = fit_model("Ridge", x[tr], y[tr], splits).best_estimator_
                            pred = fit.predict(x[te])
                            count[te] += 1
                            prefix = (regime, target, panel, mode)
                            rows.extend((*prefix, fold, s, v, t, p) for s,v,t,p in
                                        zip(person[te], video[te], y[te], pred))
                            if (target in ("Valence", "Dominance") and mode == "joint"
                                    and regime == "within_person"):
                                idx = fit["selectkbest"].get_support(indices=True)
                                for k, coef in zip(idx, fit["ridge"].coef_):
                                    ch, time, power, band = names[k]
                                    weights.append((target, panel, person[tr[0]], fold, ch, time,
                                                    ["absolute", "change"][power], band, coef))
                        np.testing.assert_array_equal(count, np.ones_like(count))
            print(target, "complete", flush=True)
    frame = pd.DataFrame(rows, columns=KEYS + ["fold", "participant", "video", "truth", "prediction"])
    # Verify original predictions and fold membership for the two reference montages.
    old = pd.read_csv(ROOT / "results/predictions.csv").query("model == 'Ridge'").copy()
    old["panel"] = old.montage.map({"4ch": "Combined", "32ch": "Full"})
    keys = ["target", "panel", "regime", "participant", "video", "fold"]
    compare = frame.query("mode == 'joint' and panel in ['Combined','Full']").set_index(keys).sort_index()
    old = old.set_index(keys).sort_index()
    pd.testing.assert_index_equal(old.index, compare.index)
    np.testing.assert_allclose(old[["truth","prediction"]], compare[["truth","prediction"]], atol=1e-10, rtol=0)
    if frame.duplicated(KEYS + ["participant","video"]).any():
        raise ValueError("Duplicate OOF trial")
    frame.to_csv(OUT / "predictions.csv", index=False)
    summarize(frame, KEYS).to_csv(OUT / "metrics.csv", index=False)
    summarize(frame, KEYS + ["participant"]).to_csv(OUT / "participant_metrics.csv", index=False)
    pd.DataFrame(weights, columns=["target","panel","participant","fold","channel","time","power","band","coef"]
                 ).to_csv(OUT / "fold_weights.csv", index=False)
    print(f"Verified {len(compare)} original reference predictions; saved {len(frame)} OOF rows.")


if __name__ == "__main__":
    with threadpool_limits(limits=1):
        run()
