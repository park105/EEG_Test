"""Lab Streaming Layer(LSL) 스트림 수신. `pip install pylsl` 필요.

장비 제조사 앱이 LSL로 내보내는 경우(Muse, Emotiv, g.tec, Unicorn 등)에 쓴다.
clocksync 처리로 샘플 timestamp를 이 PC의 pylsl.local_clock() 시계로 맞춘다.
"""
from __future__ import annotations

import numpy as np

from .base import EEGSource


class LSLSource(EEGSource):
    kind = "lsl"

    def __init__(self, stream_type: str = "EEG", stream_name: str = "",
                 channel_names: list[str] | None = None, scale_to_uv: float = 1.0) -> None:
        super().__init__()
        import pylsl
        self.pylsl = pylsl
        prop, value = ("name", stream_name) if stream_name else ("type", stream_type)
        streams = pylsl.resolve_byprop(prop, value, timeout=5)
        if not streams:
            raise RuntimeError(f"LSL 스트림을 찾지 못했습니다 ({prop}={value})")
        self.info_ = streams[0]
        self.fs = float(self.info_.nominal_srate())
        self.inlet = pylsl.StreamInlet(self.info_, processing_flags=pylsl.proc_clocksync | pylsl.proc_dejitter)
        names = channel_names or self._labels()
        n = self.info_.channel_count()
        self.channels = (list(names) + [f"CH{i+1}" for i in range(len(names), n)])[:n]
        self.scale = scale_to_uv

    def _labels(self) -> list[str]:
        labels, ch = [], self.inlet.info().desc().child("channels").child("channel")
        while ch.name() == "channel":
            labels.append(ch.child_value("label"))
            ch = ch.next_sibling()
        return labels

    def start(self) -> None:
        self.inlet.open_stream()

    def stop(self) -> None:
        self.inlet.close_stream()

    def now(self) -> float:
        return self.pylsl.local_clock()

    def read(self):
        samples, ts = self.inlet.pull_chunk(timeout=0.0)
        if not ts:
            return np.zeros(0), np.zeros((0, len(self.channels)))
        return np.asarray(ts), np.asarray(samples, dtype=float) * self.scale
