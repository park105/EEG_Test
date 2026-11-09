"""Counterbalanced behavioral pilot; optional synchronized EEG collected externally."""
import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from .experiment import ExperimentTemplate, Stimulus, TkPresenter

COLORS = {"red": Stimulus("red", "#c00000"), "green": Stimulus("green", "#008000")}


def schedule(blocks, rng):
    if blocks < 2 or blocks % 2:
        raise ValueError("Use an even number of blocks >=2")
    orders = [("red", "green"), ("green", "red")]
    return [[orders[k], orders[1-k]] for k in rng.permutation([0, 1]*(blocks//2))]


def measure(ui, dest, participant, blocks, seed, singles_first, clock=perf_counter):
    rng = np.random.default_rng(seed)
    plan = schedule(blocks, rng)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=False)
    origin = clock()
    def now():
        return clock()-origin
    def record(entry):
        with (dest/"observations.jsonl").open("a", encoding="utf8") as f:
            f.write(json.dumps(entry)+"\n")
    record(dict(kind="setup", participant=participant, seed=seed, blocks=blocks,
                singles_first=singles_first, colors={k:v.value for k,v in COLORS.items()},
                clock="relative software seconds; not synchronized EEG"))
    def expose(color):
        ui.blank()
        start = now()
        ui.wait(3)
        ui.show(COLORS[color])
        onset = now()
        ui.wait(4)
        ui.blank()
        return dict(color=color, rest_start_s=start, onset_s=onset, offset_s=now())
    ratings = {}
    def singles():
        for color in rng.permutation(list(COLORS)):
            event = expose(color)
            ratings[color] = ui.rating()
            record(dict(kind="independent_rating", **event, rating=ratings[color], answer_s=now()))
    if singles_first:
        singles()
    answers = []
    for block, orders in enumerate(plan, 1):
        row = {}
        for order in orders:
            events = [expose(c) for c in order]
            choice = ui.choose()
            row[order[0]] = choice
            record(dict(kind="pair", block=block, events=events, choice=choice, answer_s=now()))
        answers.append(row)
    if not singles_first:
        singles()
    inferred = "red" if ratings["red"] > ratings["green"] else "green" if ratings["green"] > ratings["red"] else "tie"
    same = sum(a["red"] == a["green"] for a in answers)
    result = dict(blocks=blocks, order_agreement=same/blocks, separate_rating_choice=inferred,
                  ratings=ratings, by_first_color={first: {
                      "choices":[a[first] for a in answers],
                      "match_separate_rating":sum(a[first]==inferred for a in answers)/blocks}
                      for first in COLORS})
    (dest/"comparison.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    return result


class ChoiceScreen(TkPresenter):
    def choose(self):
        answer = self.ask.askinteger("두 색의 선호", "1 빨강 / 2 초록 / 3 비슷함",
                                     minvalue=1, maxvalue=3, parent=self.root)
        if answer is None:
            raise KeyboardInterrupt("Participant stopped")
        return ("red", "green", "tie")[answer-1]


def main():
    p = argparse.ArgumentParser(description="Red/rest/green vs green/rest/red behavioral pilot")
    p.add_argument("--out", required=True, help="New session directory; never overwritten")
    p.add_argument("--participant", required=True)
    p.add_argument("--blocks", type=int, default=4)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--ratings-last", action="store_true")
    args = p.parse_args()
    ui = ChoiceScreen(ExperimentTemplate.example("color"))
    try:
        measure(ui, args.out, args.participant, args.blocks, args.seed, not args.ratings_last)
    finally:
        ui.close()


if __name__ == "__main__":
    main()
