"""선호 추정 모델 인터페이스 (자리표시 구현).

로드맵
  1단계(현재) 분류: P(좋아함) 확률을 낸다.
      - FrontalAsymmetryBaseline: 학습 없음. 전두 알파 비대칭(FAA) 변화를 확률로 바꾸는 규칙.
      - PersonalLogistic: ③에서 받은 본인 평정으로 개인 보정. 반드시 out-of-fold로만 예측.
      - PretrainedModel: DEAP 등으로 미리 학습한 모델(joblib)을 끼우는 자리.
  2단계 분류 → 회귀: PreferenceRegressor 인터페이스로 1–9 평점 자체를 예측.

새 모델은 PreferenceModel을 상속해 fit / predict_proba만 구현하면 inference.py에 바로 꽂힌다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
import pandas as pd


class PreferenceModel(ABC):
    name = "base"
    description = ""

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "PreferenceModel":
        return self

    @abstractmethod
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """각 행(시행)에 대해 P(좋아함) ∈ [0, 1]."""


class FrontalAsymmetryBaseline(PreferenceModel):
    """학습 없는 기준 규칙. 세션 안에서 FAA를 표준화해 시그모이드로 변환.

    FAA↑(오른쪽 알파가 상대적으로 큼 = 왼쪽 전두 활성↑)를 '접근/선호' 쪽으로 보는
    문헌 가설을 단순화한 것. 개인차가 크므로 기준선일 뿐 정답이 아니다.
    """
    name = "frontal_asymmetry_baseline"
    description = "전두 알파 비대칭 기반 규칙(학습 없음)"

    def __init__(self, gain: float = 1.5) -> None:
        self.gain = gain

    def predict_proba(self, X):
        col = "feature_faa" if "feature_faa" in X else None
        if col is None:
            return np.full(len(X), 0.5)
        v = X[col].to_numpy(float)
        z = (v - np.nanmean(v)) / (np.nanstd(v) + 1e-9)
        return 1 / (1 + np.exp(-self.gain * z))


class PersonalLogistic(PreferenceModel):
    """본인 평정(좋아요 1–9)으로 학습하는 개인 보정 로지스틱 회귀."""
    name = "personal_logistic"
    description = "본인 평정으로 학습한 개인 보정 로지스틱 회귀(교차검증 예측)"

    def __init__(self, C: float = 0.5) -> None:
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        self.pipe = make_pipeline(StandardScaler(), LogisticRegression(C=C, class_weight="balanced"))

    def fit(self, X, y):
        self.pipe.fit(X.to_numpy(float), y)
        return self

    def predict_proba(self, X):
        return self.pipe.predict_proba(X.to_numpy(float))[:, 1]


class PretrainedModel(PreferenceModel):
    """미리 학습한 sklearn 파이프라인(joblib) 자리. 특징 열 이름이 학습 때와 같아야 한다."""
    name = "pretrained"
    description = "사전 학습 모델(예: DEAP)"

    def __init__(self, path: str | Path) -> None:
        import joblib
        bundle = joblib.load(path)
        self.pipe, self.columns = bundle["model"], bundle["columns"]

    def predict_proba(self, X):
        return self.pipe.predict_proba(X[self.columns].to_numpy(float))[:, 1]


class PreferenceRegressor(ABC):
    """2단계: 1–9 평점 회귀 인터페이스(아직 구현 없음)."""

    @abstractmethod
    def fit(self, X: pd.DataFrame, rating: np.ndarray) -> "PreferenceRegressor": ...

    @abstractmethod
    def predict_rating(self, X: pd.DataFrame) -> np.ndarray: ...


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith("feature_")]


def out_of_fold_personal(X: pd.DataFrame, y: np.ndarray, n_splits: int = 5, seed: int = 0) -> np.ndarray:
    """각 시행의 확률을 그 시행을 뺀 나머지로 학습한 모델로만 예측한다(라벨 누수 방지)."""
    from sklearn.model_selection import StratifiedKFold
    n_splits = int(min(n_splits, np.bincount(y).min()))
    proba = np.full(len(y), np.nan)
    for train, test in StratifiedKFold(n_splits, shuffle=True, random_state=seed).split(X, y):
        proba[test] = PersonalLogistic().fit(X.iloc[train], y[train]).predict_proba(X.iloc[test])
    return proba
