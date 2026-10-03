"""Run the synthetic demonstration or explicitly select live SDK execution."""

import argparse
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path

from collaboration.artifacts import verify_artifact, write_artifact
from collaboration.backends import FixtureBackend, SdkBackend
from collaboration.contracts import Budget
from collaboration.coordinator import run
from collaboration.evidence import build_tasks
from warehouse.build import build


async def execute(args):
    if args.mode == "live" and (args.compare or args.scenario != "clean"):
        raise ValueError("Fault injection and comparison are fixture-only")
    build()  # The existing documented local synthetic warehouse only.
    tasks = build_tasks(conflict=args.scenario == "conflict")
    timeout = args.timeout if args.timeout is not None else (30.0 if args.mode == "live" else 0.08)
    budget = Budget(attempt_timeout=timeout)
    if args.mode == "fixture":
        backend = FixtureBackend(args.scenario)
    else:
        backend = SdkBackend(args.model or os.environ.get("OPENAI_MODEL"))
    try:
        result = await run(tasks, backend, budget)
    finally:
        if isinstance(backend, SdkBackend):
            await backend.close()
    if args.compare:
        sequential = await run(tasks, FixtureBackend(args.scenario), replace(budget, max_concurrency=1))
        comparison = {
            "mode": "fixture", "scenario": args.scenario,
            "decision_equivalent": result["summary"] == sequential["summary"],
            "parallel": result["measurements"], "sequential": sequential["measurements"],
            "interpretation": "Measured scheduler timing with simulated delays; not a live-model speedup claim.",
        }
        print(json.dumps(comparison, indent=2))
        if not comparison["decision_equivalent"]:
            raise ValueError("Sequential/parallel decision mismatch")
        if args.output:
            write_artifact(args.output.with_name(args.output.stem + "-sequential.json"), sequential)
    if args.output:
        write_artifact(args.output, result)
    print(json.dumps({"mode": result["mode"], **result["summary"],
                      "measurements": result["measurements"], "artifact_sha256": result["artifact_sha256"]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo")
    demo.add_argument("--mode", choices=["fixture", "live"], default="fixture")
    demo.add_argument("--scenario", choices=["clean", "invalid", "timeout", "conflict"], default="clean")
    demo.add_argument("--compare", action="store_true")
    demo.add_argument("--model")
    demo.add_argument("--timeout", type=float)
    demo.add_argument("--output", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "verify":
        print(json.dumps(verify_artifact(json.loads(args.path.read_text())), indent=2))
    else:
        asyncio.run(execute(args))


if __name__ == "__main__":
    main()
