"""Evaluation-only stratification of existing held-out predictions."""
import numpy as np
import pandas as pd


def summarize(raw, out):
    data = raw.dropna(subset=["direct_credit", "ridge_credit"]).copy()
    # DEAP ratings are decimal numbers; avoid misclassifying e.g. 2.999999999999999.
    d = data.rating_delta.abs().round(8)
    masks = {"all": d > 0, "0<gap<=1": (d > 0) & (d <= 1),
             "gap>=2": d >= 2, "gap>=3": d >= 3}
    details = []
    for label, mask in masks.items():
        grouped = data[mask].groupby(["method", "participant"])
        part = grouped.agg(n=("video_a", "size"), direct=("direct_credit", "mean"),
                           ridge=("ridge_credit", "mean")).reset_index()
        details.append(part.assign(group=label))
    people = pd.concat(details, ignore_index=True)
    stats = people.groupby(["method", "group"], sort=False).agg(
        participants=("participant","size"), pairs=("n","sum"),
        direct=("direct","mean"), ridge=("ridge","mean")).reset_index()
    people.to_csv(out/"gap_participants.csv", index=False)
    stats.to_csv(out/"gap_summary.csv", index=False)
    lines = ["# DEAP 평점 차이에 따른 비교", "",
             "모델과 분할은 그대로 두고 미학습 영상 쌍을 실제 평점 차이로 나눴습니다. 동점 제외, 참가자 평균. 2점 이상과 3점 이상은 겹칩니다.",
             "", "| 특징 | 평점 차이 | 인원 | 쌍 | 직접 학습 | 회귀 후 순위 |", "|---|---|---:|---:|---:|---:|"]
    for r in stats.itertuples():
        lines.append(f"| {r.method} | {r.group} | {r.participants} | {r.pairs} | {r.direct:.2%} | {r.ridge:.2%} |")
    for method, rows in people.groupby("method"):
        wide = rows.pivot(index="participant", columns="group", values="direct")
        if {"gap>=3", "0<gap<=1"}.issubset(wide):
            delta = (wide["gap>=3"]-wide["0<gap<=1"]).dropna()
            if len(delta):
                lines.append(f"\n{method}: 양 조건 공통 {len(delta)}명의 (3점 이상 − 1점 이하) 평균 차이는 {100*delta.mean():+.2f}%p. 향상된 사람 {int((delta>0).sum())}명.")
    err = (data.direct_margin+data.reversed_margin).abs().max()
    lines.append(f"\n같은 EEG 입력 순서만 뒤집었을 때 점수 합의 최대 절댓값: {err:.3g}. 절편 없는 차이 모델의 구조적 성질이며 실제 자극 순서 실험은 아닙니다.")
    lines.append("\n평점 차이는 사후에만 알 수 있으므로 큰 차이 쌍의 성능을 전체 예측 성능으로 해석하지 않습니다. 작은 차이가 실제 무차별을 뜻하지도 않습니다.")
    (out/"gap_report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
