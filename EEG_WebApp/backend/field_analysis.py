"""Within-session camera proxies and frozen EEG regression evaluation for paper surveys."""
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field, FiniteFloat
from scipy.signal import welch
from scipy.stats import spearmanr


def write_json(path, value):
    with NamedTemporaryFile("w", dir=path.parent, encoding="utf8", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
    os.replace(handle.name, path)


class CameraSample(BaseModel):
    phase: Literal["fixation_onset", "stimulus_onset", "stimulus_offset"]
    elapsed_ms: FiniteFloat = Field(ge=0)
    smile: FiniteFloat | None = Field(default=None, ge=0, le=1)
    shoulder: FiniteFloat | None = None


class TrialCapture(BaseModel):
    stimulus_id: str
    camera_enabled: bool
    samples: list[CameraSample] = Field(default_factory=list, max_length=1000)
    live_liking: int | None = Field(default=None, strict=True, ge=1, le=9)


def live_evaluation(directory, result):
    scores = {}
    for item in result["items"]:
        path = directory / f"response_{item['trial_index']}.json"
        if path.exists():
            response = json.loads(path.read_text(encoding="utf8"))
            if response["stimulus_id"] == item["stimulus_id"]:
                scores[item["stimulus_id"]] = response["liking"]
    return evaluate(result, PaperScores(level="photo", scale=9, scores=scores)) if scores else None


def gamma_db(signal, fs):
    # Adapted from research/m1-deap features.power: 2 s Hann, 50% overlap,
    # absolute log power per electrode, then average across the montage.
    if fs < 90 or len(signal) < round(2 * fs) or not np.isfinite(signal).all():
        return None
    n = round(2 * fs)
    freq, psd = welch(signal.T, fs=fs, window="hann", nperseg=n, noverlap=n//2)
    area = psd[:, (freq >= 30) & (freq < 45)].sum(axis=1) * (freq[1]-freq[0])
    return float(np.mean(10*np.log10(np.maximum(area, 1e-12))))


def summarize_capture(directory, index, stimulus_id):
    path = directory / f"capture_{index}.json"
    if not path.is_file():
        return {}
    capture = json.loads(path.read_text(encoding="utf8"))
    if capture["stimulus_id"] != stimulus_id:
        return {}
    rows = capture["samples"]
    summary = {"enabled": capture["camera_enabled"], "frames": len(rows)}
    for key in ("smile", "shoulder"):
        means = {}
        for label, phase in (("base","fixation_onset"), ("photo","stimulus_onset"), ("after","stimulus_offset")):
            values = [r[key] for r in rows if r["phase"] == phase and r[key] is not None]
            summary[f"{key}_{label}_n"] = len(values)
            means[label] = float(np.mean(values)) if values else None
        summary[key+"_delta"] = (means["photo"]-means["base"]
                                 if None not in (means["photo"], means["base"]) else None)
    return summary


def associations(items):
    # Adapted from ablation/check_emg.py. Each paired observation is one
    # photo for one participant. Optical proxies replace the original EMG.
    report = {}
    for key in ("smile_delta", "shoulder_delta"):
        pairs = [(r["gamma_db"], r["camera"][key]) for r in items
                 if r.get("gamma_db") is not None and r.get("camera", {}).get(key) is not None]
        rho = None
        if len(pairs) >= 3:
            a, b = np.array(pairs).T
            if np.ptp(a) and np.ptp(b):
                rho = float(spearmanr(a,b).statistic)
        report[key] = {"n":len(pairs), "rho":rho}
    return report


class PaperScores(BaseModel):
    level: Literal["photo", "category"]
    scale: Literal[5,9] = 9
    scores: dict[str, FiniteFloat]


def evaluate(result, form):
    """서면 점수와 비교. 위쪽 값은 기존 4채널 모델(posterior), by_model에 모델별 결과를 함께 담는다."""
    out = _evaluate(result, form, "posterior_liking")
    out["by_model"] = {"posterior": {k: out[k] for k in ("n", "mae", "rmse", "within_one")}}
    if any(item.get("m1_liking") is not None for item in result["items"]):
        m1 = _evaluate(result, form, "m1_liking")
        out["by_model"]["m1"] = {k: m1[k] for k in ("n", "mae", "rmse", "within_one")}
        for row, other in zip(out["rows"], m1["rows"]):
            row["prediction_m1"], row["error_m1"] = other["prediction"], other["error"]
    return out


def _evaluate(result, form, field):
    groups = {}
    for item in result["items"]:
        key = item["stimulus_id" if form.level == "photo" else "category"]
        if key:
            values = groups.setdefault(key, [])
            if item.get(field) is not None:
                values.append(item[field])
    if not form.scores or not set(form.scores) <= groups.keys():
        raise ValueError("측정한 사진 또는 범주의 점수를 하나 이상 입력하세요.")
    rows = []
    for key, raw in form.scores.items():
        if not 1 <= raw <= form.scale:
            raise ValueError("선택한 척도 범위를 확인하세요.")
        target = 1 + 8*(raw-1)/(form.scale-1)
        pred = float(np.mean(groups[key])) if groups[key] else None
        rows.append(dict(key=key, paper=raw, target=target, prediction=pred,
                         error=None if pred is None else pred-target))
    errors = np.array([r["error"] for r in rows if r["error"] is not None])
    return dict(**form.model_dump(), rows=rows, n=int(errors.size), available=len(groups),
                mae=float(np.abs(errors).mean()) if errors.size else None,
                rmse=float(np.sqrt((errors**2).mean())) if errors.size else None,
                within_one=float((np.abs(errors)<=1).mean()) if errors.size else None)

