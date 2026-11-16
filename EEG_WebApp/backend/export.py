"""측정 종료 시 모델 입력 형식(EEG_Test의 `brainficial.deap_ml apply`)으로 내보내기와 무결성 점검.

세션 폴더에 추가로 만드는 파일
  events.csv      시행 1개 = 1행. apply 명령의 --events 입력.
  eeg_model.csv   (필요할 때만) 시각 간격을 균일하게 다시 매긴 EEG. 원본 eeg.csv가 이미 균일하면 만들지 않음.
  integrity.json  샘플 누락·시각 간격·마커 지연 점검 결과와 apply에 넣을 파일 경로

events.csv에는 일부러 kind / participant_id를 넣지 않는다. 그 열이 모두 있으면 brainficial이
1–5점 실습 형식으로 검증하는데, 웹앱 평정은 DEAP과 같은 1–9점이기 때문이다.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

EVENT_COLUMNS = ["trial_id", "stimulus_id", "baseline_start_s", "onset_s", "offset_s",
                 "rating", "seen_before", "rating_time_s"]
LOADER_RTOL = 0.02  # brainficial EEGLoader가 허용하는 샘플 간격 오차


def build_events(markers: pd.DataFrame, ratings: pd.DataFrame) -> pd.DataFrame:
    m = markers.dropna(subset=["trial_index"])
    rows = []
    for idx, g in m.groupby("trial_index"):
        times = dict(zip(g["name"], g["server_ts"]))
        if not {"fixation_onset", "stimulus_onset", "stimulus_offset"} <= times.keys():
            continue  # 중단된 시행
        rows.append({"trial_index": int(idx), "trial_id": f"T{int(idx):03d}",
                     "stimulus_id": g["stimulus_id"].dropna().iloc[0],
                     "baseline_start_s": times["fixation_onset"], "onset_s": times["stimulus_onset"],
                     "offset_s": times["stimulus_offset"]})
    ev = pd.DataFrame(rows, columns=["trial_index", "trial_id", "stimulus_id", "baseline_start_s", "onset_s", "offset_s"])
    r = ratings.rename(columns={"liking": "rating", "server_ts": "rating_time_s"})
    ev = ev.merge(r[["trial_index", "rating", "seen_before", "rating_time_s"]], on="trial_index", how="left")
    return ev


def check_eeg(t: np.ndarray, fs: float) -> dict:
    dt = np.diff(t)
    expected = 1 / fs
    duration = float(t[-1] - t[0]) if len(t) > 1 else 0.0
    expected_n = int(round(duration * fs)) + 1
    gaps = dt > 1.5 * expected
    lost = int(np.round(np.sum(dt[gaps] / expected - 1))) if gaps.any() else 0
    return {"samples": int(len(t)), "duration_s": round(duration, 2), "fs": fs,
            "expected_samples": expected_n,
            "lost_samples_est": lost, "lost_percent": round(100 * lost / max(expected_n, 1), 3),
            "gaps": int(gaps.sum()), "max_gap_ms": round(float(dt.max() * 1000), 1) if len(dt) else None,
            "nonincreasing": int(np.sum(dt <= 0)),
            "jitter_ms_sd": round(float(np.std(dt) * 1000), 3) if len(dt) else None,
            "uniform_for_loader": bool(len(dt) and np.all(dt > 0) and np.allclose(dt, expected, rtol=LOADER_RTOL, atol=1e-6))}


def marker_latency(markers: pd.DataFrame) -> dict:
    """서버 도착 시각과 브라우저 시각의 차이 분포(같은 시계가 아니므로 '변동'만 의미 있음)."""
    m = markers.dropna(subset=["client_ts_ms"])
    if len(m) < 3:
        return {"status": "insufficient"}
    m = m.sort_values("server_ts")
    diff = (m["server_ts"] * 1000 - m["client_ts_ms"]).to_numpy()
    # 새로고침(이어하기)하면 브라우저 시계가 0부터 다시 시작한다 → 1초 넘게 튀는 곳에서 구간을 나눠 따로 맞춘다
    cuts = np.flatnonzero(np.abs(np.diff(diff)) > 1000) + 1
    diff = np.concatenate([seg - np.median(seg) for seg in np.split(diff, cuts)])
    return {"status": "ok", "n": int(len(m)), "page_reloads": int(len(cuts)), "spread_ms_sd": round(float(np.std(diff)), 2),
            "spread_ms_max": round(float(np.max(np.abs(diff))), 2),
            "note": "마커 전송 지연의 흔들림. 수십 ms 이상이면 소프트웨어 시각을 의심하세요."}


def export_session(session_dir: Path, fs: float, channels: list[str], unit: str = "uV") -> dict:
    session_dir = Path(session_dir)
    eeg = pd.read_csv(session_dir / "eeg.csv")
    markers = pd.read_csv(session_dir / "markers.csv")
    ratings = pd.read_csv(session_dir / "ratings.csv")
    events = build_events(markers, ratings)
    events[EVENT_COLUMNS].to_csv(session_dir / "events.csv", index=False)

    t = eeg["timestamp_s"].to_numpy(float)
    info = check_eeg(t, fs)
    eeg_file = "eeg.csv"
    if not info["uniform_for_loader"]:
        if info["lost_samples_est"] == 0 and info["nonincreasing"] == 0:
            # 누락은 없고 시각만 흔들림(BrainFlow 청크 시각 등) → 선형 적합으로 균일하게 다시 매김
            i = np.arange(len(t))
            slope, intercept = np.polyfit(i, t, 1)
            regular = eeg.copy()
            regular["timestamp_s"] = intercept + i * (1 / fs)
            regular.to_csv(session_dir / "eeg_model.csv", index=False, float_format="%.6f")
            eeg_file = "eeg_model.csv"
            info["regularized"] = {"measured_fs": round(1 / slope, 4),
                                   "max_shift_ms": round(float(np.max(np.abs(regular["timestamp_s"] - t)) * 1000), 2)}
        else:
            eeg_file = None
            info["problem"] = "샘플 누락 또는 시각 역전이 있어 모델 입력으로 바로 쓸 수 없습니다."
    result = {
        "eeg": info, "markers": marker_latency(markers),
        "trials_complete": int(len(events)), "trials_rated": int(events["rating"].notna().sum()),
        "model_input": None if eeg_file is None else {
            "eeg": eeg_file, "events": "events.csv", "fs": fs, "unit": unit, "channels": channels,
            "command": (f"python -m brainficial.deap_ml apply --eeg {eeg_file} --events events.csv "
                        f"--fs {fs:g} --unit {unit} --model <model.joblib> --out model_apply "
                        f"--rating-threshold 6 --low-max 4")},
    }
    (session_dir / "integrity.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
