"""SETU command-line interface.

    python -m app.cli init-db
    python -m app.cli seed
    python -m app.cli simulate --days 30 --count 220 --seed 42
    python -m app.cli evaluate [--ablation] [--provider mock|gateway|local]

Sub-modules are imported lazily inside each handler so that early-phase
commands keep working before later subsystems exist.
"""
from __future__ import annotations

import argparse
import asyncio
import sys


def _cmd_init_db(_args) -> int:
    from app.seed import init_db

    init_db()
    print("Database schema created.")
    return 0


def _cmd_seed(_args) -> int:
    from app.seed import run_seed

    summary = run_seed()
    print(
        "Seed complete: "
        f"{summary['departments']} departments, {summary['officers']} officers, "
        f"{summary['holidays']} holidays, {summary['golden_samples']} golden samples."
    )
    return 0


def _cmd_simulate(args) -> int:
    from app.simulator import run_simulation

    result = asyncio.run(
        run_simulation(days=args.days, count=args.count, seed=args.seed, reset=args.reset)
    )
    print(
        f"Simulated {result['created']} grievances over {args.days} days "
        f"(seed={args.seed}). Review queue: {result.get('review', 0)}, "
        f"duplicates: {result.get('duplicates', 0)}, overdue-open: {result.get('overdue', 0)}."
    )
    return 0


def _cmd_evaluate(args) -> int:
    if args.ablation:
        from app.evaluation.ablation import run_ablation

        result = asyncio.run(run_ablation(provider=args.provider))
        print(result["table_text"])
    else:
        from app.evaluation.runner import run_evaluation

        result = asyncio.run(run_evaluation(provider=args.provider))
        print(
            f"macro-F1={result['macro_f1']:.3f}  accuracy={result['accuracy']:.3f}  "
            f"weighted-F1={result['weighted_f1']:.3f}  n={result['sample_count']}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="SETU command line")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create the database schema").set_defaults(func=_cmd_init_db)
    sub.add_parser("seed", help="Seed departments, officers, holidays, settings, golden set").set_defaults(
        func=_cmd_seed
    )

    p_sim = sub.add_parser("simulate", help="Generate a realistic month of grievances")
    p_sim.add_argument("--days", type=int, default=30)
    p_sim.add_argument("--count", type=int, default=220)
    p_sim.add_argument("--seed", type=int, default=42)
    p_sim.add_argument("--reset", action="store_true", help="Delete existing grievances first")
    p_sim.set_defaults(func=_cmd_simulate)

    p_eval = sub.add_parser("evaluate", help="Run the evaluation harness")
    p_eval.add_argument("--ablation", action="store_true", help="Run the five-config ablation")
    p_eval.add_argument("--provider", default=None, help="Override LLM provider for this run")
    p_eval.set_defaults(func=_cmd_evaluate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
