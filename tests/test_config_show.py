import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_swarm import cli as swarm
from agent_swarm.core.config import ConfigurationError, SwarmConfig
from agent_swarm.core.config_inspection import inspect_config, render_human


def config_data(command="fixture"):
    return {
        "providers": {
            "a": {"command": command, "enforced_access": "read_only"},
            "b": {"command": command, "enforced_access": "workspace_write"},
        },
        "overseer": {
            "provider": "a",
            "model": "planner",
            "role": "overseer",
            "strategy": "predict",
            "access": "read_only",
            "quality_tier": "high",
        },
        "workers": {
            "builder": {
                "provider": "b",
                "model": "builder-model",
                "role": "worker",
                "capabilities": ["implementation"],
                "strategy": "agentic",
                "access": "workspace_write",
                "quality_tier": "standard",
                "validation_retries": 0,
            },
            "reviewer": {
                "provider": "a",
                "model": "review-model",
                "role": "reviewer",
                "capabilities": ["review"],
                "strategy": "predict",
                "access": "read_only",
                "quality_tier": "high",
            },
        },
    }


class ConfigShowTests(unittest.TestCase):
    def test_normalized_output_is_deterministic_and_passive_by_default(self):
        config = SwarmConfig.from_dict(config_data())
        with (
            patch(
                "agent_swarm.core.config_inspection.shutil.which",
                return_value="/bin/fixture",
            ),
            patch("agent_swarm.core.config_inspection.subprocess.run") as run,
        ):
            first = inspect_config(config, "example.yaml")
            second = inspect_config(config, "example.yaml")
        self.assertEqual(first, second)
        self.assertEqual([item["name"] for item in first["providers"]], ["a", "b"])
        self.assertEqual(first["providers"][0]["duplicate_command_with"], ["b"])
        self.assertIn("bus_handoff_shape", first)
        run.assert_not_called()

    def test_version_probe_is_direct_bounded_and_deduplicated(self):
        config = SwarmConfig.from_dict(config_data())
        completed = subprocess.CompletedProcess("fixture", 0, "fixture 1.0\n", "")
        calls = []

        def run_probe(*args, **kwargs):
            calls.append((args, kwargs))
            return completed

        with patch(
            "agent_swarm.core.config_inspection.shutil.which",
            return_value="/bin/fixture",
        ):
            data = inspect_config(
                config,
                "example.yaml",
                probe_versions=True,
                run_probe=run_probe,
            )
        self.assertEqual(
            data["provider_version_probes"]["a"],
            {"status": "ok", "output": "fixture 1.0"},
        )
        self.assertEqual(
            data["provider_version_probes"]["b"],
            {"status": "duplicate_command", "same_as": "a"},
        )
        self.assertEqual(calls[0][0], (["/bin/fixture", "--version"],))
        self.assertFalse(calls[0][1]["shell"])
        self.assertEqual(calls[0][1]["timeout"], 2)

    def test_version_probe_timeout_is_safe_and_does_not_use_a_shell(self):
        config = SwarmConfig.from_dict(config_data())
        calls = []

        def run_probe(*args, **kwargs):
            calls.append((args, kwargs))
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

        with patch(
            "agent_swarm.core.config_inspection.shutil.which",
            return_value="/bin/fixture",
        ):
            data = inspect_config(
                config,
                "example.yaml",
                probe_versions=True,
                run_probe=run_probe,
            )

        self.assertEqual(
            data["provider_version_probes"]["a"],
            {"output": None, "status": "timeout"},
        )
        self.assertFalse(calls[0][1]["shell"])
        self.assertEqual(calls[0][1]["timeout"], 2)

    def test_provider_arguments_are_redacted_in_normalized_output(self):
        data = config_data()
        data["providers"]["a"]["args"] = [
            "--api-key=super-secret",
            "--token",
            "split-secret",
            "--client-secret='quoted-secret'",
            "--safe-flag",
            "benign-value",
        ]
        config = SwarmConfig.from_dict(data)

        rendered = inspect_config(config, "example.yaml")

        self.assertEqual(
            rendered["providers"][0]["args"],
            [
                "--api-key=<redacted>",
                "--token",
                "<redacted>",
                "--client-secret=<redacted>",
                "--safe-flag",
                "benign-value",
            ],
        )
        self.assertNotIn("super-secret", json.dumps(rendered))
        self.assertNotIn("split-secret", json.dumps(rendered))
        self.assertNotIn("quoted-secret", json.dumps(rendered))
        self.assertIn("benign-value", json.dumps(rendered))
        self.assertNotIn("super-secret", render_human(rendered))

    def test_missing_executable_and_nonzero_probe_are_safe(self):
        config = SwarmConfig.from_dict(config_data())
        with patch(
            "agent_swarm.core.config_inspection.shutil.which", return_value=None
        ):
            missing = inspect_config(config, "example.yaml", probe_versions=True)
        self.assertEqual(
            missing["provider_version_probes"]["a"]["status"], "missing_executable"
        )
        with patch(
            "agent_swarm.core.config_inspection.shutil.which",
            return_value="/bin/fixture",
        ):
            failed = inspect_config(
                config,
                "example.yaml",
                probe_versions=True,
                run_probe=lambda *args, **kwargs: subprocess.CompletedProcess(
                    "fixture", 9, "", "token=secret"
                ),
            )
        self.assertEqual(
            failed["provider_version_probes"]["a"]["status"], "nonzero_exit"
        )
        self.assertIn("<redacted>", failed["provider_version_probes"]["a"]["output"])

    def test_config_show_validates_before_display_and_json_is_machine_readable(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.yaml"
            path.write_text("providers: {}\n", encoding="utf-8")
            stderr = io.StringIO()
            with (
                patch.object(
                    sys, "argv", ["swarm", "config", "show", "--config", str(path)]
                ),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as error,
            ):
                swarm.main()
            self.assertEqual(error.exception.code, 2)
            self.assertIn("At least one provider", stderr.getvalue())

            import yaml

            path.write_text(yaml.safe_dump(config_data()), encoding="utf-8")
            stdout = io.StringIO()
            with (
                patch.object(
                    sys,
                    "argv",
                    ["swarm", "config", "show", "--config", str(path), "--json"],
                ),
                contextlib.redirect_stdout(stdout),
                patch.object(swarm, "run_swarm", side_effect=AssertionError),
            ):
                swarm.main()
            rendered = json.loads(stdout.getvalue())
            self.assertEqual(rendered["agents"]["overseer"]["model"], "planner")

    def test_config_show_normalizes_malformed_yaml_as_a_configuration_error(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.yaml"
            path.write_text("providers: [\n", encoding="utf-8")
            stderr = io.StringIO()
            with (
                patch.object(
                    sys, "argv", ["swarm", "config", "show", "--config", str(path)]
                ),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as error,
            ):
                swarm.main()
            self.assertEqual(error.exception.code, 2)
            self.assertIn("Invalid YAML", stderr.getvalue())

    def test_legacy_goal_parser_is_unchanged_for_non_command_config_goal(self):
        parser = swarm._legacy_parser()
        parsed = parser.parse_args(["config", "--json"])
        self.assertEqual(parsed.goal, "config")
        self.assertTrue(parsed.json)

    def test_invalid_configuration_still_raises_at_the_model_boundary(self):
        data = config_data()
        data["overseer"]["provider"] = "missing"
        with self.assertRaises(ConfigurationError):
            SwarmConfig.from_dict(data)


if __name__ == "__main__":
    unittest.main()
