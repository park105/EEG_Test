"""② 연결 화면의 채널별 신호 품질 판정 (최근 2초 기준).

임계값은 시작점일 뿐이며, 장비와 전극 종류에 맞춰 조정해야 한다.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import welch

MIN_STD_UV = 0.5


def signal_issue(x):
    """Shared minimum eligibility gate, in microvolts before filtering."""
    if x.ndim != 2 or not len(x) or not x.shape[1]:
        return "empty_signal"
    if not np.isfinite(x).all():
        return "nonfinite_signal"
    if np.any(np.std(x, axis=0) < MIN_STD_UV):
        return "flat_channel"
    return None


def channel_quality(x: np.ndarray, fs: float, channels: list[str]) -> list[dict]:
    if len(x) < fs:  # 1초 미만이면 판단 보류
        return [{"channel": c, "status": "unknown", "message": "데이터 수집 중"} for c in channels]
    out = []
    for j, ch in enumerate(channels):
        if not np.isfinite(x[:, j]).all():
            out.append({"channel": ch, "status": "bad", "message": "결측·무한값 포함 — 입력 확인",
                        "std_uv": None, "line_ratio": None})
            continue
        f, p = welch(x[:, j] - x[:, j].mean(), fs=fs, nperseg=min(len(x), int(fs)))
        band = (f >= 1) & (f < 40)
        line = ((f >= 48) & (f <= 52)) | ((f >= 58) & (f <= 62))
        sd = float(np.std(x[:, j]))
        peak = float(np.max(np.abs(x[:, j] - np.median(x[:, j]))))
        line_ratio = float(p[line].sum() / (p[band].sum() + 1e-12)) if line.any() else 0.0
        if sd < MIN_STD_UV:
            status, msg = "bad", "신호 없음(평탄) — 전극 연결 확인"
        elif peak > 200:
            status, msg = "bad", "포화/큰 잡음 — 접촉 불량 또는 움직임"
        elif line_ratio > 1.0:
            status, msg = "bad", "전원 잡음 큼 — 접지·참조 전극 확인"
        elif sd > 50 or line_ratio > 0.3:
            status, msg = "fair", "잡음이 조금 많음"
        else:
            status, msg = "good", "양호"
        out.append({"channel": ch, "status": status, "message": msg,
                    "std_uv": round(sd, 2), "line_ratio": round(line_ratio, 3)})
    return out
