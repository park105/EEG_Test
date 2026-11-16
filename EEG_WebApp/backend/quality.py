"""② 연결 화면의 채널별 신호 품질 판정 (최근 2초 기준).

임계값은 시작점일 뿐이며, 장비와 전극 종류에 맞춰 조정해야 한다.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import welch


def channel_quality(x: np.ndarray, fs: float, channels: list[str]) -> list[dict]:
    if len(x) < fs:  # 1초 미만이면 판단 보류
        return [{"channel": c, "status": "unknown", "message": "데이터 수집 중"} for c in channels]
    out = []
    f, p = welch(x - x.mean(axis=0), fs=fs, nperseg=min(len(x), int(fs)), axis=0)
    band = (f >= 1) & (f < 40)
    line = ((f >= 48) & (f <= 52)) | ((f >= 58) & (f <= 62))
    for j, ch in enumerate(channels):
        sd = float(np.std(x[:, j]))
        peak = float(np.max(np.abs(x[:, j] - np.median(x[:, j]))))
        line_ratio = float(p[line, j].sum() / (p[band, j].sum() + 1e-12)) if line.any() else 0.0
        if sd < 0.5:
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
