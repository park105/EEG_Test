"""파일 업로드 모드: 이미 기록된 EEG + 이벤트 파일을 받아 장비 측정과 같은 추론을 돌린다.

받는 파일
  EEG     CSV/TSV. 시각 열(timestamp_s, time 등) + 채널 열. 시각 열이 없으면 샘플링 레이트로 만든다.
  이벤트  둘 중 하나
          (가) 모델 입력 형식 events.csv: stimulus_id, onset_s, offset_s [, baseline_start_s, rating, seen_before, trial_id]
          (나) 이 웹앱이 저장한 markers.csv (+ 선택 ratings.csv): 예전 세션을 다시 계산할 때

변환 결과는 장비 세션과 똑같은 폴더 구조(eeg.csv µV, markers.csv, ratings.csv)라서
inference.run · export_session · DEAP 모델 적용을 그대로 쓴다.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

TIME_COLUMNS = ["timestamp_s", "timestamp", "time_s", "time", "times", "t", "seconds", "sec"]
NON_EEG = {"sample", "sample_index", "sample_number", "index", "idx", "trigger", "marker", "markers",
           "event", "events", "label", "annotation", "stim", "status", "counter", "battery", "unnamed: 0"}
EVENT_ALIASES = {
    "stimulus_id": ["stimulus_id", "stimulus", "stim_id", "image_id", "image", "item", "video_id"],
    "onset_s": ["onset_s", "onset", "stimulus_onset", "start_s", "start"],
    "offset_s": ["offset_s", "offset", "stimulus_offset", "end_s", "end"],
    "duration_s": ["duration_s", "duration"],
    "baseline_start_s": ["baseline_start_s", "baseline_start", "fixation_onset", "baseline_s"],
    "rating": ["rating", "liking", "score", "like"],
    "seen_before": ["seen_before", "seen", "familiar", "familiarity"],
    "trial_id": ["trial_id", "trial", "trial_index"],
}
UNIT_TO_UV = {"uV": 1.0, "mV": 1e3, "V": 1e6}
MAX_CHANNELS = 64


class UploadError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 입력 오류."""


# ---------------- 읽기 ----------------
def read_table(path: Path) -> pd.DataFrame:
    raw = Path(path).read_bytes()
    if not raw.strip():
        raise UploadError("빈 파일이에요.")
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise UploadError("글자 인코딩을 읽지 못했어요. UTF-8 CSV로 저장해 주세요.")
    head = text.split("\n", 1)[0]
    sep = max([",", "\t", ";"], key=head.count)
    try:
        df = pd.read_csv(io.StringIO(text), sep=sep)
    except Exception as exc:
        raise UploadError(f"표 형식으로 읽지 못했어요: {exc}")
    df.columns = [str(c).strip() for c in df.columns]
    if df.empty:
        raise UploadError("데이터 행이 없어요.")
    return df


def _find(columns, names) -> str | None:
    lower = {c.lower(): c for c in columns}
    return next((lower[n] for n in names if n in lower), None)


def _seconds(values: np.ndarray) -> tuple[np.ndarray, str]:
    """시각 열 단위 추정: 샘플 간격 중앙값이 0.5 이상이면 ms로 본다(EEG는 초 단위 간격이 0.1 미만)."""
    d = np.diff(values[: min(len(values), 5000)])
    d = d[d > 0]
    if len(d) and np.median(d) >= 0.5:
        return values / 1000.0, "ms"
    return values, "s"


