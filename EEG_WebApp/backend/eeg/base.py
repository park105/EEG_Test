"""EEG 소스 인터페이스와 수집 스레드.

핵심 규칙: 자극 마커는 반드시 `source.now()`로 찍는다. 이 시계가 EEG 샘플의
timestamp와 같은 시계이므로, 웹앱 화면 이벤트와 EEG를 같은 시간축에 놓을 수 있다.
"""
from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from typing import Callable

import numpy as np


class EEGSource(ABC):
    kind: str = "base"
    synthetic: bool = False

    def __init__(self) -> None:
        self.channels: list[str] = []
        self.fs: float = 0.0

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def read(self) -> tuple[np.ndarray, np.ndarray]:
        """마지막 호출 이후 새 데이터. (timestamps[n], samples[n, ch] in uV). 블로킹 금지."""

    @abstractmethod
    def now(self) -> float:
        """샘플 timestamp와 같은 시계의 현재 시각(초)."""

    def on_marker(self, marker: dict) -> None:
        """마커 알림. 실제 장비는 무시하고, 모의 소스는 자극 반응을 흉내 낼 때 쓴다."""

    def info(self) -> dict:
        return {"kind": self.kind, "synthetic": self.synthetic,
                "channels": self.channels, "fs": self.fs}


class RingBuffer:
    """최근 N초 데이터(실시간 파형·신호 품질 표시용)."""

    def __init__(self, n_channels: int, capacity: int) -> None:
        self.t = np.zeros(0)
        self.x = np.zeros((0, n_channels))
        self.capacity = capacity
        self.lock = threading.Lock()

    def extend(self, t: np.ndarray, x: np.ndarray) -> None:
        with self.lock:
            self.t = np.concatenate([self.t, t])[-self.capacity:]
            self.x = np.concatenate([self.x, x])[-self.capacity:]

    def last(self, n: int) -> tuple[np.ndarray, np.ndarray]:
        with self.lock:
            return self.t[-n:].copy(), self.x[-n:].copy()


class Acquisition:
    """백그라운드 스레드에서 소스를 계속 읽어 버퍼와 기록기(sink)에 넘긴다."""

    def __init__(self, source: EEGSource, buffer_seconds: float = 10) -> None:
        self.source = source
        self.buffer: RingBuffer | None = None
        self.buffer_seconds = buffer_seconds
        self.sinks: list[Callable[[np.ndarray, np.ndarray], None]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None
        self.sinks_lock = threading.Lock()
        self._last_data: float | None = None  # 마지막으로 샘플이 들어온 때(time.monotonic)

    def start(self) -> None:
        self.source.start()
        self.buffer = RingBuffer(len(self.source.channels), int(self.buffer_seconds * self.source.fs))
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="eeg-acquisition")
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                t, x = self.source.read()
            except Exception as exc:  # 장비 끊김 등은 화면에 보여 준다
                self.error = f"{type(exc).__name__}: {exc}"
                time.sleep(0.5)
                continue
            self.error = None
            if len(t):
                self._last_data = time.monotonic()
                self.buffer.extend(t, x)
                with self.sinks_lock:
                    for sink in list(self.sinks):
                        sink(t, x)
            time.sleep(0.02)

    def data_age(self) -> float:
        """마지막 샘플이 들어온 뒤 지난 시간(초). 아직 한 번도 안 들어왔으면 무한대."""
        return float("inf") if self._last_data is None else time.monotonic() - self._last_data

    def streaming(self, max_age: float = 2.0) -> bool:
        """'연결됨'의 기준: 오류가 없고 최근 max_age초 안에 실제 샘플이 들어왔다."""
        return self.error is None and self.data_age() <= max_age

    def wait_for_data(self, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self._last_data is not None:
                return True
            time.sleep(0.05)
        return self._last_data is not None

    def add_sink(self, sink) -> None:
        with self.sinks_lock:
            if sink not in self.sinks:  # 다시 연결·이어하기로 두 번 불려도 한 번만 기록
                self.sinks.append(sink)

    def remove_sink(self, sink) -> None:
        with self.sinks_lock:
            if sink in self.sinks:
                self.sinks.remove(sink)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.source.stop()
