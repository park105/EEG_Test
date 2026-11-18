"""g.Pype가 없는 PC에서 장비 없이 g.USBamp 경로를 시험하는 가짜 장비. GDS_FAKE=1일 때만 쓴다.
(g.Pype가 있으면 gusbamp_source가 g.Pype의 gp.Generator를 대신 쓴다.)

16채널 µV 신호(알파 10 Hz + 잡음)를 실제 시간 속도로 약 31 ms 블록마다 넘긴다.
입력 1–3(A1–A3)은 알파를 크게 넣어 O1·Oz·O2 자리 확인 연습에 쓸 수 있게 했다.
"""
from __future__ import annotations

import threading
import time

import numpy as np

SERIAL = "UB-FAKE.01"
_open: set[str] = set()


def connected() -> list[tuple[str, bool]]:
    return [(SERIAL, SERIAL in _open)]


def claim(serial: str) -> None:
    """실제 장비처럼 한 번에 하나만 열린다(g.Pype 대역 경로도 같이 쓴다)."""
    if serial != SERIAL:
        raise RuntimeError(f"장비 {serial}를 찾을 수 없습니다.")
    if serial in _open:
        raise RuntimeError("다른 프로그램이 사용 중입니다.")
    _open.add(serial)


def release(serial: str) -> None:
    _open.discard(serial)


class FakeAmp:
    def __init__(self, serial: str, fs: float, inputs: list[int] | None = None):
        claim(serial)
        self.serial, self.fs = serial, float(fs)
        self.inputs = list(range(16)) if inputs is None else list(inputs)   # 배선한 입력만 내보낸다
        self.scans = max(1, int(fs) // 32)
        self.failure: str | None = None
        self.unplug_after_s: float | None = None   # 시험용: 이 시간이 지나면 USB가 빠진 것처럼 멈춘다
        self.running = threading.Event()
        self.thread: threading.Thread | None = None
        self.rng = np.random.default_rng(3)

    def start(self, callback) -> None:
        self.running.set()
        self.thread = threading.Thread(target=self._run, args=(callback,), daemon=True, name="gusbamp-fake")
        self.thread.start()

    def _run(self, callback) -> None:
        amp = np.where(np.arange(16) < 3, 20.0, 5.0)[self.inputs]
        start, k, n = time.perf_counter(), 0, self.scans
        while self.running.is_set():
            time.sleep(max(0.0, start + (k + n) / self.fs - time.perf_counter()))
            if self.unplug_after_s is not None and time.perf_counter() - start > self.unplug_after_s:
                self.failure = "장비 응답 없음(USB 분리)"
                return
            t = (k + np.arange(n))[:, None] / self.fs
            callback(amp * np.sin(2 * np.pi * 10 * t) + self.rng.normal(0, 4, (n, len(self.inputs))))
            k += n

    def stop(self) -> None:
        self.running.clear()
        if self.thread:
            self.thread.join(timeout=2)
        release(self.serial)