# ---------------- 미리보기(업로드 직후) ----------------
def inspect_eeg(path: Path, feature_channels: list[str]) -> dict:
    df = read_table(path)
    tcol = _find(df.columns, TIME_COLUMNS)
    numeric = [c for c in df.columns if c != tcol and c.lower() not in NON_EEG
               and pd.api.types.is_numeric_dtype(df[c]) and df[c].notna().mean() > 0.9]
    if not numeric:
        raise UploadError("숫자로 된 채널 열을 찾지 못했어요. 첫 줄에 채널 이름이 있어야 해요.")
    warnings = []
    if len(numeric) > MAX_CHANNELS:
        warnings.append(f"채널이 {len(numeric)}개라 앞의 {MAX_CHANNELS}개만 써요.")
        numeric = numeric[:MAX_CHANNELS]
    info = {"rows": int(len(df)), "channels": numeric, "time_column": tcol, "time_unit": None,
            "fs_est": None, "duration_s": None, "t_start": None, "t_end": None}
    if tcol:
        t = pd.to_numeric(df[tcol], errors="coerce").to_numpy(float)
        if np.isnan(t).any():
            raise UploadError(f"시각 열 '{tcol}'에 숫자가 아닌 값이 있어요.")
        t, unit = _seconds(t)
        d = np.diff(t)
        if (d <= 0).any():
            warnings.append(f"시각이 증가하지 않는 곳이 {int((d <= 0).sum())}군데 있어요.")
        med = float(np.median(d[d > 0])) if (d > 0).any() else 0
        info.update(time_unit=unit, fs_est=round(1 / med, 3) if med else None,
                    duration_s=round(float(t[-1] - t[0]), 2), t_start=round(float(t[0]), 6), t_end=round(float(t[-1]), 6))
    else:
        warnings.append("시각 열이 없어요. 샘플링 레이트를 입력하면 0초부터 시각을 만들어요.")
    present = [c for c in feature_channels if c in numeric]
    info["feature_channels_present"] = present
    if not present:
        warnings.append(f"기본 특징 채널({', '.join(feature_channels)})이 없어 모든 채널로 특징을 계산해요.")
    elif "F3" not in present or "F4" not in present:
        warnings.append("F3/F4가 없어 전두 알파 비대칭 특징은 빠져요.")
    amp = float(np.nanmedian(np.abs(df[numeric].to_numpy(float) - df[numeric].median().to_numpy(float))))
    info["unit_guess"] = "V" if amp < 1e-3 else "mV" if amp < 0.5 else "uV"
    info["warnings"] = warnings
    return info


def _event_format(df: pd.DataFrame) -> str:
    cols = {c.lower() for c in df.columns}
    if {"name", "server_ts"} <= cols:
        return "webapp_markers"
    return "events"


def inspect_events(path: Path, known_stimuli: set[str]) -> dict:
    df = read_table(path)
    fmt = _event_format(df)
    if fmt == "webapp_markers":
        names = df["name"].astype(str)
        trials = df.loc[names == "stimulus_onset", "stimulus_id"].astype(str)
        return {"format": fmt, "trials": int(len(trials)), "rated": None,
                "matched_stimuli": int(trials.isin(known_stimuli).sum()), "rating_range": None,
                "has_baseline": bool((names == "baseline_start").any()), "warnings": [],
                "needs_ratings": True}
    ev, warnings = normalize_events(df, fixation_s=3.0, stimulus_s=4.0)
    r = ev["rating"].dropna()
    return {"format": fmt, "trials": int(len(ev)), "rated": int(len(r)),
            "matched_stimuli": int(ev["stimulus_id"].isin(known_stimuli).sum()),
            "rating_range": [float(r.min()), float(r.max())] if len(r) else None,
            "scale_guess": None if not len(r) else "1-5" if r.max() <= 5 else "1-9",
            "time_range": [float(ev["onset_s"].min()), float(ev["offset_s"].max())],
            "warnings": warnings, "needs_ratings": False}


# ---------------- 변환 ----------------
def _truthy(v) -> float:
    if pd.isna(v):
        return np.nan
    s = str(v).strip().lower()
    if s in {"1", "1.0", "true", "t", "y", "yes", "예", "o", "seen"}:
        return 1.0
    if s in {"0", "0.0", "false", "f", "n", "no", "아니오", "x", "new"}:
        return 0.0
    return np.nan


def normalize_events(df: pd.DataFrame, fixation_s: float, stimulus_s: float) -> tuple[pd.DataFrame, list[str]]:
    cols = {k: _find(df.columns, v) for k, v in EVENT_ALIASES.items()}
    missing = [k for k in ("stimulus_id", "onset_s") if not cols[k]]
    if missing:
        raise UploadError("이벤트 파일에 필요한 열이 없어요: " + ", ".join(missing)
                          + " (필수: stimulus_id, onset_s / 권장: offset_s, baseline_start_s, rating)")
    warnings = []
    out = pd.DataFrame({"stimulus_id": df[cols["stimulus_id"]].astype(str).str.strip(),
                        "onset_s": pd.to_numeric(df[cols["onset_s"]], errors="coerce")})
    if cols["offset_s"]:
        out["offset_s"] = pd.to_numeric(df[cols["offset_s"]], errors="coerce")
    elif cols["duration_s"]:
        out["offset_s"] = out["onset_s"] + pd.to_numeric(df[cols["duration_s"]], errors="coerce")
    else:
        out["offset_s"] = out["onset_s"] + stimulus_s
        warnings.append(f"offset_s가 없어 자극 길이를 {stimulus_s:g}초로 봤어요.")
    if cols["baseline_start_s"]:
        out["baseline_start_s"] = pd.to_numeric(df[cols["baseline_start_s"]], errors="coerce")
    else:
        out["baseline_start_s"] = out["onset_s"] - fixation_s
        warnings.append(f"baseline_start_s가 없어 자극 직전 {fixation_s:g}초를 기준 구간으로 써요.")
    out["rating"] = pd.to_numeric(df[cols["rating"]], errors="coerce") if cols["rating"] else np.nan
    out["seen_before"] = df[cols["seen_before"]].map(_truthy) if cols["seen_before"] else np.nan
    if not cols["rating"]:
        warnings.append("rating 열이 없어 본인 평정 비교와 개인 보정 모델은 쓰지 못해요.")
    bad = out[["onset_s", "offset_s", "baseline_start_s"]].isna().any(axis=1)
    if bad.any():
        warnings.append(f"시각이 비어 있는 {int(bad.sum())}개 행은 뺐어요.")
        out = out[~bad]
    flipped = (out["offset_s"] <= out["onset_s"]) | (out["baseline_start_s"] >= out["onset_s"])
    if flipped.any():
        warnings.append(f"구간 순서가 맞지 않는 {int(flipped.sum())}개 행은 뺐어요 (baseline_start < onset < offset).")
        out = out[~flipped]
    if out.empty:
        raise UploadError("쓸 수 있는 시행이 없어요.")
    return out.reset_index(drop=True), warnings


