from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from agent_swarm.core.config import ConfigurationError, load_config
from agent_swarm.core.config_inspection import inspect_config, render_human
from agent_swarm.core.run import SwarmRunResult, TaskPlan
from agent_swarm.core.worktree import (
    ManagedWorktree,
    WorktreeError,
    capture_workspace_patch,
    create_managed_worktree,
    remove_managed_worktree,
    workspace_status,
)
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
    parser.add_argument(
        "--local-artifacts-dir",
        help=(
            "run in a managed temporary Git worktree, write a complete artifact "
            "set under this directory, then remove the worktree"
        ),
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


def _write_bytes_atomic(path: str | Path, content: bytes) -> None:
    """Replace one binary artifact only after its complete content reaches disk."""

    target = Path(path)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
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


def _write_local_artifacts(
    artifacts_root: str | Path,
    worktree: ManagedWorktree,
    result: SwarmRunResult,
) -> Path:
    """Persist the complete run and workspace state before cleanup is allowed."""

    artifact_dir = Path(artifacts_root).resolve() / result.record.run_id
    artifact_dir.mkdir(parents=True, exist_ok=False)
    patch = capture_workspace_patch(worktree)
    status = workspace_status(worktree)
    events = result.events_to_ndjson()
    run_content = result.to_json() + "\n"
    events_content = events + ("\n" if events else "")

    _write_text_atomic(artifact_dir / "run.json", run_content)
    _write_text_atomic(artifact_dir / "run.events.ndjson", events_content)
    _write_bytes_atomic(artifact_dir / "workspace.patch", patch)
    manifest = {
        "schema_version": "1.0",
        "run_id": result.record.run_id,
        "run_status": result.record.status,
        "base_commit": worktree.base_commit,
        "workspace_status": list(status),
        "artifacts": {
            "run": {
                "path": "run.json",
                "sha256": hashlib.sha256(run_content.encode("utf-8")).hexdigest(),
            },
            "events": {
                "path": "run.events.ndjson",
                "sha256": hashlib.sha256(events_content.encode("utf-8")).hexdigest(),
            },
            "workspace_patch": {
                "path": "workspace.patch",
                "sha256": hashlib.sha256(patch).hexdigest(),
            },
        },
    }
    _write_text_atomic(
        artifact_dir / "manifest.json",
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    return artifact_dir


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
    if args.local_artifacts_dir and (args.output or args.events_output):
        parser.error(
            "--local-artifacts-dir writes both standard artifacts; do not combine "
            "it with --output or --events-output"
        )

    config_path = os.path.abspath(args.config)
    managed_worktree: ManagedWorktree | None = None
    artifact_dir: Path | None = None
    try:
        plan = _load_plan(args)
        load_config(config_path)
        run_cwd = os.getcwd()
        if args.local_artifacts_dir:
            managed_worktree = create_managed_worktree(run_cwd)
            run_cwd = os.fspath(managed_worktree.path)
        result = asyncio.run(
            run_swarm(
                args.goal,
                config_path,
                cwd=run_cwd,
                plan=plan,
            )
        )
        if managed_worktree is not None:
            artifact_dir = _write_local_artifacts(
                args.local_artifacts_dir,
                managed_worktree,
                result,
            )
            remove_managed_worktree(managed_worktree)
            managed_worktree = None
    except (OSError, ValueError, ConfigurationError, WorktreeError) as error:
        print(f"swarm error: {error}", file=sys.stderr)
        if managed_worktree is not None:
            recovery_path = (
                managed_worktree.path
                if managed_worktree.path.exists()
                else managed_worktree.temporary_root
            )
            print(
                f"managed run state retained for recovery: {recovery_path}",
                file=sys.stderr,
            )
        raise SystemExit(2) from error
    except BaseException:
        if managed_worktree is not None:
            recovery_path = (
                managed_worktree.path
                if managed_worktree.path.exists()
                else managed_worktree.temporary_root
            )
            print(
                f"managed run state retained for recovery: {recovery_path}",
                file=sys.stderr,
            )
        raise

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
        if artifact_dir is not None:
            print(f"\nArtifacts: {artifact_dir}")
            print("Managed worktree removed after artifact completion.")
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
