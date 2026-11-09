"""python -m brainficial: demo, analyze, templates, or rehearsal experiment."""
import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import pandas as pd
from .loader import EEGLoader
from .signal import CompSig
from .model import CompLike
from .inference import permutation_check
from .synthetic import generate
from .report import write_report
from .experiment import ExperimentTemplate, EventLogger, ExperimentRunner, TkPresenter


def analyze(eeg, events_path, out, fs, channels, unit="uV", erp=False, synthetic=False, seed=42,
            permutations=0, assume_exchangeable=False):
    recording = EEGLoader().load(eeg, fs, channels, unit)
    events = pd.read_csv(events_path)
    features, quality = CompSig().extract(recording, events, erp)
    metrics, predictions = CompLike().evaluate(features, seed)
    metrics["permutation"] = permutation_check(features, permutations, seed,
                                               synthetic or assume_exchangeable)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    provenance = {"synthetic": synthetic, "seed": seed, "fs": fs, "channels": channels,
                  "input_unit": unit, "erp": erp, "python": sys.version,
                  "permutations": permutations, "assume_exchangeable": assume_exchangeable,
                  "inputs": {str(Path(p).resolve()): hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [eeg, events_path]},
                  "packages": {p: importlib.metadata.version(p) for p in ["numpy", "scipy", "pandas", "scikit-learn", "matplotlib"]}}
    (out/"provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    write_report(out, recording, events, features, quality, metrics, predictions, synthetic)
    print(f"{'SYNTHETIC - NOT EMPIRICAL' if synthetic else 'EXPLORATORY REAL INPUT'} | {metrics['status']} | {out.resolve() / 'report.html'}")
    return metrics


def main():
    parser = argparse.ArgumentParser(description="BrainFicial EEG preference research")
    sub = parser.add_subparsers(dest="command", required=True)
    pairs = sub.add_parser("deap-pairs", help="Compare liking order on held-out video pairs")
    pairs.add_argument("--features", default="outputs/real/deap/features.csv")
    pairs.add_argument("--out", default="outputs/real/deap_pairs")
    pairs.add_argument("--seed", type=int, default=42)
    deap = sub.add_parser("deap", help="Within-person DEAP music-video liking benchmark")
    deap.add_argument("--data", required=True)
    deap.add_argument("--out", default="outputs/real/deap")
    deap.add_argument("--seed", type=int, default=42)
    demo = sub.add_parser("demo", help="Generate labeled synthetic EEG and analyze")
    demo.add_argument("--out", default="outputs/demo")
    demo.add_argument("--kind", choices=["color", "person", "music"], default="color")
    demo.add_argument("--null", action="store_true", help="Generic response only; no injected liking effect")
    demo.add_argument("--erp", action="store_true")
    demo.add_argument("--seed", type=int, default=42)
    demo.add_argument("--permutations", type=int, default=0)
    real = sub.add_parser("analyze")
    real.add_argument("--eeg", required=True)
    real.add_argument("--events", required=True)
    real.add_argument("--out", default="outputs/analysis")
    real.add_argument("--fs", type=float, required=True)
    real.add_argument("--channels", nargs="+", required=True)
    real.add_argument("--unit", choices=["uV", "mV", "V"], required=True)
    real.add_argument("--erp", action="store_true")
    real.add_argument("--source", choices=["real", "synthetic"], required=True)
    real.add_argument("--permutations", type=int, default=0)
    real.add_argument("--assume-exchangeable", action="store_true",
                      help="Only use after justifying exchangeability of stimulus labels")
    templates = sub.add_parser("templates")
    templates.add_argument("--out", default="templates")
    run = sub.add_parser("run", help="Software-timed rehearsal UI; no hardware recording")
    run.add_argument("--template", required=True)
    run.add_argument("--events", default="outputs/live/events.csv")
    run.add_argument("--participant", default="P001")
    run.add_argument("--session", default="S001")
    run.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        if args.command == "deap-pairs":
            from .deap_pairs import run as run_pairs
            run_pairs(args.features, args.out, args.seed)
        elif args.command == "deap":
            from .deap import run as run_deap
            run_deap(args.data, args.out, args.seed)
        elif args.command == "demo":
            eeg, events = generate(Path(args.out)/"input", args.kind, args.seed, args.null)
            analyze(eeg, events, args.out, 128, ["F3", "F4"], erp=args.erp, synthetic=True,
                    seed=args.seed, permutations=args.permutations)
            (Path(args.out)/"generator.json").write_text(json.dumps({"synthetic": True, "null": args.null, "kind": args.kind, "seed": args.seed}, indent=2), encoding="utf-8")
        elif args.command == "analyze":
            analyze(args.eeg, args.events, args.out, args.fs, args.channels, args.unit, args.erp,
                    args.source == "synthetic", permutations=args.permutations,
                    assume_exchangeable=args.assume_exchangeable)
        elif args.command == "templates":
            Path(args.out).mkdir(parents=True, exist_ok=True)
            for kind in ["color", "person", "music"]:
                path = Path(args.out)/f"{kind}.json"
                if path.exists():
                    raise FileExistsError(f"Refusing to overwrite {path}")
                path.write_text(json.dumps(asdict(ExperimentTemplate.example(kind)), indent=2), encoding="utf-8")
        else:
            template = ExperimentTemplate.load(args.template)
            presenter = TkPresenter(template)
            try:
                ExperimentRunner(presenter).run(template, EventLogger(args.events), args.participant, args.session, args.seed)
            finally:
                presenter.close()
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"BrainFicial input error: {exc}\n")


if __name__ == "__main__":
    main()
