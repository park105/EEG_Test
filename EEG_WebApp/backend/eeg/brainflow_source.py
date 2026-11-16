"""BrainFlow 장비 연결 (OpenBCI, Muse, BrainBit 등). `pip install brainflow` 필요.

BrainFlow timestamp는 유닉스 시간(time.time) 기준이므로 now()도 time.time()을 쓴다.
"""
from __future__ import annotations

import time

import numpy as np

from .base import EEGSource


class BrainFlowSource(EEGSource):
    kind = "brainflow"

    def __init__(self, board_id: int, serial_port: str = "", channel_names: list[str] | None = None,
                 scale_to_uv: float = 1.0) -> None:
        super().__init__()
        from brainflow.board_shim import BoardShim, BrainFlowInputParams
        self.BoardShim = BoardShim
        params = BrainFlowInputParams()
        if serial_port:
            params.serial_port = serial_port
        self.board_id = board_id
        self.synthetic = board_id == -1  # BoardIds.SYNTHETIC_BOARD
        self.board = BoardShim(board_id, params)
        self.eeg_rows = BoardShim.get_eeg_channels(board_id)
        self.ts_row = BoardShim.get_timestamp_channel(board_id)
        self.fs = float(BoardShim.get_sampling_rate(board_id))
        try:
            names = BoardShim.get_eeg_names(board_id)
        except Exception:
            names = []
        if channel_names:
            names = channel_names
        if len(names) < len(self.eeg_rows):
            names = list(names) + [f"CH{i+1}" for i in range(len(names), len(self.eeg_rows))]
        self.channels = list(names[:len(self.eeg_rows)])
        self.scale = scale_to_uv

    def start(self) -> None:
        self.board.prepare_session()
        self.board.start_stream()

    def stop(self) -> None:
        try:
            self.board.stop_stream()
        finally:
            self.board.release_session()

    def now(self) -> float:
        return time.time()

    def read(self):
        data = self.board.get_board_data()
        if data.shape[1] == 0:
            return np.zeros(0), np.zeros((0, len(self.channels)))
        return data[self.ts_row], data[self.eeg_rows].T * self.scale
