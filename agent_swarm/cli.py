from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from agent_swarm.core.config import ConfigurationError, load_config
from agent_swarm.core.config_inspection import inspect_config, render_human
from agent_swarm.core.run import TaskPlan
from agent_swarm.swarm_runner import SwarmRunner


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


def _legacy_parser() -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--events-output",
        help="Write the canonical bus chronology as NDJSON to this path",
    )
    return parser


def _write_text_atomic(path: str | Path, content: str) -> None:
    """Replace one artifact only after its complete content reaches disk."""

    target = Path(path)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _config_show_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect a validated swarm configuration"
    )
    parser.add_argument(
        "--config", default=".swarm/config.yaml", help="Swarm YAML configuration"
    )
    parser.add_argument("--json", action="store_true", help="Print stable JSON")
    parser.add_argument(
        "--probe-versions",
        action="store_true",
        help="Run each distinct resolved provider executable with --version",
    )
    return parser


def _config_show(argv: list[str]) -> None:
    args = _config_show_parser().parse_args(argv)
    config_path = os.path.abspath(args.config)
    try:
        data = inspect_config(
            load_config(config_path), config_path, probe_versions=args.probe_versions
        )
    except (OSError, ValueError, ConfigurationError) as error:
        print(f"swarm configuration error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(render_human(data))


def _run_legacy(argv: list[str]) -> None:
    parser = _legacy_parser()
    args = parser.parse_args(argv)
    if args.plan_file and args.plan_json:
        parser.error("use only one of --plan-file or --plan-json")
    if (
        args.output
        and args.events_output
        and Path(args.output).resolve() == Path(args.events_output).resolve()
    ):
        parser.error("--output and --events-output must use different paths")

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
    try:
        if args.output:
            _write_text_atomic(args.output, rendered + "\n")
        if args.events_output:
            events = result.events_to_ndjson()
            _write_text_atomic(args.events_output, events + ("\n" if events else ""))
    except OSError as error:
        print(f"swarm output error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
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


def main() -> None:
    # Only the exact new command is intercepted; all other legacy goal syntax
    # (including a goal beginning with "config") keeps its established parser.
    argv = sys.argv[1:]
    if argv[:2] == ["config", "show"]:
        _config_show(argv[2:])
        return
    _run_legacy(argv)


if __name__ == "__main__":
    main()
