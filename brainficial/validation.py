"""Fail closed on malformed event timing and participant mixing."""
import numpy as np
import pandas as pd
from .loader import Recording

EVENT_COLUMNS = ["participant_id", "session_id", "trial_id", "stimulus_id", "kind",
                 "baseline_start_s", "onset_s", "offset_s", "rating_time_s", "rating"]


def validate_events(events: pd.DataFrame, recording: Recording | None = None):
    if not set(EVENT_COLUMNS).issubset(events.columns) or events.empty:
        raise ValueError("Events must contain all documented columns and at least one trial")
    if events[EVENT_COLUMNS].isna().any().any():
        raise ValueError("Missing event values or ratings")
    if events.trial_id.duplicated().any():
        raise ValueError("trial_id must be unique")
    for c in ["participant_id", "session_id", "stimulus_id", "kind"]:
        if events[c].astype(str).str.strip().eq("").any():
            raise ValueError(f"Empty {c}")
    if events.participant_id.nunique() != 1 or events.session_id.nunique() != 1:
        raise ValueError("Analyze one participant and one session at a time")
    if events.kind.nunique() != 1 or not events.kind.isin(["color", "person", "music"]).all():
        raise ValueError("Analyze one modality at a time")
    times = events[["baseline_start_s", "onset_s", "offset_s", "rating_time_s"]].to_numpy(float)
    ratings = events.rating.to_numpy(float)
    if not np.isfinite(times).all() or not np.isfinite(ratings).all():
        raise ValueError("Event numbers must be finite")
    if np.any(np.diff(times[:, :3], axis=1) <= 0) or np.any(times[:, 3] < times[:, 2]):
        raise ValueError("Require baseline < onset < offset <= rating time")
    if np.any((ratings < 1) | (ratings > 5)) or np.any(ratings != np.floor(ratings)):
        raise ValueError("Ratings must be integers 1..5")
    if np.any(times[:, 1] - times[:, 0] < 2) or np.any(times[:, 2] - times[:, 1] < 2):
        raise ValueError("PSD requires at least 2 seconds each of baseline and stimulus")
    ordered = times[np.argsort(times[:, 0])]
    if np.any(ordered[1:, 0] < ordered[:-1, 3]):
        raise ValueError("Trials/baselines overlap previous stimulus or rating")
    if recording is not None:
        if times.min() < recording.time[0] - 1e-6 or times[:, 2].max() > recording.time[-1] + 1/recording.fs + 1e-6:
            raise ValueError("EEG does not cover complete baselines and stimuli")
