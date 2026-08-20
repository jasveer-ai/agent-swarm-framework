from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from agent_swarm.core.environment import subprocess_environment


class WorktreeError(RuntimeError):
    """Raised when a managed local worktree cannot be created or finalized."""


@dataclass(frozen=True)
class ManagedWorktree:
    source_root: Path
    path: Path
    temporary_root: Path
    base_commit: str


def _git(
    cwd: str | Path,
    arguments: Sequence[str],
    *,
    allowed_returncodes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        ["git", "-C", os.fspath(cwd), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=subprocess_environment(),
    )
    if completed.returncode not in allowed_returncodes:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()
        raise WorktreeError(diagnostic or "git command failed")
    return completed


def create_managed_worktree(cwd: str | Path) -> ManagedWorktree:
    """Create a detached temporary worktree from a clean source checkout."""

    source_root = Path(
        os.fsdecode(_git(cwd, ("rev-parse", "--show-toplevel")).stdout).strip()
    ).resolve()
    status = _git(
        source_root,
        ("status", "--porcelain=v1", "--untracked-files=all", "-z"),
    ).stdout
    if status:
        raise WorktreeError(
            "local ephemeral runs require a clean source checkout so the worktree "
            "starts from a complete, unambiguous revision"
        )

    base_commit = os.fsdecode(
        _git(source_root, ("rev-parse", "HEAD")).stdout
    ).strip()
    temporary_root = Path(tempfile.mkdtemp(prefix="agent-swarm-run-"))
    worktree_path = temporary_root / "worktree"
    try:
        _git(
            source_root,
            ("worktree", "add", "--detach", os.fspath(worktree_path), base_commit),
        )
    except BaseException:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise
    return ManagedWorktree(
        source_root=source_root,
        path=worktree_path,
        temporary_root=temporary_root,
        base_commit=base_commit,
    )


def workspace_status(worktree: ManagedWorktree) -> tuple[str, ...]:
    """Return stable porcelain entries for the managed checkout."""

    raw = _git(
        worktree.path,
        ("status", "--porcelain=v1", "--untracked-files=all", "-z"),
    ).stdout
    return tuple(
        os.fsdecode(entry) for entry in raw.split(b"\0") if entry
    )


def capture_workspace_patch(worktree: ManagedWorktree) -> bytes:
    """Capture tracked and non-ignored untracked changes as one binary Git patch."""

    patch = bytearray(
        _git(
            worktree.path,
            (
                "diff",
                "HEAD",
                "--binary",
                "--full-index",
                "--no-ext-diff",
                "--src-prefix=a/",
                "--dst-prefix=b/",
            ),
        ).stdout
    )
    untracked = _git(
        worktree.path,
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ).stdout
    for raw_path in (value for value in untracked.split(b"\0") if value):
        relative_path = os.fsdecode(raw_path)
        addition = _git(
            worktree.path,
            (
                "diff",
                "--no-index",
                "--binary",
                "--full-index",
                "--no-ext-diff",
                "--src-prefix=a/",
                "--dst-prefix=b/",
                "--",
                "/dev/null",
                relative_path,
            ),
            allowed_returncodes=(0, 1),
        ).stdout
        if patch and addition and not patch.endswith(b"\n"):
            patch.extend(b"\n")
        patch.extend(addition)
    return bytes(patch)


def remove_managed_worktree(worktree: ManagedWorktree) -> None:
    """Remove a worktree only after its caller has persisted all artifacts."""

    _git(
        worktree.source_root,
        ("worktree", "remove", "--force", os.fspath(worktree.path)),
    )
    try:
        worktree.temporary_root.rmdir()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise WorktreeError(
            f"worktree was removed but temporary directory remains: "
            f"{worktree.temporary_root}: {error}"
        ) from error
