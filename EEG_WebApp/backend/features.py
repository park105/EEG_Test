"""밴드파워 특징 추출 (전두·중심 채널).

팀 저장소 EEG_Test의 brainficial 패키지가 옆 폴더에 있으면 그 전처리(AnalEEG:
1–40 Hz 필터, 진폭/평탄 검사)와 밴드파워(GetFeature: Welch PSD, theta/alpha/beta)를
그대로 재사용한다. 없으면 같은 규칙의 내장 구현을 쓴다.
"""
from __future__ import annotations

import sys

import numpy as np
from scipy.signal import butter, sosfiltfilt, welch

from .config import settings
from .quality import signal_issue

BANDS = {"theta": (4, 8), "alpha": (8, 13), "beta": (13, 30)}


def _load_brainficial():
    path = settings.brainficial_path
    if (path / "brainficial" / "__init__.py").is_file() and str(path) not in sys.path:
        sys.path.append(str(path))
    try:
        from brainficial.signal import AnalEEG, GetFeature
        return AnalEEG, GetFeature
    except Exception:
        return None


class _LocalAnal:
    def __init__(self, fs: float, artifact_uv: float = 150):
        self.fs, self.artifact_uv = fs, artifact_uv
        self.sos = butter(4, [1, 40], btype="bandpass", fs=fs, output="sos")

    def quality(self, x):
        if np.max(np.abs(x)) > self.artifact_uv or np.max(np.ptp(x, axis=0)) > 2 * self.artifact_uv:
            return "amplitude_artifact"
        if np.any(np.std(x, axis=0) < .05):
            return "flat_channel"
        return "ok"

    def transform(self, x):
        return sosfiltfilt(self.sos, x, axis=0)


class _LocalFeature:
    bands = BANDS

    def psd(self, x, fs, channels):
        f, p = welch(x, fs=fs, nperseg=int(2 * fs), axis=0)
        result = {}
        for band, (lo, hi) in self.bands.items():
            power = p[(f >= lo) & (f < hi)].sum(axis=0) * (f[1] - f[0])
            for channel, value in zip(channels, power):
                result[f"{channel}_{band}"] = float(value)
        return result


_bf = _load_brainficial()
AnalEEG, GetFeature = _bf if _bf else (_LocalAnal, _LocalFeature)
BACKEND = "brainficial (EEG_Test)" if _bf else "built-in"


def _detrend(x):
    return x - x.mean(axis=0)


def trial_features(baseline: np.ndarray, stimulus: np.ndarray, fs: float,
                   channels: list[str]) -> tuple[dict, str]:
    """한 시행의 특징. baseline=고정점 구간, stimulus=자극 구간 (각 [n, ch], uV).

    반환 특징:
      feature_{ch}_{band}_db : 자극/고정점 밴드파워 변화(dB)
      feature_faa            : 전두 알파 비대칭 변화 (ln F4α − ln F3α, 자극 − 고정점)
      feature_caa            : 중심 알파 비대칭 변화 (C4/C3)
    """
    pre, get = AnalEEG(fs), GetFeature()
    issue = signal_issue(baseline) or signal_issue(stimulus)
    if issue:
        return {}, issue
    status = next((r for r in (pre.quality(_detrend(baseline)), pre.quality(_detrend(stimulus))) if r != "ok"), "ok")
    if status != "ok":
        return {}, status
    b = get.psd(pre.transform(baseline), fs, channels)
    s = get.psd(pre.transform(stimulus), fs, channels)
    feats = {f"feature_{k}_db": float(10 * np.log10((s[k] + 1e-12) / (b[k] + 1e-12))) for k in b}
    for name, (left, right) in {"faa": ("F3", "F4"), "caa": ("C3", "C4")}.items():
        if left in channels and right in channels:
            asym_s = np.log(s[f"{right}_alpha"] + 1e-12) - np.log(s[f"{left}_alpha"] + 1e-12)
            asym_b = np.log(b[f"{right}_alpha"] + 1e-12) - np.log(b[f"{left}_alpha"] + 1e-12)
            feats[f"feature_{name}"] = float(asym_s - asym_b)
    if not all(np.isfinite(v) for v in feats.values()):
        return {}, "nonfinite_features"
    return feats, "ok"
