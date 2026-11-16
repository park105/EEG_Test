"""업로드 모드 예시 파일: 모의(합성) EEG로 eeg.csv + events.csv 한 벌을 만든다.

장비 없이 업로드 흐름을 해 보거나, 파일 형식을 확인하는 용도. 실제 뇌파가 아니다.
  python -m backend.demo  →  data/demo/eeg.csv, data/demo/events.csv
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import settings
from .eeg.mock import MockEEGSource

DEMO_DIR = settings.data_dir.parent / "demo"
PER_CATEGORY = 4


def make_demo(out_dir: Path = DEMO_DIR, seed: int = 11) -> Path:
    out_dir = Path(out_dir)
    if (out_dir / "eeg.csv").exists() and (out_dir / "events.csv").exists():
        return out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stimuli = json.loads((settings.stimuli_dir / "manifest.json").read_text(encoding="utf-8"))["stimuli"]
    rng = np.random.default_rng(seed)
    picks = []
    for cat in sorted({s["category"] for s in stimuli}):
        group = [s for s in stimuli if s["category"] == cat]
        picks += list(rng.choice(group, size=min(PER_CATEGORY, len(group)), replace=False))
    rng.shuffle(picks)

    T = settings.timing
    src = MockEEGSource(settings.mock_channels, settings.mock_fs, seed=seed)
    src.set_stimuli(stimuli)
    fs = src.fs
    chunks, events, n = [], [], 0

    def run(seconds: float) -> None:
        nonlocal n
        k = int(round(seconds * fs))
        t = (n + np.arange(k)) / fs
        chunks.append((t, src._generate(t)))
        n += k

    now = lambda: n / fs  # noqa: E731
    run(T.baseline_s)  # 휴식 기준선
    for i, s in enumerate(picks):
        base = now(); run(T.fixation_s)
        onset = now(); src.on_marker({"name": "stimulus_onset", "stimulus_id": s["id"]})
        pref = src.current_pref
        run(T.stimulus_s)
        offset = now(); src.on_marker({"name": "stimulus_offset"})
        run(T.recovery_s + 2)  # 빈 화면 + 평정 시간
        liking = int(np.clip(round(5 + 3.5 * pref + rng.normal(0, 0.8)), 1, 9))
        events.append({"trial_id": f"T{i:03d}", "stimulus_id": s["id"], "baseline_start_s": round(base, 4),
                       "onset_s": round(onset, 4), "offset_s": round(offset, 4), "rating": liking,
                       "seen_before": int(rng.random() < 0.15)})
    t = np.concatenate([c[0] for c in chunks])
    x = np.concatenate([c[1] for c in chunks])
    eeg = pd.DataFrame(x, columns=src.channels)
    eeg.insert(0, "timestamp_s", t)
    eeg.to_csv(out_dir / "eeg.csv", index=False, float_format="%.3f")
    pd.DataFrame(events).to_csv(out_dir / "events.csv", index=False)
    (out_dir / "README.txt").write_text(
        "모의(합성) EEG 예시 파일입니다. 실제 뇌파가 아닙니다.\n"
        f"eeg.csv: timestamp_s(초) + {len(src.channels)}채널(µV), {fs:g} Hz\n"
        "events.csv: 시행 1개 = 1행. baseline_start_s ≤ onset_s < offset_s, rating 1–9, seen_before 0/1\n",
        encoding="utf-8")
    return out_dir


if __name__ == "__main__":
    print(make_demo())
