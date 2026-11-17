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
                 channel_names: list[str] | None = None, scale_to_uv: float = 1.0,
                 layout=None) -> None:
        super().__init__()
        import pylsl
        self.pylsl = pylsl
        prop, value = ("name", stream_name) if stream_name else ("type", stream_type)
        if layout:
            prop, value = "uid", layout.uid
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
        self.layout = layout
        self.indices = list(range(n))
        if layout:
            if len(layout.wires) != n or self.fs <= 80:
                raise ValueError("입력 채널 수 또는 샘플링률을 확인하세요 (EEG 필터에 80 Hz 초과 필요).")
            self.indices = [i for i, w in enumerate(layout.wires) if w.kind != "skip"]
            self.channels = [layout.wires[i].name for i in self.indices]
            factors = {"uV": 1., "mV": 1000., "V": 1000000.}
            self.scale = np.array([factors[layout.wires[i].unit] for i in self.indices])

    def info(self):
        meta = super().info()
        if self.layout:
            meta.update(stream_name=self.info_.name(), input_layout=self.layout.model_dump(),
                        recorded_unit="uV")
        return meta

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
        return np.asarray(ts), np.asarray(samples, dtype=float)[:, self.indices] * self.scale
