"""Mentor report pilot: early response, within-person association and held-out prediction."""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.io import loadmat
from scipy.stats import rankdata
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .signal import GetFeature

CHANNELS = "Fp1 AF3 F3 F7 FC5 FC1 C3 T7 CP5 CP1 P3 P7 PO3 O1 Oz Pz Fp2 AF4 Fz F4 F8 FC6 FC2 Cz C4 T8 CP6 CP2 P4 P8 PO4 O2".split()
REGIONS = {"frontal": "F3 Fz F4 F7 F8", "parietal": "P3 Pz P4 P7 P8",
           "temporal": "T7 T8", "occipital": "O1 Oz O2"}


def features(data, labels):
    if data.shape != (40, 40, 8064) or labels.shape != (40, 4):
        raise ValueError("Expected standard DEAP MATLAB layout")
    rows = []
    extract = GetFeature().psd
    for vid, (trial, rating) in enumerate(zip(data, labels), 1):
        row = dict(video=vid, liking=rating[3], quality="ok")
        base, early = trial[:32, :384].T, trial[:32, 384:896].T
        if not 1 <= rating[3] <= 9 or any(not np.isfinite(x).all() or np.any(np.ptp(x, axis=0)==0) for x in (base, early)):
            row["quality"] = "invalid"
        else:
            b, s = (extract(x, 128, CHANNELS) for x in (base, early))
            row.update({k:10*np.log10((s[k]+1e-12)/(b[k]+1e-12)) for k in b})
        rows.append(row)
    return pd.DataFrame(rows)


def participant(frame):
    df = frame.loc[frame.quality=="ok"].reset_index(drop=True)
    if len(df)<10:
        return [], []
    y = df.liking.to_numpy()
    hi, lo = y>5, y<5
    effects, predictions = [], []
    for region, names in REGIONS.items():
        for band in GetFeature.bands:
            x = df[[f"{ch}_{band}" for ch in names.split()]].mean(axis=1).to_numpy()
            rho = np.corrcoef(rankdata(x), rankdata(y))[0,1] if np.ptp(x) and np.ptp(y) else np.nan
            effects.append(dict(region=region, band=band, response_db=x.mean(), rho=rho,
                                high_low_db=x[hi].mean()-x[lo].mean() if min(hi.sum(), lo.sum())>=3 else np.nan,
                                high=int(hi.sum()), low=int(lo.sum())))
    for fold,(tr,te) in enumerate(KFold(5,shuffle=True,random_state=42).split(df)):
        reference = np.median(y[tr])
        for mode,names in {"F3F4":["F3","F4"], "all32":CHANNELS}.items():
            x = df[[f"{c}_{b}" for c in names for b in GetFeature.bands]].to_numpy()
            model = make_pipeline(StandardScaler(), Ridge(alpha=10)).fit(x[tr],y[tr])
            pred = np.clip(model.predict(x[te]),1,9)
            predictions.extend(dict(mode=mode,fold=fold,video=int(df.video[k]),liking=y[k],estimate=v,reference=reference)
                               for k,v in zip(te,pred))
    return effects,predictions


def holm(p):
    p = np.asarray(p)
    idx = np.argsort(p)
    result = np.empty(len(p))
    result[idx] = np.minimum(1,np.maximum.accumulate(p[idx]*(len(p)-np.arange(len(p)))))
    return result


def group_stats(effects):
    rng = np.random.default_rng(42)
    rows = []
    for (region,band), g in effects.groupby(["region","band"]):
        for measure in ["response_db","high_low_db","rho"]:
            v = g[measure].dropna().to_numpy()
            if not len(v):
                continue
            # Fixed video set. Independent participant as the unit of inference.
            signs = rng.choice([-1,1],size=(9999,len(v)))
            p = (1+(np.abs((signs*v).mean(axis=1))>=abs(v.mean())-1e-12).sum())/10000
            rows.append(dict(region=region,band=band,measure=measure,n=len(v),mean=v.mean(),p=p))
    out = pd.DataFrame(rows)
    out["holm_p"] = out.groupby("measure").p.transform(holm)
    return out


def location_band_tests(effects):
    """Test differences directly instead of comparing significant/non-significant cells."""
    wide = effects.pivot(index="participant", columns=["region","band"],values="rho")
    wide = wide.reindex(columns=pd.MultiIndex.from_product([list(REGIONS),list(GetFeature.bands)])).dropna()
    r = wide.to_numpy().reshape(len(wide),len(REGIONS),len(GetFeature.bands))
    grand = r.mean(axis=(1,2),keepdims=True)
    region = r.mean(axis=2,keepdims=True)
    band = r.mean(axis=1,keepdims=True)
    signs = np.random.default_rng(43).choice([-1,1],size=(9999,len(r)))
    rows = []
    for name,vec in [("position",region-grand),("band",band-grand),("interaction",r-region-band+grand)]:
        v = vec.reshape(len(r),-1)
        obs = np.linalg.norm(v.mean(axis=0))
        null = np.linalg.norm(signs @ v /len(v),axis=1)
        rows.append(dict(contrast=name,n=len(r),norm=obs,p=(1+(null>=obs-1e-12).sum())/10000))
    out = pd.DataFrame(rows)
    out["holm_p"] = holm(out.p)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path("outputs/real/report_pilot"))
    args = parser.parse_args()
    frames, effects, preds = [], [], []
    paths = sorted(args.data.glob("s[0-9][0-9].mat"))
    if not paths:
        parser.error("No participant files")
    for path in paths:
        m = loadmat(path,variable_names=["data","labels"])
        df = features(m["data"],m["labels"])
        del m
        df["participant"] = path.stem
        frames.append(df)
        e,p = participant(df)
        effects.extend(dict(participant=path.stem,**r) for r in e)
        preds.extend(dict(participant=path.stem,**r) for r in p)
    frames,effects,preds = pd.concat(frames),pd.DataFrame(effects),pd.DataFrame(preds)
    stats = group_stats(effects)
    contrasts = location_band_tests(effects)
    for col in ["estimate","reference"]:
        preds[col+"_ae"] = (preds[col]-preds.liking).abs()
    mae = preds.groupby(["mode","participant"])[["estimate_ae","reference_ae"]].mean()
    args.out.mkdir(parents=True,exist_ok=True)
    for name,table in [("features",frames),("effects",effects),("group",stats),("contrasts",contrasts),("predictions",preds),("mae",mae.reset_index())]:
        table.to_csv(args.out/(name+".csv"),index=False)
    print(frames.quality.value_counts().to_string())
    print(stats.to_string(index=False))
    print(mae.groupby("mode").mean().to_string())


if __name__ == "__main__":
    main()
