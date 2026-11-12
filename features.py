"""Trial-local features from the preprocessed MATLAB DEAP release."""
import argparse
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
from scipy.io import loadmat
from scipy.signal import welch

FS = 128
CHANNELS = "Fp1 AF3 F3 F7 FC5 FC1 C3 T7 CP5 CP1 P3 P7 PO3 O1 Oz Pz Fp2 AF4 Fz F4 F8 FC6 FC2 Cz C4 T8 CP6 CP2 P4 P8 PO4 O2".split()
FOUR = ["F3", "F4", "C3", "C4"]
LABELS = ["Valence", "Arousal", "Dominance", "Liking"]
BANDS = [(4, 8), (8, 13), (13, 30), (30, 45)]
DEFAULT_DATA = Path(__file__).resolve().parents[2] / "생체데이터 분석과 실무" / "DEAP_DATA_SET"


def power(signal):
    freq, density = welch(signal, fs=FS, window="hann", nperseg=256, noverlap=128)
    areas = [density[:, (freq >= lo) & (freq < hi)].sum(axis=1) * (freq[1]-freq[0])
             for lo, hi in BANDS]
    return 10 * np.log10(np.maximum(np.stack(areas, axis=1), 1e-12))


def features(eeg):
    if eeg.shape != (32, 8064) or not np.isfinite(eeg).all():
        raise ValueError("Expected 32 finite EEG channels at 128 Hz for 63 seconds")
    base = power(eeg[:, :3*FS])
    segments = np.split(eeg[:, 3*FS:], 3, axis=1)
    stimulus = np.stack([power(segment) for segment in segments])
    # shape: channels, intervals, absolute/change, bands
    return np.stack([stimulus, stimulus-base], axis=2).transpose(1, 0, 2, 3)


def read_subject(root, subject, variables):
    filename = f"s{subject:02}.mat"
    if root.is_file():
        with ZipFile(root) as archive:
            entries = [name for name in archive.namelist() if Path(name).name == filename]
            if len(entries) != 1:
                raise ValueError(f"Expected exactly one {filename} in {root}")
            return loadmat(BytesIO(archive.read(entries[0])), variable_names=variables)
    return loadmat(root / "data_preprocessed_matlab" / filename, variable_names=variables)


def extract(root, out, ratings_path):
    signals, labels = [], []
    for subject in range(1, 33):
        mat = read_subject(root, subject, ["data", "labels"])
        if mat["data"].shape != (40, 40, 8064) or mat["labels"].shape != (40, 4):
            raise ValueError(f"Unexpected dimensions for participant {subject}")
        signals.extend(features(trial[:32]) for trial in mat["data"])
        labels.extend(mat["labels"])
        del mat
    ids = pd.MultiIndex.from_product([range(1, 33), range(1, 41)], names=["Participant_id", "Experiment_id"])
    labels = pd.DataFrame(labels, index=ids, columns=LABELS)
    if not labels.apply(lambda col: col.between(1, 9)).all().all():
        raise ValueError("Invalid standard rating")
    if ratings_path is not None:
        ratings = pd.read_csv(ratings_path).set_index(ids.names).sort_index()
        if not ratings.index.equals(ids):
            raise ValueError("Participant/video keys differ between CSV and MATLAB")
        np.testing.assert_allclose(ratings[LABELS], labels, atol=1e-8, rtol=0)
        fam = ratings.Familiarity
        if not fam.dropna().between(1, 5).all():
            raise ValueError("Invalid Familiarity")
        labels["Familiarity"] = fam
        print("Familiarity counts by participant:", fam.groupby(level=0).count().to_dict())
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, x=np.stack(signals), y=labels.to_numpy(), targets=labels.columns.to_numpy(dtype=str),
                        subject=ids.get_level_values(0).to_numpy(), video=ids.get_level_values(1).to_numpy())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--ratings", type=Path, help="Optional participant_ratings.csv")
    parser.add_argument("--out", type=Path, default=Path("results/features.npz"))
    args = parser.parse_args()
    extract(args.data, args.out, args.ratings)
