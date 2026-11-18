"""EEG 입력 소스. 모든 소스는 같은 인터페이스(EEGSource)를 따른다."""
from __future__ import annotations

from .base import EEGSource


def create_source(settings) -> EEGSource:
    kind = settings.source.lower()
    if kind == "none":
        raise RuntimeError("장비가 선택되지 않았어요. 배선 화면(/static/wiring.html)에서 장비를 검색해 고르거나, "
                           "'장비 없이 모의 EEG로 연습'을 누르세요.")
    if kind == "mock":
        from .mock import MockEEGSource
        return MockEEGSource(settings.mock_channels, settings.mock_fs, settings.mock_seed)
    if kind == "brainflow":
        from .brainflow_source import BrainFlowSource
        return BrainFlowSource(settings.brainflow_board_id, settings.brainflow_serial_port,
                               settings.device_channel_names, settings.device_scale_to_uv)
    if kind == "lsl":
        from .lsl_source import LSLSource
        return LSLSource(settings.lsl_stream_type, settings.lsl_stream_name,
                         settings.device_channel_names, settings.device_scale_to_uv)
    if kind == "gusbamp":
        from .gusbamp_source import GUSBampSource
        return GUSBampSource(settings.gusbamp_serial, channel_names=settings.device_channel_names or None)
    raise ValueError(f"알 수 없는 EEG_SOURCE: {settings.source} (none | mock | brainflow | lsl | gusbamp)")


__all__ = ["EEGSource", "create_source"]
