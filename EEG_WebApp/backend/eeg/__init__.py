"""EEG 입력 소스. 모든 소스는 같은 인터페이스(EEGSource)를 따른다."""
from __future__ import annotations

from .base import EEGSource


def create_source(settings) -> EEGSource:
    kind = settings.source.lower()
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
    raise ValueError(f"알 수 없는 EEG_SOURCE: {settings.source} (mock | brainflow | lsl)")


__all__ = ["EEGSource", "create_source"]
