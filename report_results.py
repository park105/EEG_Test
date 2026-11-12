"""Recompute the comparison tables from held-out predictions and check saved scores."""
from pathlib import Path

import numpy as np
import pandas as pd

from train import summarize

RESULTS = Path(__file__).resolve().parent / "results"
TARGETS = ["Valence", "Arousal", "Dominance", "Liking", "Familiarity"]


def checked_scores(rows, keys, filename):
    scores = summarize(rows, keys).set_index(keys).sort_index()
    saved = pd.read_csv(RESULTS / filename).set_index(keys).sort_index()
    pd.testing.assert_index_equal(scores.index, saved.index)
    np.testing.assert_allclose(scores, saved, atol=1e-12, rtol=0, equal_nan=True)
    return scores


def main():
    rows = pd.read_csv(RESULTS / "predictions.csv")
    keys = ["regime", "montage", "target", "model"]
    scores = checked_scores(rows, keys, "metrics.csv")
    people = checked_scores(rows, keys + ["participant"], "participant_metrics.csv")
    assert len(rows) == 75360 and len(scores) == 60
    lines = [
        "# DEAP 실제 데이터 회귀 평가", "",
        "각 칸은 **전체 MAE / 전체 R² / 개선 인원** 순서다. 개선 인원은 같은 조건에서 "
        "참가자의 40개 보류 영상에 대한 MAE가 중앙값 모델보다 엄격히 작은 사람 수다. "
        "굵은 칸은 전체 MAE가 중앙값보다 낮은 EEG 모델이다. 참가자 수는 표준 라벨 32명, "
        "Familiarity 29명이다. 전체 R²는 시행을 합쳐 계산했다.", ""
    ]
    for regime, name in [("within_person", "개인 내 미관측 영상"), ("new_participant", "미관측 참가자")]:
        lines += [f"## {name}", "", "|라벨|중앙값 MAE / R²|4채널 Ridge|32채널 Ridge|4채널 SVR|32채널 SVR|",
                  "|---|---:|---:|---:|---:|---:|"]
        for target in TARGETS:
            baseline = scores.loc[(regime, "4ch", target, "Median")]
            cells = [target, f"{baseline.MAE:.3f} / {baseline.R2:.3f}"]
            for model in ["Ridge", "SVR"]:
                for montage in ["4ch", "32ch"]:
                    group = (regime, montage, target)
                    score = scores.loc[(*group, model)]
                    per = people.loc[group].MAE.unstack("model")
                    better = int((per[model] < per.Median).sum())
                    cell = f"{score.MAE:.3f} / {score.R2:.3f} / {better}명"
                    cells.append(f"**{cell}**" if score.MAE < baseline.MAE else cell)
            lines.append("|" + "|".join(cells) + "|")
        lines += [""]
    lines += ["## 검증 범위", "",
              "- 1,280개 참가자·영상 키로 MATLAB 표준 평점과 CSV를 대조했다. Familiarity는 s02·s15·s23의 결측 120행을 해당 타깃에서만 제외했다.",
              "- 3초 기준선과 20초 구간 세 개를 같은 시행에서 계산해 한 행에 담았다. 입력은 EEG 파워와 기준선 대비 차이며, 다른 평정이나 참가자·영상 ID는 입력 특징에서 제외했다.",
              "- 개인 내 평가에서는 같은 참가자의 영상, 참가자 외 평가에서는 참가자를 단위로 외부 및 내부 분할의 교집합을 검사했다. 스케일링·특징 선택·튜닝은 내부 학습 자료로 수행하고 선택된 파이프라인을 외부 학습 자료에 재적합했다.",
              "- 외부 보류 예측을 원래 시행과 대조하고 중앙값을 각 학습 폴드에서 재계산했다. 전체·개인별 지표를 예측 CSV에서 다시 계산하고 저장값과 대조했다.",
              "- 참가자 외 평가에서는 동일 영상이 다른 참가자의 학습 자료에 포함될 수 있다. 사전 전처리된 DEAP를 사용하므로 배포본 제작 단계의 필터링·아티팩트 제거는 이 검증 범위 밖이다.",
              "- 채널 수와 알고리즘을 같은 외부 결과에서 비교했다. 표에서 가장 작은 오차를 고른 뒤 그 값을 독립적인 최종 모델 성능으로 볼 수는 없다. 개선 인원은 기술통계이며 유의성 검정 결과가 아니다."]
    (RESULTS / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
