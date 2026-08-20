import contextlib
import hashlib
import io
import json
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from agent_swarm import cli as swarm
from agent_swarm.core.run import RunRecord, SwarmRunResult
from agent_swarm.core.worktree import (
    WorktreeError,
    create_managed_worktree,
    remove_managed_worktree,
)


def git(cwd: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def initialize_repository(path: Path) -> None:
    path.mkdir()
    git(path, "init", "--quiet")
    git(path, "config", "user.name", "Fixture")
    git(path, "config", "user.email", "fixture@example.invalid")
    (path / "tracked.txt").write_text("before\n", encoding="utf-8")
    git(path, "add", "tracked.txt")
    git(path, "commit", "--quiet", "-m", "initial")


def successful_result() -> SwarmRunResult:
    record = RunRecord(goal="Build")
    record.finish("succeeded")
    events = (
        {"sequence": 1, "topic": "run.completed", "message": {"id": "done"}},
    )
    return SwarmRunResult("done", record, events)


class LocalWorktreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config_path = (
            Path(__file__).resolve().parents[1] / ".swarm" / "config.yaml"
        )

    def test_local_run_persists_complete_artifacts_then_removes_worktree(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            artifacts = root / "artifacts"
            initialize_repository(repository)
            managed_paths: list[Path] = []

            async def fake_run(*args, **kwargs):
                worktree_path = Path(kwargs["cwd"])
                managed_paths.append(worktree_path)
                (worktree_path / "tracked.txt").write_text(
                    "after\n", encoding="utf-8"
                )
                (worktree_path / "new.bin").write_bytes(b"\x00\x01artifact")
                (worktree_path / "empty.txt").touch()
                return successful_result()

            stdout = io.StringIO()
            with (
                patch("agent_swarm.cli.os.getcwd", return_value=str(repository)),
                patch("agent_swarm.cli.run_swarm", new=AsyncMock(side_effect=fake_run)),
                contextlib.redirect_stdout(stdout),
                self.assertRaises(SystemExit) as exit_error,
            ):
                swarm._run_legacy(
                    [
                        "Build",
                        "--config",
                        str(self.config_path),
                        "--local-artifacts-dir",
                        str(artifacts),
                        "--json",
                    ]
                )

            self.assertEqual(exit_error.exception.code, 0)
            self.assertEqual(len(managed_paths), 1)
            self.assertFalse(managed_paths[0].exists())
            listed_worktrees = git(repository, "worktree", "list", "--porcelain")
            self.assertNotIn("agent-swarm-run-", listed_worktrees)

            artifact_dirs = list(artifacts.iterdir())
            self.assertEqual(len(artifact_dirs), 1)
            artifact_dir = artifact_dirs[0]
            manifest = json.loads(
                (artifact_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["run_status"], "succeeded")
            self.assertEqual(
                set(manifest["artifacts"]),
                {"run", "events", "workspace_patch"},
            )
            for artifact in manifest["artifacts"].values():
                content = (artifact_dir / artifact["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(), artifact["sha256"])
            workspace_patch = artifact_dir / "workspace.patch"
            self.assertTrue(workspace_patch.is_file())
            self.assertIn("tracked.txt", workspace_patch.read_text(errors="replace"))
            self.assertIn("new.bin", workspace_patch.read_text(errors="replace"))
            self.assertIn("empty.txt", workspace_patch.read_text(errors="replace"))

            restored = root / "restored"
            git(root, "clone", "--quiet", str(repository), str(restored))
            git(restored, "apply", "--binary", str(workspace_patch))
            self.assertEqual(
                (restored / "tracked.txt").read_text(encoding="utf-8"), "after\n"
            )
            self.assertEqual(
                (restored / "new.bin").read_bytes(), b"\x00\x01artifact"
            )
            self.assertTrue((restored / "empty.txt").is_file())

    def test_artifact_failure_retains_managed_worktree_for_recovery(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            artifacts = root / "artifacts"
            initialize_repository(repository)
            managed_paths: list[Path] = []

            async def fake_run(*args, **kwargs):
                worktree_path = Path(kwargs["cwd"])
                managed_paths.append(worktree_path)
                (worktree_path / "tracked.txt").write_text(
                    "recover me\n", encoding="utf-8"
                )
                return successful_result()

            stderr = io.StringIO()
            with (
                patch("agent_swarm.cli.os.getcwd", return_value=str(repository)),
                patch("agent_swarm.cli.run_swarm", new=AsyncMock(side_effect=fake_run)),
                patch(
                    "agent_swarm.cli._write_bytes_atomic",
                    side_effect=OSError("artifact disk unavailable"),
                ),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as exit_error,
            ):
                swarm._run_legacy(
                    [
                        "Build",
                        "--config",
                        str(self.config_path),
                        "--local-artifacts-dir",
                        str(artifacts),
                    ]
                )

            self.assertEqual(exit_error.exception.code, 2)
            self.assertEqual(len(managed_paths), 1)
            self.assertTrue(managed_paths[0].exists())
            self.assertIn(
                f"managed run state retained for recovery: {managed_paths[0]}",
                stderr.getvalue(),
            )
            partial_directories = list(artifacts.iterdir())
            self.assertEqual(len(partial_directories), 1)
            self.assertFalse((partial_directories[0] / "manifest.json").exists())
            git(repository, "worktree", "remove", "--force", str(managed_paths[0]))
            managed_paths[0].parent.rmdir()

    def test_unexpected_failure_reports_and_retains_managed_worktree(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            initialize_repository(repository)
            managed_paths: list[Path] = []

            async def fake_run(*args, **kwargs):
                managed_paths.append(Path(kwargs["cwd"]))
                raise RuntimeError("unexpected framework failure")

            stderr = io.StringIO()
            with (
                patch("agent_swarm.cli.os.getcwd", return_value=str(repository)),
                patch("agent_swarm.cli.run_swarm", new=AsyncMock(side_effect=fake_run)),
                contextlib.redirect_stderr(stderr),
                self.assertRaisesRegex(RuntimeError, "unexpected framework failure"),
            ):
                swarm._run_legacy(
                    [
                        "Build",
                        "--config",
                        str(self.config_path),
                        "--local-artifacts-dir",
                        str(root / "artifacts"),
                    ]
                )

            self.assertEqual(len(managed_paths), 1)
            self.assertTrue(managed_paths[0].exists())
            self.assertIn(
                f"managed run state retained for recovery: {managed_paths[0]}",
                stderr.getvalue(),
            )
            git(repository, "worktree", "remove", "--force", str(managed_paths[0]))
            managed_paths[0].parent.rmdir()

    def test_dirty_source_is_rejected_before_creating_worktree(self):
        with TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            initialize_repository(repository)
            (repository / "tracked.txt").write_text("dirty\n", encoding="utf-8")

            with self.assertRaisesRegex(WorktreeError, "clean source checkout"):
                create_managed_worktree(repository)

            self.assertNotIn(
                "agent-swarm-run-",
                git(repository, "worktree", "list", "--porcelain"),
            )

    def test_worktree_commands_ignore_inherited_git_repository_context(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            unrelated = root / "unrelated"
            initialize_repository(repository)
            initialize_repository(unrelated)

            with patch.dict(
                os.environ,
                {
                    "GIT_DIR": str(unrelated / ".git"),
                    "GIT_WORK_TREE": ".",
                    "GIT_DIFF_TOOL": "vscode",
                },
                clear=False,
            ):
                worktree = create_managed_worktree(repository)

            self.assertEqual(worktree.source_root, repository.resolve())
            remove_managed_worktree(worktree)

    def test_remove_reports_leftover_temporary_directory(self):
        with TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            initialize_repository(repository)
            worktree = create_managed_worktree(repository)
            leftover = worktree.temporary_root / "leftover.txt"
            leftover.write_text("unexpected", encoding="utf-8")

            with self.assertRaisesRegex(WorktreeError, "temporary directory remains"):
                remove_managed_worktree(worktree)

            self.assertFalse(worktree.path.exists())
            leftover.unlink()
            worktree.temporary_root.rmdir()


if __name__ == "__main__":
    unittest.main()
