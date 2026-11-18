"""g.tec g.USBamp를 웹앱이 직접 연다(LSL·MATLAB 없이). g.tec 공식 Python 라이브러리 g.Pype를 쓴다.

설치(실험실 노트북):  .venv\\Scripts\\python.exe -m pip install "gpype[devices]"
  - g.Pype가 g.USBamp를 g.tec Device Service(GDS)로 연다. GDS(g.NEEDaccess)가 설치·실행 중이어야 한다.
  - g.Pype와 gtec_gds는 g.tec 비상업 라이선스(GNCL): 교육·연구 목적, g.tec 증폭기와 함께 쓰는 것만 허용.
    gtec_gds는 "g.Pype의 일부로만" 쓰게 되어 있어서, 장비는 g.Pype의 gp.GUSBamp 노드로만 연다.
  - 장비는 한 번에 한 프로그램만 열 수 있다. MATLAB·g.Recorder 등을 끄고 연결한다.

g.Pype 개념(https://gpype.gtec.at/content/1_basic_concepts/)에 맞춘 구성. 실시간(realtime) 파이프라인 하나:

    gp.GUSBamp ──→ gp.ChannelSelector(roles=signal) ──→ gp.ChannelLabeler(Montage) ──→ WebAppSink
    (소스: 배선한 입력만 수집)  (트리거·시각 채널 제외)          (전극 이름을 소스 바로 뒤에서)  (싱크: 큐로 넘김)

  - 소스는 배선 화면에서 고른 입력만 장비에서 받는다(channel_selection). 안 쓰는 입력은 아예 수집하지 않는다.
  - 채널 이름은 g.Pype 권장대로 소스 가까이에서 한 번 붙이고(ChannelLabeler), 싱크는 그 이름이 웹앱 배선과
    같은지 setup()에서 확인한다.
  - 싱크의 step()은 g.Pype 스레드에서 프레임마다 불리므로 큐에 넣기만 하고 바로 돌아온다(블로킹 금지).
  - 실행 중 오류(USB 분리 등)는 g.Pype가 파이프라인 상태를 ERROR로 바꾸고 p.failure에 남긴다. read()가 이를 보고
    ConnectionError를 올리면 웹앱의 기존 끊김 처리(재연결 화면)가 그대로 동작한다.
  - 장비 없이 연습(GDS_FAKE=1)할 때는 g.Pype 문서가 하드웨어 대역으로 권하는 gp.Generator를 같은 파이프라인의
    소스 자리에 넣는다. g.Pype가 없는 PC에서는 g.Pype 없이 같은 모양의 신호를 내는 gusbamp_fake를 쓴다.

시각: g.USBamp에는 PC와 공유하는 시계가 없으므로 샘플 번호로 시각을 매긴다. 첫 프레임이 도착한 시각에서
그 프레임 길이를 뺀 값을 0번 샘플 시각으로 잡고, 이후 k번 샘플 = t0 + k/fs. 마커도 같은 time.perf_counter()로
찍는다(독립 실행 g.Pype의 시계와 같다). 도착 시각과의 차이는 info()의 clock_lag_ms로 보인다.
"""
from __future__ import annotations

import os
import queue
import time

import numpy as np

from .base import EEGSource

PREFIX = "gusbamp:"
AUTO = "auto"                         # 시리얼을 모를 때: g.Pype가 비어 있는 g.USBamp 하나를 고른다
RATES = (128, 256, 512, 600, 1200)    # 웹앱에서 고를 수 있는 샘플링 속도(Hz). 8채널 모델은 128·256·512만
N_CHANNELS = 16
WIRES = [{"label": f"{g}{i}", "type": "EEG", "unit": "uV"} for g in "ABCD" for i in range(1, 5)]


def fake() -> bool:
    return os.environ.get("GDS_FAKE") == "1"


def try_gpype():
    try:
        import gpype
    except ImportError:
        return None
    return gpype


def load_gpype():
    gp = try_gpype()
    if gp is None:
        raise RuntimeError('g.Pype가 없습니다. .venv에 pip install "gpype[devices]"로 설치하세요.')
    return gp


def default_fs() -> int:
    fs = int(os.environ.get("GUSBAMP_FS", "256"))
    if fs not in RATES:
        raise ValueError(f"GUSBAMP_FS는 {', '.join(map(str, RATES))} 중 하나여야 합니다.")
    return fs


