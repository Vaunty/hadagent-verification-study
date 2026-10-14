"""Run the project's older synthetic Proof-of-Inference demonstrations.

These runners use constructed scores, outputs, records, or trust transitions.
Their summary values are fixture behavior, not measurements of a deployed
HadAgent network or the paper's complete consensus design. The P010, P012, and
P013 research workflows have separate entry points under ``experiments/``.

Available demonstrations:
1. determinism: fixed score jitter across named execution configurations.
2. trust-then-betray: simulated optimistic delivery and trust transitions.
3. model-binding: lookup-table and proxy-model scenarios.
4. reproducibility: fixed unsafe-output fixtures and an optional judge.
5. validation-fuzzing: hand-written records and the historical tuple bug.

Usage:
    python runner.py --attack determinism
    python runner.py --attack trust-then-betray [--defense]
    python runner.py --attack model-binding
    python runner.py --attack reproducibility [--defense]
    python runner.py --attack validation-fuzzing
    python runner.py --attack all
"""
import sys
import argparse
from typing import Dict, Any

from runners.determinism import run_determinism_study
from runners.trust_then_betray import run_trust_then_betray_simulation
from runners.model_binding import run_model_binding_study
from runners.reproducibility import run_reproducibility_vs_safety_study
from runners.validation_fuzzing import run_validation_fuzzing_study
from core.defenses import PoIDefense


def main():
    parser = argparse.ArgumentParser(description="Synthetic Proof-of-Inference red-team demonstrations")
    parser.add_argument(
        "--attack",
        choices=["determinism", "trust-then-betray", "model-binding", "reproducibility", "validation-fuzzing", "all"],
        default="all",
        help="Synthetic demonstration to execute (default: all)"
    )
    parser.add_argument("--defense", action="store_true", help="Enable in-path defense mechanisms")
    parser.add_argument("--rounds", type=int, default=12, help="Number of rounds for stateful attack simulations")
    args = parser.parse_args()

    results: Dict[str, Any] = {}

    print("=================================================================")
    print("  Synthetic Proof-of-Inference Red-Team Demonstrations           ")
    print("=================================================================")

    if args.attack in ("determinism", "all"):
        print("\n>>> Demonstration 1: Fixed Determinism Jitter <<<")
        results["determinism"] = run_determinism_study()

    if args.attack in ("trust-then-betray", "all"):
        print("\n>>> Demonstration 2: Simulated Trust-Then-Betray <<<")
        defense = PoIDefense(safety_judge=True, audit_probability=0.33) if args.defense else None
        results["trust_then_betray"] = run_trust_then_betray_simulation(
            rounds=args.rounds,
            betray_at_round=6,
            defense=defense
        )

    if args.attack in ("model-binding", "all"):
        print("\n>>> Demonstration 3: Model Binding and Lookup Table <<<")
        results["model_binding"] = run_model_binding_study()

    if args.attack in ("reproducibility", "all"):
        print("\n>>> Demonstration 4: Reproducibility and Safety Fixtures <<<")
        results["reproducibility"] = run_reproducibility_vs_safety_study(use_defense=args.defense)

    if args.attack in ("validation-fuzzing", "all"):
        print("\n>>> Demonstration 5: Validation Corpus and Tuple Bug <<<")
        results["validation_fuzzing"] = run_validation_fuzzing_study()

    print("\n=================================================================")
    print("  All requested synthetic runners completed. See README for the   ")
    print("  evidence labels and separate measured experiments.              ")
    print("  Results logged to SQLite database (harness.db).                ")
    print("=================================================================\n")


if __name__ == "__main__":
    main()
