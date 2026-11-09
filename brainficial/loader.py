"""Strict, explicit interchange format; never guess channel units or clocks."""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd


@dataclass
class Recording:
    time: np.ndarray
    samples: np.ndarray
    channels: list[str]
    fs: float


class EEGLoader:
    def load(self, path: str | Path, fs: float, channels: list[str],
             unit: str = "uV") -> Recording:
        if not np.isfinite(fs) or fs <= 80:
            raise ValueError("fs must exceed 80 Hz for the 1–40 Hz pipeline")
        if unit not in {"uV", "mV", "V"}:
            raise ValueError("Explicit unit required: uV, mV, or V")
        if not channels or len(set(channels)) != len(channels) or "timestamp_s" in channels:
            raise ValueError("Select unique EEG channel names")
        df = pd.read_csv(path)
        if not {"timestamp_s", *channels}.issubset(df.columns):
            raise ValueError("CSV needs timestamp_s and all selected channels")
        a = df[["timestamp_s", *channels]].to_numpy(dtype=float)
        if len(a) < 2 or not np.isfinite(a).all():
            raise ValueError("Empty, short, or nonfinite EEG")
        dt = np.diff(a[:, 0])
        if np.any(dt <= 0) or not np.allclose(dt, 1 / fs, rtol=.02, atol=1e-6):
            raise ValueError("Nonuniform timestamps, dropped samples, or wrong fs; repair explicitly")
        scale = {"uV": 1, "mV": 1000, "V": 1e6}[unit]
        return Recording(a[:, 0], a[:, 1:] * scale, channels, fs)