def _entry(serial: str, in_use: bool = False) -> dict:
    name = "g.USBamp (USB, 비어 있는 장비 자동 선택)" if serial == AUTO else f"g.USBamp {serial}"
    return dict(uid=PREFIX + serial, name=name + (" (다른 프로그램이 사용 중)" if in_use else ""),
                host="USB 직접", fs=default_fs(), in_use=in_use, wires=[dict(w) for w in WIRES])


def devices() -> list[dict]:
    """배선 화면 목록용. lab_setup.streams()의 LSL 항목과 같은 모양으로 돌려준다."""
    if fake():
        from . import gusbamp_fake
        return [_entry(serial, in_use) for serial, in_use in gusbamp_fake.connected()]
    load_gpype()
    try:   # g.Pype가 장비를 자동으로 고를 때 쓰는 목록(사용 중인 장비는 빠짐)
        from gpype.backend.sources.base.favourite import gds_available
        serials = gds_available("DEVICE_TYPE_GUSBAMP")
    except Exception:
        return [_entry(AUTO)]   # 목록을 못 읽으면 연결할 때 g.Pype가 고르게 한다
    return [_entry(s) for s in serials]


_SINK = None


def sink_class():
    """웹앱 싱크 노드(g.Pype INode). g.Pype를 실제로 쓸 때만 만든다(설치 안 된 PC에서도 웹앱은 떠야 하므로)."""
    global _SINK
    if _SINK is None:
        gp = load_gpype()
        from gpype.backend.core.i_port import IPort
        PORT_IN, KEYS = gp.Constants.Defaults.PORT_IN, gp.Constants.Keys

        class WebAppSink(gp.INode):
            """받은 프레임을 웹앱 큐로 넘기는 싱크. 출력 포트가 없다(Collector와 같은 모양)."""

            def __init__(self, deliver=None, expected_labels=None, **kwargs):
                ports = [IPort.Configuration(name=PORT_IN, timing=gp.Constants.Timing.INHERITED)]
                super().__init__(input_ports=kwargs.pop(KEYS.INPUT_PORTS, ports), **kwargs)
                self.deliver = deliver
                self.expected = list(expected_labels or [])

            def setup(self, data, port_context_in):
                labels = list(port_context_in.get(PORT_IN, {}).get(KEYS.CHANNEL_LABELS) or [])
                if self.expected and labels != self.expected:
                    raise ValueError(f"g.Pype 채널 이름 {labels}이 웹앱 배선 {self.expected}과 다릅니다.")
                return super().setup(data, port_context_in)

            def step(self, data):
                frame = data.get(PORT_IN)
                if frame is not None and self.deliver is not None:
                    self.deliver(np.array(frame, dtype=float))   # 복사해서 넘기고 바로 돌아온다
                return {}

        _SINK = WebAppSink
    return _SINK


