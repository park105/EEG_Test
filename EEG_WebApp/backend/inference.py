"""④ 오프라인 추론: 세션이 끝난 뒤 저장된 EEG + 마커 + 평정 + 설문으로 한 번에 계산.

출력(results.json)은 ⑤ 결과 화면이 그대로 그린다.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import deap_model, posterior
from . import field_analysis
from . import features as feat
from .export import export_session, build_trials
from .model import FrontalAsymmetryBaseline, PersonalLogistic, feature_columns, out_of_fold_personal

LIKE_MIN, DISLIKE_MAX = 6, 4          # 1–9 평정: 6 이상 좋아함, 4 이하 싫어함, 5 중립
UNCERTAIN_CONFIDENCE = 0.15           # 이보다 낮으면 EEG 판단 보류
DISCLAIMER = ("EEG 기반 추정입니다. 한 사람·한 세션의 탐색적 결과이며 '진짜 취향'을 판정하지 않습니다. "
              "자극의 밝기·색·친숙함·주의·피로도 결과에 섞일 수 있습니다.")


def _label(score: float | None) -> str:
    if score is None or np.isnan(score):
        return "unknown"
    return "like" if score >= LIKE_MIN else "dislike" if score <= DISLIKE_MAX else "neutral"


def survey_expectation(stimulus: dict, survey_items: list[dict], answers: dict) -> float | None:
    """설문 문항 중 이 자극의 category/tone에 연결된 문항 점수 평균(1–9)."""
    values = []
    for item in survey_items:
        target = item.get("maps_to") or {}
        if any(stimulus.get(k) == v for k, v in target.items()) and item["id"] in answers:
            values.append(float(answers[item["id"]]))
    return float(np.mean(values)) if values else None


def resting_summary(eeg: pd.DataFrame, markers: pd.DataFrame, fs: float, channels: list[str]) -> dict:
    times = dict(zip(markers["name"], markers["server_ts"]))
    if not {"baseline_start", "baseline_end"} <= times.keys():
        return {"status": "missing"}
    t = eeg["timestamp_s"].to_numpy()
    x = eeg[channels].to_numpy(float)[(t >= times["baseline_start"]) & (t < times["baseline_end"])]
    if len(x) < 2 * fs:
        return {"status": "too_short"}
    x = feat.AnalEEG(fs).transform(x - x.mean(axis=0))
    psd = feat.GetFeature().psd(x, fs, channels)
    return {"status": "ok", "seconds": round(len(x) / fs, 1),
            "alpha_uv2": {c: round(psd[f"{c}_alpha"], 3) for c in channels}}


def run(session_dir: Path, stimuli: list[dict], survey_items: list[dict], feature_channels: list[str]) -> dict:
    session_dir = Path(session_dir)
    meta = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    answers = json.loads((session_dir / "survey.json").read_text(encoding="utf-8")) \
        if (session_dir / "survey.json").exists() else {}
    eeg = pd.read_csv(session_dir / "eeg.csv")
    markers = pd.read_csv(session_dir / "markers.csv")
    ratings = pd.read_csv(session_dir / "ratings.csv") if (session_dir / "ratings.csv").exists() \
        else pd.DataFrame(columns=["trial_index", "liking", "seen_before"])
    fs = float(meta["source"]["fs"])
    recorded_layout = meta["source"].get("input_layout")
    if recorded_layout:
        feature_channels = [w["name"] for w in recorded_layout["wires"] if w["kind"] == "EEG"]
    channels = [c for c in feature_channels if c in eeg.columns]
    channel_note = None
    if not channels:
        # 업로드한 데이터의 채널 이름이 다르면(예: Muse TP9/AF7) 기록된 모든 채널로 특징을 계산한다
        channels = [c for c in meta["source"].get("channels", []) if c in eeg.columns] or \
            [c for c in eeg.columns if c != "timestamp_s"]
        channel_note = f"기본 특징 채널({', '.join(feature_channels)})이 없어 기록된 모든 채널을 썼습니다."

    t = eeg["timestamp_s"].to_numpy()
    x_all = eeg[channels].to_numpy(float)
    trials = build_trials(markers)
    rows = []
    for tr in trials.to_dict("records"):
        base = x_all[(t >= tr["fixation_onset"]) & (t < tr["stimulus_onset"])]
        stim = x_all[(t >= tr["stimulus_onset"]) & (t < tr["stimulus_offset"])]
        if min(len(base), len(stim)) < 2 * fs:
            f, status = {}, "short_window"
        else:
            f, status = feat.trial_features(base, stim, fs, channels)
        gamma = None
        if status == "ok" and all(c in eeg for c in posterior.CHANNELS):
            photo = (t >= tr["stimulus_onset"]) & (t < tr["stimulus_offset"])
            gamma = field_analysis.gamma_db(eeg.loc[photo, posterior.CHANNELS].to_numpy(float), fs)
        rows.append({**tr, "quality": status, "gamma_db": gamma, **f})
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("완료된 시행이 없습니다.")
    df = df.merge(ratings[["trial_index", "liking", "seen_before"]], on="trial_index", how="left")

    usable = df[df["quality"] == "ok"].copy()
    cols = feature_columns(usable)
    usable[cols] = usable[cols].fillna(0.0)
    y_label = usable["liking"].map(lambda r: _label(r) if pd.notna(r) else "unknown")
    labeled = usable[y_label.isin(["like", "dislike"])]
    y = (y_label[labeled.index] == "like").astype(int).to_numpy()

    proba = pd.Series(np.nan, index=usable.index)
    eval_info: dict = {}
    integrity = export_session(session_dir, fs, list(meta["source"]["channels"]), "uV")
    liking_scores, liking_note = posterior.predict_session(eeg, trials, fs, integrity)
    deap, deap_note = deap_model.apply(session_dir, integrity["model_input"])
    if deap is not None:
        model_name, model_desc = "deap_ensemble", "DEAP 사전학습 앙상블(EEG_Test deap_ml)"
        trial_ids = df["trial_index"].map(lambda i: f"T{int(i):03d}")
        proba = pd.Series([deap["proba"].get(tid, np.nan) for tid in trial_ids], index=df.index)
        res = deap["result"]
        ens = (res.get("metrics") or {}).get("ensemble") or {}
        eval_info = {"model_path": deap["path"], "model_channels": res.get("channels"),
                     "model_window": res.get("window"), "n_labeled": res.get("labelled_trials"),
                     "note": "DEAP으로 학습한 모델을 이 기록에 적용했습니다. 특징은 이 기록 안에서 표준화했습니다."}
        if ens.get("balanced_accuracy") is not None:
            eval_info["balanced_accuracy_vs_rating"] = round(float(ens["balanced_accuracy"]), 3)
            eval_info["auc_vs_rating"] = None if ens.get("auc") is None else round(float(ens["auc"]), 3)
            eval_info["chance"] = 0.5
    elif len(y) and np.bincount(y, minlength=2).min() >= 3:
        model_name, model_desc = PersonalLogistic.name, PersonalLogistic.description
        proba[labeled.index] = out_of_fold_personal(labeled[cols], y)
        rest = usable.index.difference(labeled.index)
        if len(rest):
            proba[rest] = PersonalLogistic().fit(labeled[cols], y).predict_proba(usable.loc[rest, cols])
        pred = (proba[labeled.index].to_numpy() >= 0.5).astype(int)
        from sklearn.metrics import balanced_accuracy_score
        eval_info = {"balanced_accuracy_vs_rating": round(float(balanced_accuracy_score(y, pred)), 3),
                     "n_labeled": int(len(y)), "chance": 0.5,
                     "note": "본인 평정 대비 교차검증 정확도. 자극 수가 적어 우연 변동이 큽니다."}
    else:
        model = FrontalAsymmetryBaseline()
        model_name, model_desc = model.name, model.description
        if len(usable):
            proba[usable.index] = model.predict_proba(usable[cols] if cols else usable)
        eval_info = {"note": "좋아함/싫어함 평정이 각각 3개 이상이 아니어서 개인 보정 없이 기준 규칙을 썼습니다."}
    if deap is None:
        eval_info["deap_skipped"] = deap_note
    if channel_note:
        eval_info["channel_note"] = channel_note

    by_id = {s["id"]: s for s in stimuli}
    items, counts = [], {"agree": 0, "disagree": 0, "undecided": 0}
    rating_counts = {"agree": 0, "disagree": 0, "undecided": 0}
    for i, r in df.iterrows():
        stim = by_id.get(r["stimulus_id"], {"id": r["stimulus_id"]})
        p = float(proba.get(i, np.nan)) if r["quality"] == "ok" else np.nan
        conf = float(abs(p - 0.5) * 2) if not np.isnan(p) else None
        if conf is None:
            eeg_label = "unavailable"
        elif conf < UNCERTAIN_CONFIDENCE:
            eeg_label = "uncertain"
        else:
            eeg_label = "like" if p >= 0.5 else "dislike"
        expected = survey_expectation(stim, survey_items, answers)
        survey_label = _label(expected) if expected is not None else "unknown"
        if eeg_label in {"like", "dislike"} and survey_label in {"like", "dislike"}:
            agreement = "agree" if eeg_label == survey_label else "disagree"
        else:
            agreement = "undecided"
        counts[agreement] += 1
        rating = None if pd.isna(r.get("liking")) else float(r["liking"])
        if rating is not None and rating.is_integer():
            rating = int(rating)
        rating_label = _label(rating) if rating is not None else "unknown"
        if eeg_label in {"like", "dislike"} and rating_label in {"like", "dislike"}:
            rating_agreement = "agree" if eeg_label == rating_label else "disagree"
        else:
            rating_agreement = "undecided"
        rating_counts[rating_agreement] += 1
        items.append({
            "trial_index": int(r["trial_index"]), "stimulus_id": r["stimulus_id"],
            "title": stim.get("title", r["stimulus_id"]), "src": stim.get("src"),
            "category": stim.get("category"), "tone": stim.get("tone"),
            "quality": r["quality"],
            "posterior_liking": liking_scores.get(r["trial_index"]),
            "gamma_db": float(r.gamma_db) if integrity["model_input"] and pd.notna(r.gamma_db) else None,
            "camera": field_analysis.summarize_capture(session_dir, int(r.trial_index), r.stimulus_id),
            "eeg_like_probability": None if np.isnan(p) else round(p, 3),
            "confidence": None if conf is None else round(conf, 3),
            "eeg_label": eeg_label,
            "survey_expected": None if expected is None else round(expected, 2),
            "survey_label": survey_label,
            "rating": rating, "rating_label": rating_label, "rating_agreement": rating_agreement,
            "seen_before": None if pd.isna(r.get("seen_before")) else bool(r["seen_before"]),
            "agreement": agreement,
        })
    result = {
        "session_id": meta["session_id"], "participant_id": meta["participant_id"],
        "camera_associations": field_analysis.associations(items),
        "synthetic": bool(meta["source"].get("synthetic")), "source": meta["source"]["kind"],
        "mode": meta.get("mode", "device"), "upload_warnings": meta.get("upload_warnings", []),
        "has_survey": bool(answers),
        "posterior_liking_note": liking_note,
        "upload_files": " + ".join(meta.get("files", {}).values()) if meta.get("mode") == "upload" else None,
        "label": "EEG 기반 추정", "disclaimer": DISCLAIMER,
        "model": {"name": model_name, "description": model_desc, "feature_channels": channels,
                  "n_features": len(cols), "feature_backend": feat.BACKEND, **eval_info},
        "n_trials": int(len(df)), "n_usable": int(len(usable)),
        "quality_counts": df["quality"].value_counts().to_dict(),
        "agreement_counts": counts, "rating_agreement_counts": rating_counts, "resting": resting_summary(eeg, markers, fs, channels),
        "integrity": {k: integrity[k] for k in ("eeg", "markers", "trials_complete", "trials_rated")},
        "items": sorted(items, key=lambda d: -(d["eeg_like_probability"] or 0)),
    }
    df.to_csv(session_dir / "features.csv", index=False)
    (session_dir / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
