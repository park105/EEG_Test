"""Four-channel population Liking regression; the artifact contains no participant IDs."""
import json
from pathlib import Path

import numpy as np

from .features import GetFeature

CHANNELS = ["O1", "Oz", "O2", "Pz"]
COLUMNS = [f"feature_{c}_{b}_db" for c in CHANNELS for b in ("theta", "alpha", "beta")]
MODEL = Path(__file__).with_name("posterior_liking.json")


def extract(base, stim, fs):
    nb, ns = round(3 * fs), round(4 * fs)
    if fs <= 60 or len(base) < nb or len(stim) < ns:
        return None
    base, stim = base[-nb:], stim[:ns]
    for window in (base, stim):
        if not np.isfinite(window).all() or np.any(np.ptp(window, axis=0) == 0):
            return None
        if np.max(np.abs(window - window.mean(axis=0))) > 150:
            return None
    psd = GetFeature().psd
    before, after = psd(base, fs, CHANNELS), psd(stim, fs, CHANNELS)
    return np.array([10 * np.log10((after[key] + 1e-12) / (before[key] + 1e-12))
                     for key in (col[8:-3] for col in COLUMNS)])


def score(vector, model):
    return np.clip(np.asarray(vector) @ model["weights"] + model["intercept"], 1, 9)


def predict_session(eeg, trials, fs, integrity):
    missing = [ch for ch in CHANNELS if ch not in eeg]
    if missing:
        return {}, "필수 채널 누락: " + ", ".join(missing)
    if not integrity["model_input"]:
        return {}, "EEG 시간축 무결성 검사 실패"
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    if model["features"] != COLUMNS:
        raise ValueError("Posterior model feature mismatch")
    values = eeg[CHANNELS].to_numpy(float)
    times = eeg.timestamp_s.to_numpy()
    scores = {}
    for trial in trials.itertuples():
        a, b, c = np.searchsorted(times, [trial.fixation_onset, trial.stimulus_onset, trial.stimulus_offset])
        vector = extract(values[a:b], values[b:c], fs)
        if vector is not None:
            scores[trial.trial_index] = round(float(score(vector, model)), 3)
    return scores, f"유효 시행 {len(scores)}/{len(trials)} · 직전 3초 대비 시청 첫 4초"