def prepare(session_dir: Path, *, fs: float | None, unit: str, rating_scale: str,
            feature_channels: list[str], fixation_s: float, stimulus_s: float) -> dict:
    """raw_*.csv → eeg.csv(µV) · markers.csv · ratings.csv. 반환: 소스 정보와 경고."""
    session_dir = Path(session_dir)
    if not (session_dir / "raw_eeg.csv").exists():
        raise UploadError("EEG 파일을 먼저 올려 주세요.")
    if not (session_dir / "raw_events.csv").exists():
        raise UploadError("이벤트 파일을 먼저 올려 주세요.")
    if unit not in UNIT_TO_UV:
        raise UploadError(f"단위는 {', '.join(UNIT_TO_UV)} 중 하나여야 해요.")
    warnings: list[str] = []

    # EEG
    info = inspect_eeg(session_dir / "raw_eeg.csv", feature_channels)
    df = read_table(session_dir / "raw_eeg.csv")
    channels = info["channels"]
    if info["time_column"]:
        t, _ = _seconds(pd.to_numeric(df[info["time_column"]], errors="coerce").to_numpy(float))
        fs = float(fs or info["fs_est"] or 0)
    else:
        if not fs:
            raise UploadError("시각 열이 없는 EEG는 샘플링 레이트(Hz)를 꼭 입력해야 해요.")
        t = np.arange(len(df)) / float(fs)
    if not fs or fs <= 0:
        raise UploadError("샘플링 레이트를 알 수 없어요. 직접 입력해 주세요.")
    if info["fs_est"] and abs(info["fs_est"] - fs) / fs > 0.05:
        warnings.append(f"입력한 샘플링 레이트 {fs:g} Hz가 시각 열로 계산한 {info['fs_est']:g} Hz와 달라요.")
    x = df[channels].to_numpy(float) * UNIT_TO_UV[unit]
    if np.isnan(x).any():
        x = pd.DataFrame(x).interpolate(limit_direction="both").to_numpy()
        warnings.append("비어 있는 EEG 값은 앞뒤 값으로 채웠어요.")
    eeg = pd.DataFrame(x, columns=channels)
    eeg.insert(0, "timestamp_s", t)
    eeg.to_csv(session_dir / "eeg.csv", index=False, float_format="%.6f")

    # 이벤트
    raw_ev = read_table(session_dir / "raw_events.csv")
    t0, t1 = float(t[0]), float(t[-1])
    marker_rows = []
    if _event_format(raw_ev) == "webapp_markers":
        m = raw_ev.rename(columns={c: c.lower() for c in raw_ev.columns})
        for col in ("trial_index", "stimulus_id", "client_ts_ms"):
            if col not in m:
                m[col] = np.nan
        m = m[["server_ts", "name", "trial_index", "stimulus_id", "client_ts_ms"]]
        m.to_csv(session_dir / "markers.csv", index=False)
        if (session_dir / "raw_ratings.csv").exists():
            r = read_table(session_dir / "raw_ratings.csv")
            need = {"trial_index", "liking"}
            if not need <= set(r.columns):
                raise UploadError("평정 파일에 trial_index, liking 열이 있어야 해요.")
            for col in ("stimulus_id", "seen_before", "server_ts"):
                if col not in r:
                    r[col] = np.nan
            r[["trial_index", "stimulus_id", "liking", "seen_before", "server_ts"]].to_csv(session_dir / "ratings.csv", index=False)
        else:
            pd.DataFrame(columns=["trial_index", "stimulus_id", "liking", "seen_before", "server_ts"]).to_csv(
                session_dir / "ratings.csv", index=False)
            warnings.append("평정 파일(ratings.csv)이 없어 본인 평정 비교는 빠져요.")
        times = pd.to_numeric(m["server_ts"], errors="coerce")
        n_trials = int((m["name"] == "stimulus_onset").sum())
        inside = float(((times >= t0) & (times <= t1)).mean()) if len(times) else 0
        if inside < 0.5:
            raise UploadError("마커 시각이 EEG 시각 범위를 벗어나요. 같은 세션의 eeg.csv와 markers.csv인지 확인해 주세요.")
        ratings_raw = pd.read_csv(session_dir / "ratings.csv")["liking"]
    else:
        ev, w = normalize_events(raw_ev, fixation_s, stimulus_s)
        warnings += w
        inside = float(((ev["onset_s"] >= t0) & (ev["offset_s"] <= t1)).mean())
        if inside < 0.5 and ev["baseline_start_s"].min() >= -1 and ev["offset_s"].max() <= (t1 - t0) + 1:
            # 이벤트가 '기록 시작부터 몇 초' 기준이면 EEG 첫 시각에 맞춰 옮긴다
            ev[["onset_s", "offset_s", "baseline_start_s"]] += t0
            warnings.append(f"이벤트 시각을 기록 시작 기준으로 보고 EEG 첫 시각({t0:.3f}s)만큼 옮겼어요.")
            inside = float(((ev["onset_s"] >= t0) & (ev["offset_s"] <= t1)).mean())
        if inside == 0:
            raise UploadError(f"이벤트 시각({ev['onset_s'].min():.2f}–{ev['offset_s'].max():.2f}s)이 "
                              f"EEG 기록 범위({t0:.2f}–{t1:.2f}s)와 겹치지 않아요. 같은 시계·같은 단위(초)인지 확인해 주세요.")
        if inside < 1:
            warnings.append(f"EEG 범위를 벗어난 시행 {int(round((1 - inside) * len(ev)))}개는 계산에서 빠져요.")
        scale = rating_scale
        r = ev["rating"].dropna()
        if scale == "auto":
            scale = "1-5" if len(r) and r.max() <= 5 else "1-9"
        if scale == "1-5" and len(r):
            ev["rating"] = 2 * ev["rating"] - 1   # 1→1, 3→5, 5→9: 6 이상 선호 / 4 이하 비선호 기준을 그대로 쓴다
            warnings.append("1–5점 평정을 1–9점으로 바꿔 계산했어요 (2×점수−1).")
        if len(r) and (ev["rating"].dropna().lt(1).any() or ev["rating"].dropna().gt(9).any()):
            raise UploadError("평정이 1–9 범위를 벗어나요. 평정 척도를 확인해 주세요.")
        ratings_rows = []
        for i, e in ev.iterrows():
            for name, ts in (("fixation_onset", e["baseline_start_s"]), ("stimulus_onset", e["onset_s"]),
                             ("stimulus_offset", e["offset_s"])):
                marker_rows.append([f"{ts:.6f}", name, i, e["stimulus_id"], ""])
            if pd.notna(e["rating"]):
                ratings_rows.append([i, e["stimulus_id"], round(float(e["rating"]), 3),
                                     "" if pd.isna(e["seen_before"]) else int(e["seen_before"]), f"{e['offset_s']:.6f}"])
        pd.DataFrame(marker_rows, columns=["server_ts", "name", "trial_index", "stimulus_id", "client_ts_ms"]).to_csv(
            session_dir / "markers.csv", index=False)
        pd.DataFrame(ratings_rows, columns=["trial_index", "stimulus_id", "liking", "seen_before", "server_ts"]).to_csv(
            session_dir / "ratings.csv", index=False)
        n_trials = int(len(ev))
        ratings_raw = ev["rating"]

    meta_path = session_dir / "session.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    source = {"kind": "upload", "fs": fs, "channels": channels, "unit": "uV", "unit_in_file": unit,
              "synthetic": bool(meta.get("demo")), "files": meta.get("files", {})}
    meta.update(source=source, status="prepared", upload_warnings=warnings)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"fs": fs, "channels": channels, "trials": n_trials,
            "rated": int(pd.Series(ratings_raw).notna().sum()), "warnings": warnings}
