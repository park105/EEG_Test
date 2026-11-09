import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from brainficial.color_order import measure


class PilotTest(unittest.TestCase):
    def test_counterbalance_canonical_choices_and_separate_ratings(self):
        class Screen:
            t = 0
            def blank(self): pass
            def wait(self, secs): self.t += secs
            def show(self, s): self.color = s.stimulus_id
            def rating(self): return 4 if self.color == "red" else 3
            def choose(self): return self.color  # deliberate bias for last presented
        ui = Screen()
        with TemporaryDirectory() as d:
            out = Path(d)/"pilot"
            result = measure(ui, out, "test", 4, 42, False, clock=lambda: ui.t)
            self.assertEqual(result["order_agreement"], 0)
            self.assertEqual(result["separate_rating_choice"], "red")
            rows = [json.loads(x) for x in (out/"observations.jsonl").read_text().splitlines()]
            pairs = [r for r in rows if r["kind"] == "pair"]
            self.assertEqual(sum(r["events"][0]["color"]=="red" for r in pairs[::2]), 2)
            for r in pairs:
                a,b = r["events"]
                self.assertEqual(b["onset_s"]-a["offset_s"], 3)
