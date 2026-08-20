from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from src.core.config import ConfigurationError, load_config
from src.core.run import TaskPlan
from src.swarm_runner import SwarmRunner


def _load_plan(args: argparse.Namespace) -> TaskPlan | None:
    if args.plan_json:
        return TaskPlan.from_json(args.plan_json, source="caller_json")
    if args.plan_file:
        value = Path(args.plan_file).read_text(encoding="utf-8")
        return TaskPlan.from_json(value, source=f"caller_file:{args.plan_file}")
    return None


async def run_swarm(
    goal: str,
    config_path: str,
    *,
    cwd: str,
    plan: TaskPlan | None = None,
):
    config = load_config(config_path)
    runner = SwarmRunner(config)
    return await runner.run(goal, cwd=cwd, plan=plan)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent Swarm Framework CLI")
    parser.add_argument("goal", help="High-level goal for the swarm")
    parser.add_argument(
        "--config", default=".swarm/config.yaml", help="Swarm YAML configuration"
    )
    parser.add_argument(
        "--plan-file",
        help="Caller-supplied JSON task plan; skips an overseer provider call",
    )
    parser.add_argument(
        "--plan-json",
        help="Inline JSON task plan; skips an overseer provider call",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the full run record as JSON"
    )
    parser.add_argument(
        "--output",
        help="Write the full run record to this path; nothing is persisted by default",
    )
    args = parser.parse_args()
    if args.plan_file and args.plan_json:
        parser.error("use only one of --plan-file or --plan-json")

    config_path = os.path.abspath(args.config)
    try:
        plan = _load_plan(args)
        result = asyncio.run(
            run_swarm(
                args.goal,
                config_path,
                cwd=os.getcwd(),
                plan=plan,
            )
        )
    except (OSError, ValueError, ConfigurationError) as error:
        print(f"swarm configuration error: {error}", file=sys.stderr)
        raise SystemExit(2) from error

    rendered = result.to_json()
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    if args.json:
        print(rendered)
    else:
        print(result.final_output)
        usage = result.record.usage
        print(
            f"\nRun {result.record.run_id}: {result.record.status}; "
            f"provider calls={usage['provider_calls']}; "
            f"budget-accounted tokens={usage['budget_accounted_tokens']}; "
            f"accounted cost=${usage['accounted_cost_usd']:.6f} "
            f"(reported=${usage['provider_reported_cost_usd']:.6f}, "
            f"estimated=${usage['estimated_cost_usd']:.6f})"
        )
        if usage["unknown_cost_calls"]:
            print(f"Cost unavailable for {usage['unknown_cost_calls']} call(s).")

    raise SystemExit(0 if result.record.status == "succeeded" else 1)


if __name__ == "__main__":
    main()