class GUSBampSource(EEGSource):
    kind = "gusbamp"

    def __init__(self, serial: str = "", fs: float | None = None, layout=None,
                 channel_names: list[str] | None = None) -> None:
        super().__init__()
        if layout is not None:
            serial = layout.uid[len(PREFIX):]
            if len(layout.wires) != N_CHANNELS:
                raise ValueError(f"g.USBamp 입력은 {N_CHANNELS}개입니다. 배선표를 다시 불러오세요.")
            self.inputs = [i for i, w in enumerate(layout.wires) if w.kind != "skip"]
            self.channels = [layout.wires[i].name for i in self.inputs]
        else:
            names = channel_names or [f"CH{i + 1}" for i in range(N_CHANNELS)]
            self.inputs = list(range(min(len(names), N_CHANNELS)))
            self.channels = list(names[:len(self.inputs)])
        self.serial = "" if serial == AUTO else serial
        self.layout = layout
        self.fs = float(fs or default_fs())
        self.pipeline = None      # g.Pype 경로
        self.claimed = None       # 연습용 가짜 장비를 잡고 있으면 그 시리얼
        self.amp = None           # g.Pype 없는 가짜 장비 경로
        self.frames: queue.Queue = queue.Queue()
        self.t0: float | None = None
        self.count = 0
        self.lag = 0.0

    # ---- 정보 ----
    def info(self) -> dict:
        meta = super().info()
        driver = "g.Pype" if self.pipeline is not None else "fake"
        if fake():
            driver += " (가짜 장비)"
        meta.update(serial=self.serial or None, inputs=[WIRES[i]["label"] for i in self.inputs],
                    clock_lag_ms=round(self.lag * 1000, 1),
                    device_clock="샘플 번호 ÷ fs (첫 프레임 도착 기준)", driver=driver)
        if self.layout is not None:
            meta.update(stream_name=f"g.USBamp {self.serial or ''}".strip(),
                        input_layout=self.layout.model_dump(), recorded_unit="uV")
        return meta

    # ---- 수명 주기 ----
    def _deliver(self, frame: np.ndarray) -> None:
        self.frames.put((time.perf_counter(), frame))

    def _source_node(self, gp):
        """파이프라인의 소스 자리. 실제는 gp.GUSBamp, 연습은 g.Pype의 하드웨어 대역 gp.Generator."""
        if fake():
            from . import gusbamp_fake
            self.serial = self.serial or gusbamp_fake.SERIAL
            gusbamp_fake.claim(self.serial)
            self.claimed = self.serial
            return gp.Generator(sampling_rate=self.fs, channel_count=len(self.inputs),
                                frame_size=max(1, int(self.fs) // 32), signal_frequency=10,
                                signal_amplitude=20, noise_amplitude=4)
        return gp.GUSBamp(
            serial=self.serial or None, sampling_rate=int(self.fs),
            channel_selection=self.inputs,            # 배선한 입력만 장비에서 받는다
            enable_trigger=False, enable_counter=False,
            # 네 그룹(A–D)의 REF·GND를 장비 안에서 묶는다: REF·GND 전극을 하나씩만 연결하면 된다.
            common_ground=[True] * 4, common_reference=[True] * 4)

    def start(self) -> None:
        gp = try_gpype()
        if gp is None and fake():
            from . import gusbamp_fake
            self.amp = gusbamp_fake.FakeAmp(self.serial or gusbamp_fake.SERIAL, self.fs, self.inputs)
            self.serial = self.amp.serial
            self.amp.start(self._deliver)
            return
        gp = gp or load_gpype()
        pipeline = gp.Pipeline()
        try:
            source = self._source_node(gp)
            signal = gp.ChannelSelector(roles=gp.Constants.ChannelRoles.SIGNAL)
            labeler = gp.ChannelLabeler(montage=gp.Montage(self.channels))
            pipeline.connect(source, signal)
            pipeline.connect(signal, labeler)
            pipeline.connect(labeler, sink_class()(deliver=self._deliver,
                                                   expected_labels=gp.Montage(self.channels).labels))
            pipeline.start()
        except Exception as exc:
            try:
                pipeline.close()
            except Exception:
                pass
            self._release_fake()
            raise RuntimeError(f"g.USBamp를 열지 못했습니다({exc}). 전원·USB, g.tec Device Service 실행 여부, "
                               "다른 프로그램(MATLAB 등)이 장비를 쓰고 있는지 확인하세요.") from exc
        self.pipeline = pipeline
        config = getattr(source, "config", {}) or {}
        self.serial = str(config.get("serial") or self.serial)

    def stop(self) -> None:
        if self.amp is not None:
            self.amp.stop()
            self.amp = None
        if self.pipeline is not None:
            pipeline, self.pipeline = self.pipeline, None
            try:
                pipeline.stop()
            finally:
                try:
                    pipeline.close()   # 장비 핸들을 놓아 다음 연결·다른 프로그램이 열 수 있게
                except Exception:
                    pass
                self._release_fake()

    def _release_fake(self) -> None:
        if self.claimed:
            from . import gusbamp_fake
            gusbamp_fake.release(self.claimed)
            self.claimed = None

    # ---- 데이터 ----
    def now(self) -> float:
        return time.perf_counter()

    def _failure(self) -> str | None:
        if self.amp is not None:
            return self.amp.failure
        if self.pipeline is None:
            return None
        gp = try_gpype()
        if self.pipeline.get_condition() != gp.Constants.Conditions.ERROR:
            return None
        failure = self.pipeline.failure
        return f"g.Pype 파이프라인 오류: {failure['message'] if failure else '원인 미상'}"

    def read(self):
        failure = self._failure()
        if failure:
            raise ConnectionError(failure)
        stamps, frames = [], []
        while True:
            try:
                arrived, frame = self.frames.get_nowait()
            except queue.Empty:
                break
            n = len(frame)
            if self.t0 is None:
                self.t0 = arrived - n / self.fs
            stamps.append(self.t0 + (self.count + np.arange(n)) / self.fs)
            self.count += n
            self.lag = arrived - (self.t0 + self.count / self.fs)
            frames.append(frame)
        if not frames:
            return np.zeros(0), np.zeros((0, len(self.channels)))
        return np.concatenate(stamps), np.concatenate(frames)
