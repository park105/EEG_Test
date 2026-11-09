"""Experiment scheduling and event logging independent of EEG device SDKs."""
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter, sleep
from typing import Protocol
import colorsys
import csv
import json
import numpy as np
import pandas as pd
from .validation import EVENT_COLUMNS


@dataclass(frozen=True)
class Stimulus:
    stimulus_id: str
    value: str


@dataclass
class ExperimentTemplate:
    kind: str
    stimuli: list[Stimulus]
    baseline_s: float = 3
    duration_s: float = 4
    repeats: int = 2

    def __post_init__(self):
        if self.kind not in {"color", "person", "music"}:
            raise ValueError("Unknown experiment kind")
        if not self.stimuli or len({s.stimulus_id for s in self.stimuli}) != len(self.stimuli):
            raise ValueError("Provide stimuli with unique stable IDs")
        if self.baseline_s < 2 or self.duration_s < 2 or self.repeats < 1:
            raise ValueError("Durations >=2 seconds and repeats >=1 required")

    @classmethod
    def example(cls, kind="color"):
        if kind == "color":
            values = ["#%02x%02x%02x" % tuple(int(c*255) for c in colorsys.hsv_to_rgb(i/12, .65, .8)) for i in range(12)]
        else:
            extension = "png" if kind == "person" else "wav"
            values = [f"assets/{kind}_{i:02d}.{extension}" for i in range(12)]
        return cls(kind, [Stimulus(f"{kind}_{i:02d}", v) for i, v in enumerate(values)])

    @classmethod
    def load(cls, path):
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["kind"] != "color":
            for s in data["stimuli"]:
                s["value"] = str((path.parent / s["value"]).resolve())
        data["stimuli"] = [Stimulus(**s) for s in data["stimuli"]]
        return cls(**data)

    def schedule(self, seed=42):
        rng = np.random.default_rng(seed)
        return [self.stimuli[i] for _ in range(self.repeats) for i in rng.permutation(len(self.stimuli))]


class EventLogger:
    """Append and flush each completed trial; keep partial markers on interruption."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise FileExistsError(f"Refusing to overwrite events: {path}")
        with self.path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=EVENT_COLUMNS).writeheader()

    def marker(self, trial_id, name, timestamp_s):
        with self.path.with_suffix(".markers.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"trial_id": trial_id, "event": name, "timestamp_s": timestamp_s})+"\n")

    def append(self, event):
        with self.path.open("a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=EVENT_COLUMNS).writerow(event)


class Presenter(Protocol):
    def blank(self): ...
    def show(self, stimulus: Stimulus): ...
    def wait(self, seconds: float): ...
    def rating(self) -> int: ...


class ExperimentRunner:
    def __init__(self, presenter: Presenter, clock=perf_counter):
        self.presenter, self.clock = presenter, clock

    def run(self, template, logger, participant="P001", session="S001", seed=42):
        origin = self.clock()
        now = lambda: self.clock()-origin
        for i, stimulus in enumerate(template.schedule(seed)):
            trial = f"T{i:03d}"
            self.presenter.blank()
            baseline = now()
            logger.marker(trial, "baseline_start", baseline)
            self.presenter.wait(template.baseline_s)
            self.presenter.show(stimulus)
            onset = now()
            logger.marker(trial, "onset", onset)
            self.presenter.wait(template.duration_s)
            self.presenter.blank()
            offset = now()
            logger.marker(trial, "offset", offset)
            rating = self.presenter.rating()
            rating_time = now()
            logger.marker(trial, "rating", rating_time)
            logger.append(dict(participant_id=participant, session_id=session, trial_id=trial,
                               stimulus_id=stimulus.stimulus_id, kind=template.kind,
                               baseline_start_s=baseline, onset_s=onset, offset_s=offset,
                               rating_time_s=rating_time, rating=rating))


class TkPresenter:
    """Rehearsal UI: software timestamps only, never frame/audio onset precision."""
    def __init__(self, template):
        import tkinter as tk
        from tkinter import simpledialog
        self.tk, self.ask = tk, simpledialog
        self.kind = template.kind
        if self.kind != "color":
            for s in template.stimuli:
                if not Path(s.value).is_file():
                    raise ValueError(f"Supply consented/licensed local asset: {s.value}")
        if self.kind == "music":
            import wave
            import winsound
            for s in template.stimuli:
                with wave.open(s.value, "rb") as audio:
                    if audio.getnframes()/audio.getframerate() < template.duration_s:
                        raise ValueError(f"Audio shorter than stimulus duration: {s.value}")
            self.sound = winsound
        self.root = tk.Tk()
        self.root.title("BrainFicial | rehearsal — software timing")
        self.root.geometry("900x650")
        self.label = tk.Label(self.root, font=("Arial", 28))
        self.label.pack(fill="both", expand=True)

    def blank(self):
        if self.kind == "music":
            self.sound.PlaySound(None, 0)
        self.label.configure(image="", text="+", bg="#808080", fg="white")
        self.root.update()

    def show(self, stimulus):
        if self.kind == "color":
            self.label.configure(text="", bg=stimulus.value)
        elif self.kind == "person":
            self.image = self.tk.PhotoImage(file=stimulus.value)
            self.label.configure(text="", image=self.image)
        else:
            self.label.configure(text="+", bg="#808080")
            self.sound.PlaySound(stimulus.value, self.sound.SND_FILENAME | self.sound.SND_ASYNC)
        self.root.update()

    def wait(self, seconds):
        end = perf_counter()+seconds
        while perf_counter() < end:
            self.root.update()
            sleep(.005)

    def rating(self):
        value = self.ask.askinteger("선호도", "1 매우 싫음 · 2 싫음 · 3 중립 · 4 좋음 · 5 매우 좋음",
                                   minvalue=1, maxvalue=5, parent=self.root)
        if value is None:
            raise KeyboardInterrupt("Rating cancelled; partial markers retained")
        return value

    def close(self):
        if self.kind == "music":
            self.sound.PlaySound(None, 0)
        self.root.destroy()
