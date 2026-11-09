"""Direct within-person ranking; split videos before generating any pairs."""
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler

from .deap import CHANNELS, MODES, evaluate_person
from .signal import GetFeature


def pairs(indices, ratings):
    a, b = np.triu_indices(len(indices), 1)
    a, b = indices[a], indices[b]
    direction = np.sign(ratings[a] - ratings[b])
    return a, b, direction


def evaluate(frame, seed):
    if frame.participant.nunique() != 1 or frame.video.duplicated().any():
        raise ValueError("Expected one participant and one row per video")
    df = frame.loc[frame.quality.eq("ok")].sort_values("video").reset_index(drop=True)
    if len(df) < 10:
        return []
    rating = df.liking.to_numpy()
    _, old = evaluate_person(df, seed)
    old = pd.DataFrame(old).set_index(["method", "fold", "video"])
    rows = []
    for fold, (train, test) in enumerate(KFold(5, shuffle=True, random_state=seed).split(df)):
        a, b, y = pairs(train, rating)
        i, j, target = pairs(test, rating)
        keep = y != 0
        for mode in MODES:
            cols = [f"{mode}_{ch}_{band}" for ch in CHANNELS for band in GetFeature.bands]
            x = df[cols].to_numpy()
            z = StandardScaler().fit(x[train]).transform(x)
            delta = z[a[keep]] - z[b[keep]]
            if len(delta):
                # Include reverse orientation only in training. No intercept makes
                # reversing A/B negate the score. Test each unordered pair once.
                model = LogisticRegression(C=1, fit_intercept=False)
                model.fit(np.vstack([delta, -delta]), np.r_[y[keep], -y[keep]])
                margin = model.decision_function(z[i]-z[j])
                reverse = model.decision_function(z[j]-z[i])
            else:
                margin = np.full(len(i), np.nan)
                reverse = margin.copy()
            pred = old.loc[(mode, fold), "prediction"]
            for first, second, truth, score, swapped in zip(i, j, target, margin, reverse):
                va, vb = int(df.video[first]), int(df.video[second])
                old_margin = pred.loc[va] - pred.loc[vb]
                rows.append(dict(participant=df.participant.iloc[0], fold=fold, method=mode,
                                 video_a=va, video_b=vb, rating_delta=rating[first]-rating[second],
                                 direct_margin=score, reversed_margin=swapped, ridge_margin=old_margin,
                                 direct_credit=credit(score, truth), ridge_credit=credit(old_margin, truth)))
    return rows


def credit(score, truth):
    if truth == 0 or not np.isfinite(score):
        return np.nan
    return .5 if score == 0 else float(np.sign(score) == truth)


def run(features, out, seed=42):
    df = pd.read_csv(features)
    out = Path(out)
    rows = [row for _, person in df.groupby("participant") for row in evaluate(person, seed)]
    if not rows:
        raise ValueError("No evaluable participants")
    raw = pd.DataFrame(rows)
    out.mkdir(parents=True, exist_ok=True)
    raw.to_csv(out/"pairs.csv", index=False)
    # Compare both approaches on exactly the same scored pairs.
    valid = raw.dropna(subset=["direct_credit", "ridge_credit"])
    stats = valid.groupby(["participant", "method"]).agg(
        pairs=("video_a", "count"), direct=("direct_credit", "mean"), ridge=("ridge_credit", "mean"))
    stats.to_csv(out/"participants.csv")
    lines = ["# DEAP · 같은 사람의 두 영상 선호 순서", "",
             "별도로 매긴 liking 평점의 순서를 예측합니다. 직접 받은 A/B 선택 응답이나 실제 전환 실험은 아닙니다.",
             f"개인별 5분할(seed={seed}). 영상을 먼저 나눈 뒤 같은 학습 묶음 또는 같은 평가 묶음 안에서만 쌍을 만들었습니다.",
             "실제 동점은 평가 제외, 예측 동점은 0.5점. 사람별 일치율을 동일 가중 평균합니다.",
             "", "| EEG 특징 | 평가 인원 | 평가 쌍 | 직접 비교 | 평점 예측 후 비교 |", "|---|---:|---:|---:|---:|"]
    for mode, g in stats.groupby(level="method"):
        name = {"change":"기준선 대비 변화", "stimulus":"시청 중 파워"}[mode]
        lines.append(f"| {name} | {len(g)} | {g.pairs.sum()} | {g.direct.mean():.2%} | {g.ridge.mean():.2%} |")
    lines += ["", f"후보 쌍 중 실제 동점: {int((raw.loc[raw.method.eq('change'),'rating_delta']==0).sum())}쌍.",
              "무작위 양자택일의 기대 일치율은 50%입니다. 한 영상이 여러 쌍에 쓰이므로 쌍 개수는 독립 표본 수가 아닙니다. 유의성·다른 세션 재현성은 검증하지 않았습니다."]
    (out/"report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    from .gap_analysis import summarize
    summarize(raw, out)
