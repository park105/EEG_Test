"""Synthetic signal generator. Injected association is an implementation fixture."""
from pathlib import Path
import numpy as np
import pandas as pd
from .experiment import ExperimentTemplate


def generate(destination, kind="color", seed=42, null=False):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    template = ExperimentTemplate.example(kind)
    fs = 128
    trials = template.schedule(seed)
    time = np.arange(int((len(trials)*9+1)*fs))/fs
    data = rng.normal(0, 3, (len(time), 2))
    for j in range(2):
        data[:, j] += 7*np.sin(2*np.pi*10*time+j)+3*np.sin(2*np.pi*6*time+.5*j)
    rows = []
    for i, s in enumerate(trials):
        start, onset, offset = 1+9*i, 4+9*i, 8+9*i
        # Deliberately not a physiological law: odd/even ID defines synthetic liking.
        liked = int(s.stimulus_id.rsplit("_", 1)[1]) % 2
        rating = int(rng.choice([4, 5] if liked else [1, 2]))
        mask = (time >= onset) & (time < offset)
        local = time[mask]-onset
        for j in range(2):
            amp = 3 if null else (7 if liked else 1)
            data[mask, j] += amp*np.sin(2*np.pi*20*local+.3*j)
            data[mask, j] += 3*np.exp(-((local-.35)/.08)**2)  # generic onset response in BOTH labels
        rows.append(dict(participant_id="SYNTHETIC_P001", session_id="SYNTHETIC_S001",
                         trial_id=f"T{i:03d}", stimulus_id=s.stimulus_id, kind=kind,
                         baseline_start_s=start, onset_s=onset, offset_s=offset,
                         rating_time_s=offset+.5, rating=rating))
    pd.DataFrame({"timestamp_s": time, "F3": data[:, 0], "F4": data[:, 1]}).to_csv(destination/"eeg.csv", index=False)
    pd.DataFrame(rows).to_csv(destination/"events.csv", index=False)
    return destination/"eeg.csv", destination/"events.csv"
