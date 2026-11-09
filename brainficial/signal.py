"""Trial-local processing prevents filter propagation across validation groups."""
import numpy as np
import pandas as pd
from scipy.signal import butter, sosfiltfilt, welch
from .validation import validate_events


class AnalEEG:
    def __init__(self, fs: float, artifact_uv: float = 150):
        self.fs, self.artifact_uv = fs, artifact_uv
        self.sos = butter(4, [1, 40], btype="bandpass", fs=fs, output="sos")

    def quality(self, x):
        if np.max(np.abs(x)) > self.artifact_uv or np.max(np.ptp(x, axis=0)) > 2*self.artifact_uv:
            return "amplitude_artifact"
        if np.any(np.std(x, axis=0) < .05):
            return "flat_channel"
        return "ok"

    def transform(self, x):
        return sosfiltfilt(self.sos, x, axis=0)


class GetFeature:
    bands = {"theta": (4, 8), "alpha": (8, 13), "beta": (13, 30)}

    def psd(self, x, fs, channels):
        f, p = welch(x, fs=fs, nperseg=int(2*fs), axis=0)
        result = {}
        for band, (lo, hi) in self.bands.items():
            power = p[(f >= lo) & (f < hi)].sum(axis=0) * (f[1]-f[0])
            for channel, value in zip(channels, power):
                result[f"{channel}_{band}"] = float(value)
        return result


class CompSig:
    def extract(self, recording, events, erp=False):
        validate_events(events, recording)
        pre = AnalEEG(recording.fs)
        get = GetFeature()
        rows, quality = [], []
        for e in events.to_dict("records"):
            t = recording.time
            baseline = recording.samples[(t >= e["baseline_start_s"]-1e-8) & (t < e["onset_s"]-1e-8)]
            stimulus = recording.samples[(t >= e["onset_s"]-1e-8) & (t < e["offset_s"]-1e-8)]
            reason = next((r for r in [pre.quality(baseline), pre.quality(stimulus)] if r != "ok"), "ok")
            quality.append({"trial_id": e["trial_id"], "status": reason})
            if reason != "ok":
                continue
            # Separate baseline/stimulus filters avoid future-stimulus leakage into baseline.
            b = get.psd(pre.transform(baseline), recording.fs, recording.channels)
            s = get.psd(pre.transform(stimulus), recording.fs, recording.channels)
            row = dict(e)
            for k in b:
                row[f"baseline_{k}"] = b[k]
                row[f"stimulus_{k}"] = s[k]
                row[f"feature_{k}_db"] = 10*np.log10((s[k]+1e-12)/(b[k]+1e-12))
            if erp:
                # Exploratory raw baseline-corrected mean, NOT a detected P300 component.
                start, stop = int(.3*recording.fs), int(.5*recording.fs)
                recent = baseline[-int(.2*recording.fs):].mean(axis=0)
                amplitude = stimulus[start:stop].mean(axis=0)-recent
                for channel, value in zip(recording.channels, amplitude):
                    row[f"feature_{channel}_erp_300_500_uv"] = float(value)
            rows.append(row)
        return pd.DataFrame(rows), pd.DataFrame(quality)
