import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_swarm import cli as swarm
from agent_swarm.core.run import RunRecord, SwarmRunResult


class RunArtifactTests(unittest.TestCase):
    def test_events_are_ndjson_and_snapshot_remains_one_json_document(self):
        events = (
            {"sequence": 1, "topic": "run.request", "message": {"id": "one"}},
            {"sequence": 2, "topic": "run.completed", "message": {"id": "two"}},
        )
        record = RunRecord(goal="Inspect")
        result = SwarmRunResult(final_output="done", record=record, events=events)

        snapshot = json.loads(result.to_json())
        event_rows = [
            json.loads(line) for line in result.events_to_ndjson().splitlines()
        ]

        self.assertEqual(snapshot["final_output"], "done")
        self.assertEqual(event_rows, list(events))
        self.assertEqual([row["sequence"] for row in event_rows], [1, 2])

    def test_ndjson_falls_back_to_embedded_history_for_compatibility(self):
        record = RunRecord(
            goal="Inspect",
            bus_history=[
                {"sequence": 1, "topic": "run.completed", "message": {"id": "one"}}
            ],
        )

        rows = SwarmRunResult("done", record).events_to_ndjson().splitlines()

        self.assertEqual(json.loads(rows[0])["sequence"], 1)

    def test_atomic_writer_replaces_the_complete_artifact(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "run.events.ndjson"
            path.write_text("old\n", encoding="utf-8")

            swarm._write_text_atomic(path, '{"sequence":1}\n')

            self.assertEqual(path.read_text(encoding="utf-8"), '{"sequence":1}\n')
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_atomic_writer_preserves_previous_artifacts_when_replace_fails(self):
        with TemporaryDirectory() as temporary:
            for filename in ("run.json", "run.events.ndjson"):
                with self.subTest(filename=filename):
                    path = Path(temporary) / filename
                    path.write_text("previous\n", encoding="utf-8")

                    with (
                        patch(
                            "agent_swarm.cli.os.replace",
                            side_effect=OSError("interrupted before replace"),
                        ),
                        self.assertRaises(OSError),
                    ):
                        swarm._write_text_atomic(path, "replacement\n")

                    self.assertEqual(path.read_text(encoding="utf-8"), "previous\n")
                    self.assertEqual(
                        list(path.parent.glob(f".{path.name}.*.tmp")), []
                    )

    def test_cli_rejects_one_path_for_both_artifact_formats(self):
        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as error,
        ):
            swarm._run_legacy(
                [
                    "Inspect",
                    "--output",
                    "run.json",
                    "--events-output",
                    "run.json",
                ]
            )

        self.assertEqual(error.exception.code, 2)
        self.assertIn("must use different paths", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
