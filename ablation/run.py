"""Matched gamma and time-window ablations. Run with the BrainFicial Python environment."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_selection import SelectKBest, f_regression
from sklearn.linear_model import Ridge
from sklearn.model_selection import GridSearchCV, GroupKFold, KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
sys.path.insert(0, str(ROOT))
from interpret_eeg import PANELS
from features import CHANNELS
from train import SEED, outer_folds, fit_model

WINDOWS = {"all":[0,1,2], "0-20":[0], "20-40":[1], "40-60":[2], "0-40":[0,1]}
KEY = ["regime","target","panel","gamma","window"]


def fit(x, y, splits):
    if x.shape[1] >= 16:
        return fit_model("Ridge",x,y,splits)
    pipe = make_pipeline(StandardScaler(),SelectKBest(f_regression,k="all"),Ridge())
    return GridSearchCV(pipe, {"ridge__alpha":[10,100]}, cv=splits,
                        scoring="neg_mean_absolute_error",error_score="raise").fit(x,y)


def run():
    blocks = []
    with np.load(ROOT/"results/features.npz") as data:
        raw, labels = data["x"], data["y"]
        subjects, videos = data["subject"], data["video"]
        assert len(set(zip(subjects,videos))) == len(raw) == 1280
        for target in ["Valence","Dominance"]:
            y = labels[:,list(data["targets"]).index(target)]
            assert np.isfinite(y).all()
            for regime in ["within_person","new_participant"]:
                folds = []
                unit = videos if regime=="within_person" else subjects
                for tr,te in outer_folds(subjects,regime):
                    assert not np.intersect1d(unit[tr],unit[te]).size
                    if regime=="within_person":
                        cv = KFold(3,shuffle=True,random_state=SEED).split(tr)
                    else:
                        cv = GroupKFold(3).split(tr,groups=subjects[tr])
                    splits = list(cv)
                    assert all(not np.intersect1d(unit[tr[a]],unit[tr[b]]).size for a,b in splits)
                    folds.append((tr,te,splits))
                np.testing.assert_array_equal(np.sort(np.concatenate([te for _,te,_ in folds])),np.arange(len(y)))
                for panel, channels in PANELS.items():
                    eeg = np.take(raw,[CHANNELS.index(c) for c in channels],axis=1)
                    for window, idx in WINDOWS.items():
                        segment = np.take(eeg,idx,axis=2)
                        for gamma, bands in [("in",4),("out",3)]:
                            x = segment[..., :bands].reshape(len(y),-1)
                            pred, median = np.empty(len(y)), np.empty(len(y))
                            fold_id, alpha = np.empty(len(y),int), np.empty(len(y),int)
                            for n,(tr,te,splits) in enumerate(folds):
                                fitted = fit(x[tr],y[tr],splits)
                                pred[te] = fitted.predict(x[te])
                                median[te] = np.median(y[tr])
                                fold_id[te], alpha[te] = n,fitted.best_params_["ridge__alpha"]
                            blocks.append(pd.DataFrame(dict(regime=regime,target=target,panel=panel,
                                gamma=gamma,window=window,participant=subjects,video=videos,fold=fold_id,
                                alpha=alpha,truth=y,median=median,prediction=pred)))
                    print(target,regime,panel,flush=True)
    df=pd.concat(blocks,ignore_index=True)
    ref=pd.read_csv(ROOT/"interpretation/predictions.csv").query("mode=='joint' and target in ['Valence','Dominance']")
    keys=["regime","target","panel","participant","video","fold"]
    ref=ref.set_index(keys).sort_index()
    full=df.query("gamma=='in' and window=='all'").set_index(keys).sort_index()
    pd.testing.assert_index_equal(full.index,ref.index)
    np.testing.assert_allclose(full[["truth","prediction"]],ref[["truth","prediction"]],rtol=0,atol=1e-10)
    assert np.isfinite(df.prediction).all() and len(df)==204800
    df.to_csv(OUT/"predictions.csv.gz",index=False)
    print("Verified reference predictions:",len(ref))


if __name__=="__main__":
    with threadpool_limits(limits=1):
        run()
