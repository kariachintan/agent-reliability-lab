"""agent-lab list | run [--scenario NAME] [--report FILE] [--json] [--strict]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .model import ModelError, SimulatedModel, model_from_env
from .report import to_json, to_markdown
from .scenarios import SCENARIOS, by_name

EXIT_OK, EXIT_USAGE, EXIT_PROVIDER, EXIT_FAILED = 0, 2, 4, 5


def main(argv: list[str] | None = None, out=None) -> int:
    out = out or sys.stdout
    p = argparse.ArgumentParser(prog="agent-lab")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list scenarios")
    r = sub.add_parser("run", help="run scenarios")
    r.add_argument("--scenario", action="append", help="run only these (repeatable)")
    r.add_argument("--report", help="write a markdown report here")
    r.add_argument("--json", action="store_true", help="print JSON instead of text")
    r.add_argument("--strict", action="store_true", help="exit 5 if any scenario fails")
    args = p.parse_args(argv)

    if args.command == "list":
        for s in SCENARIOS:
            print(f"{s.name:24} {s.description}", file=out)
        return EXIT_OK

    try:
        env_model = model_from_env()
    except ModelError as exc:
        print(f"error: {exc}", file=out)
        return EXIT_PROVIDER

    selected = SCENARIOS
    if args.scenario:
        try:
            selected = [by_name(n) for n in args.scenario]
        except KeyError as exc:
            print(f"error: unknown scenario {exc}; try 'agent-lab list'", file=out)
            return EXIT_USAGE

    results = []
    for s in selected:
        # Misbehaving planners (fabricate/greedy) are scenario-specific. A real
        # model replaces only the well-behaved default planner, so those two
        # scenarios still exercise the guards deterministically.
        if isinstance(env_model, SimulatedModel) or s.model_factory is not SimulatedModel:
            model = s.model_factory()
        else:
            model = env_model
        results.append(s.run(model))

    planner = env_model.name
    if args.json:
        print(to_json(results, planner), file=out)
    else:
        for res in results:
            print(f"{'PASS' if res.passed else 'FAIL'}  {res.name:24} status={res.result.status}", file=out)
            for name, ok, observed in res.checks:
                if not ok:
                    print(f"      x {name}: {observed[:120]}", file=out)
        print(f"\n{sum(r.passed for r in results)}/{len(results)} scenarios passed", file=out)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(to_markdown(results, planner), encoding="utf-8")
        print(f"report written to {args.report}", file=out)
    if args.strict and not all(r.passed for r in results):
        return EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
