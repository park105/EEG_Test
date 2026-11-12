"""Build a standalone offline viewer from the verified outer-fold predictions."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LABELS = ["Valence", "Arousal", "Dominance", "Liking", "Familiarity"]


def build():
    trials = {}
    with (ROOT / "results/predictions.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            key = f"{row['participant']}/{row['video']}/{row['regime']}/{row['montage']}/{row['model']}"
            values = trials.setdefault(key, [None] * len(LABELS))
            idx = LABELS.index(row["target"])
            if values[idx] is not None:
                raise ValueError(f"Duplicate prediction for {key}")
            values[idx] = [float(row["truth"]), float(row["prediction"])]
    template = (ROOT / "viewer.template.html").read_text(encoding="utf-8")
    html = template.replace("/*PREDICTIONS*/", json.dumps(trials, separators=(",", ":"), allow_nan=False))
    (ROOT / "results/trial_viewer.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    build()
