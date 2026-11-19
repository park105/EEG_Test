"""research/m1-deap 방식 Liking 회귀를 실험실 4채널(O1·Oz·O2·Pz)과 사진 4초에 맞춘 모델.

원본(park105, research/m1-deap 34914d7)의 features.py·train.py와 같은 것
  - 2초 Hann 창, 50% 겹침 Welch PSD → θ[4,8)·α[8,13)·β[13,30)·γ[30,45) Hz 파워 적분, dB
  - 특징 = 자극 구간 절대 파워(dB) + 자극 − 기준선(dB)
  - StandardScaler → SelectKBest(f_regression, k=16) → Ridge(alpha 10·100 중 내부 검증으로 선택)
바꾼 것
  - 채널: F3·F4·C3·C4 → 실험실 장비의 O1·Oz·O2·Pz
  - 구간: 기준선 3초 + 영상 60초(20초×3) → 기준선 3초 + 사진 첫 4초 1구간
  - 두 데이터(DEAP·실측)에 똑같이 4–45 Hz 대역통과를 먼저 건다(DEAP 전처리 대역과 맞춤)
학습: tools/train_m1_liking.py가 DEAP 32명·1,280시행으로 평가하고 m1_liking.json에 저장한다.
모델 파일은 숫자만 담은 JSON이라 scikit-learn 버전과 상관없이 열린다.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from .quality import signal_issue
from scipy.signal import butter, sosfiltfilt, welch

CHANNELS = ["O1", "Oz", "O2", "Pz"]
BANDS = {"theta": (4, 8), "alpha": (8, 13), "beta": (13, 30), "gamma": (30, 45)}
BASELINE_S, STIMULUS_S = 3.0, 4.0
ARTIFACT_UV = 200.0  # 실측 추론에서 필터 뒤 이 값을 넘는 시행은 계산하지 않는다(눈 깜박임·움직임)
MODEL = Path(__file__).with_name("m1_liking.json")
COLUMNS = [f"m1_{c}_{b}_{k}_db" for c in CHANNELS for k in ("abs", "chg") for b in BANDS]


def bandpass(x: np.ndarray, fs: float) -> np.ndarray:
    """4–45 Hz 4차 버터워스, 양방향. x: [샘플, 채널]."""
    hi = min(45.0, 0.45 * fs)
    sos = butter(4, [4.0, hi], btype="bandpass", fs=fs, output="sos")
    return sosfiltfilt(sos, x, axis=0)


def power(x: np.ndarray, fs: float) -> np.ndarray:
    """[샘플, 채널] → [채널, 밴드] dB. research/m1-deap features.power와 같은 계산(fs만 일반화)."""
    n = int(round(2 * fs))
    freq, psd = welch(x.T, fs=fs, window="hann", nperseg=n, noverlap=n // 2)
    df = freq[1] - freq[0]
    areas = [psd[:, (freq >= lo) & (freq < hi)].sum(axis=1) * df for lo, hi in BANDS.values()]
    return 10 * np.log10(np.maximum(np.stack(areas, axis=1), 1e-12))


def peak_uv(window: np.ndarray) -> float:
    """필터·평균 제거 뒤 창 안의 최대 절대 진폭(µV)."""
    return float(np.max(np.abs(window - window.mean(axis=0))))


def features(base: np.ndarray, stim: np.ndarray, fs: float, filtered: bool = False,
             artifact_uv: float | None = ARTIFACT_UV) -> np.ndarray | None:
    """기준선 3초·자극 4초 [샘플, 4채널](µV) → 32개 특징(COLUMNS 순서). 쓸 수 없는 시행이면 None.
    artifact_uv=None이면 진폭으로 거르지 않는다(DEAP 학습은 원본 m1-deap처럼 전 시행을 쓴다)."""
    nb, ns = int(round(BASELINE_S * fs)), int(round(STIMULUS_S * fs))
    if len(base) < nb or len(stim) < ns:
        return None
    if signal_issue(base[-nb:]) or signal_issue(stim[:ns]):
        return None
    window = np.concatenate([base[-nb:], stim[:ns]])
    if not np.isfinite(window).all() or np.any(np.ptp(window, axis=0) == 0):
        return None
    if not filtered:
        window = bandpass(window - window.mean(axis=0), fs)
    window = window - window.mean(axis=0)
    if artifact_uv is not None and peak_uv(window) > artifact_uv:
        return None
    b, s = power(window[:nb], fs), power(window[nb:], fs)
    # [채널, (절대, 변화), 밴드] 순서로 펼친다 — 원본의 channels × (absolute/change) × bands와 같은 배열
    return np.stack([s, s - b], axis=1).reshape(-1)


def load_model(path: Path | None = None) -> dict | None:
    path = path or MODEL
    if not path.is_file():
        return None
    model = json.loads(path.read_text(encoding="utf-8"))
    if model.get("features") != COLUMNS:
        raise ValueError("m1_liking.json의 특징 목록이 코드와 다릅니다. tools/train_m1_liking.py로 다시 학습하세요.")
    return model


def predict(vector: np.ndarray, model: dict) -> float:
    z = (np.asarray(vector, float) - np.asarray(model["scaler_mean"])) / np.asarray(model["scaler_scale"])
    raw = float(z[model["selected"]] @ np.asarray(model["coef"]) + model["intercept"])
    return float(np.clip(raw, 1, 9))


def predict_session(eeg, trials, fs: float, integrity: dict) -> tuple[dict, str]:
    """반환: ({trial_index: 예측 Liking 1–9}, 화면에 보일 한 줄 메모)."""
    model = load_model()
    if model is None:
        return {}, "모델 파일(m1_liking.json)이 없습니다. tools/train_m1_liking.py로 학습하세요."
    missing = [c for c in CHANNELS if c not in eeg]
    if missing:
        return {}, "필수 채널 누락: " + ", ".join(missing)
    if not integrity.get("model_input"):
        return {}, "EEG 시간축 무결성 검사 실패"
    values = eeg[CHANNELS].to_numpy(float)
    if not np.isfinite(values).all():
        return {}, "EEG에 비어 있는 값이 있습니다."
    # 시행마다 7초만 자르면 필터 가장자리 왜곡이 생기므로 전체 기록을 한 번에 거른 뒤 자른다(학습도 같은 방식)
    raw_values = values
    values = bandpass(values - values.mean(axis=0), fs)
    times = eeg["timestamp_s"].to_numpy()
    scores, rejected = {}, 0
    for tr in trials.itertuples():
        a, b, c = np.searchsorted(times, [tr.fixation_onset, tr.stimulus_onset, tr.stimulus_offset])
        if signal_issue(raw_values[a:b]) or signal_issue(raw_values[b:c]):
            rejected += 1
            continue
        vec = features(values[a:b], values[b:c], fs, filtered=True)
        if vec is None:
            rejected += 1
            continue
        scores[int(tr.trial_index)] = round(predict(vec, model), 3)
    note = f"유효 시행 {len(scores)}/{len(trials)} · 직전 3초 대비 사진 첫 4초"
    if rejected:
        note += f" · 잡음·길이 부족으로 {rejected}개 제외"
    return scores, note


def evaluation_summary() -> dict | None:
    model = load_model()
    return None if model is None else model.get("evaluation")
