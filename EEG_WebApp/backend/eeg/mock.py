"""하드웨어 없이 돌리는 합성(SYNTHETIC) EEG 소스.

- 1/f 비슷한 배경 잡음 + 10 Hz 알파 + 6 Hz 세타 + 약한 베타 + 약한 50 Hz 전원 잡음
- 가끔 전두 채널에 눈 깜박임 형태의 큰 파형
- 자극 중에는 '가상 참가자'의 카테고리 선호에 따라 전두 알파 비대칭(F3/F4)과
  베타를 바꾼다. 데모용 장치일 뿐이며 실제 뇌 반응 법칙을 주장하지 않는다.
"""
from __future__ import annotations

import time

import numpy as np

from .base import EEGSource

# 가상 참가자의 숨은 취향(-1 싫음 ~ +1 좋음). 결과 화면이 비어 보이지 않게 하는 장치.
VIRTUAL_PREFERENCES = {"nature": 0.9, "animal": 0.6, "food": -0.2, "city": -0.8}
LEFT = {"F3", "C3", "AF3", "F7", "FC5", "FC1"}
RIGHT = {"F4", "C4", "AF4", "F8", "FC6", "FC2"}


class MockEEGSource(EEGSource):
    kind = "mock"
    synthetic = True

    def __init__(self, channels: list[str], fs: float = 250, seed: int = 7) -> None:
        super().__init__()
        self.channels = list(channels)
        self.fs = float(fs)
        self.rng = np.random.default_rng(seed)
        self.phase = self.rng.uniform(0, 2 * np.pi, (4, len(self.channels)))
        self.stimulus_category: dict[str, str] = {}
        self.current_pref: float | None = None
        self._t0 = 0.0
        self._produced = 0
        self._ar = np.zeros(len(self.channels))
        self._blink_start = -1.0
        self._blink_until = -1.0
        self._next_blink = 0.0
        self.dropped = False  # 개발용: True면 장비가 끊긴 것처럼 read()가 실패한다

    def set_stimuli(self, stimuli: list[dict]) -> None:
        self.stimulus_category = {s["id"]: s.get("category", "") for s in stimuli}

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._produced = 0
        self._next_blink = self._t0 + self.rng.uniform(5, 15)

    def stop(self) -> None:
        pass

    def now(self) -> float:
        return time.monotonic()

    def on_marker(self, marker: dict) -> None:
        name = marker.get("name")
        if name == "stimulus_onset":
            category = self.stimulus_category.get(marker.get("stimulus_id", ""), "")
            base = VIRTUAL_PREFERENCES.get(category, 0.0)
            self.current_pref = float(np.clip(base + self.rng.normal(0, 0.3), -1, 1))
        elif name in {"stimulus_offset", "recovery_onset", "rating_shown"}:
            self.current_pref = None

    def read(self) -> tuple[np.ndarray, np.ndarray]:
        if self.dropped:
            raise ConnectionError("모의 장비 연결 끊김")
        due = int((time.monotonic() - self._t0) * self.fs) - self._produced
        if due <= 0:
            return np.zeros(0), np.zeros((0, len(self.channels)))
        t = self._t0 + (self._produced + np.arange(due)) / self.fs
        self._produced += due
        return t, self._generate(t)

    def _generate(self, t: np.ndarray) -> np.ndarray:
        n, c = len(t), len(self.channels)
        noise = np.empty((n, c))
        for i in range(n):  # AR(1) 배경 잡음, 청크 사이 상태 유지
            self._ar = 0.96 * self._ar + self.rng.normal(0, 2.2, c)
            noise[i] = self._ar
        alpha_amp = np.full(c, 7.0)
        beta_amp = np.full(c, 1.5)
        pref = self.current_pref
        if pref is not None:
            alpha_amp *= 0.7  # 자극 시 공통 알파 감소
            for j, ch in enumerate(self.channels):
                if ch in LEFT:    # 좋을수록 왼쪽 알파 ↓ (접근 동기 가설 흉내)
                    alpha_amp[j] *= 1 - 0.35 * pref
                elif ch in RIGHT:
                    alpha_amp[j] *= 1 + 0.35 * pref
                if ch.startswith("F"):
                    beta_amp[j] *= 1 + 0.6 * max(pref, 0)
        tt = t[:, None]
        x = (noise
             + alpha_amp * np.sin(2 * np.pi * 10 * tt + self.phase[0])
             + 3.0 * np.sin(2 * np.pi * 6 * tt + self.phase[1])
             + beta_amp * np.sin(2 * np.pi * 20 * tt + self.phase[2])
             + 0.8 * np.sin(2 * np.pi * 50 * tt + self.phase[3]))
        # 가끔 눈 깜박임(전두 채널)
        if t[-1] >= self._next_blink:
            self._blink_until = self._next_blink + 0.3
            self._blink_start = self._next_blink
            self._next_blink += self.rng.uniform(6, 15)
        if self._blink_until > t[0]:
            mask = (t >= self._blink_start) & (t < self._blink_until)
            shape = 70 * np.sin(np.pi * (t[mask] - self._blink_start) / 0.3)
            for j, ch in enumerate(self.channels):
                if ch.startswith("F"):
                    x[mask, j] += shape
        return x
