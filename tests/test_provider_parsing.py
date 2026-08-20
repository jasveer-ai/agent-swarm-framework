import asyncio
import json
import os
import signal
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.core.config import ProviderConfig
from src.providers.base import ProviderError, TokenUsage
from src.providers.cli import CLIProvider, parse_jsonl_output


class ProviderParsingTests(unittest.TestCase):
    def test_codex_jsonl_uses_final_message_and_sums_completed_turns(self):
        events = [
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "draft"},
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 20,
                    "output_tokens": 30,
                    "reasoning_output_tokens": 7,
                },
            },
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "final"},
            },
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 40, "output_tokens": 10},
            },
        ]

        output, usage, count = parse_jsonl_output(
            "\n".join(json.dumps(event) for event in events)
        )

        self.assertEqual(output, "final")
        self.assertEqual(count, 4)
        self.assertEqual(usage.input_tokens, 140)
        self.assertEqual(usage.cached_input_tokens, 20)
        self.assertEqual(usage.output_tokens, 40)
        self.assertEqual(usage.reasoning_output_tokens, 7)

    def test_opencode_step_finish_deduplicates_part_ids_and_keeps_cost(self):
        events = [
            {"type": "text", "part": {"text": "result"}},
            {
                "type": "step_finish",
                "part": {
                    "id": "step-1",
                    "cost": 0.02,
                    "tokens": {
                        "input": 200,
                        "output": 50,
                        "reasoning": 10,
                        "cache": {"read": 40, "write": 5},
                    },
                },
            },
            {
                "type": "step_finish",
                "part": {
                    "id": "step-1",
                    "cost": 0.02,
                    "tokens": {"input": 200, "output": 50},
                },
            },
        ]

        output, usage, _ = parse_jsonl_output(
            "\n".join(json.dumps(event) for event in events)
        )

        self.assertEqual(output, "result")
        self.assertEqual(usage.input_tokens, 200)
        self.assertEqual(usage.output_tokens, 50)
        self.assertEqual(usage.cached_input_tokens, 40)
        self.assertEqual(usage.cache_write_input_tokens, 5)
        self.assertAlmostEqual(usage.provider_reported_cost_usd, 0.02)

    def test_error_event_fails_and_redacts_token(self):
        raw = json.dumps(
            {
                "type": "turn.failed",
                "error": "Authorization: Bearer secret-value",
            }
        )

        with self.assertRaisesRegex(ProviderError, "<redacted>") as raised:
            parse_jsonl_output(raw)
        self.assertNotIn("secret-value", str(raised.exception))

    def test_json_error_event_redacts_structured_secrets(self):
        raw = json.dumps(
            {
                "type": "error",
                "error": {
                    "token": "token-value",
                    "api_key": "key-value",
                    "nested": {"password": "password-value"},
                },
            }
        )

        with self.assertRaises(ProviderError) as raised:
            parse_jsonl_output(raw)
        rendered = str(raised.exception)
        self.assertNotIn("token-value", rendered)
        self.assertNotIn("key-value", rendered)
        self.assertNotIn("password-value", rendered)

    def test_reasoning_parts_are_not_returned_as_agent_output(self):
        raw = json.dumps(
            {
                "type": "reasoning",
                "part": {"type": "reasoning", "text": "hidden reasoning"},
            }
        )

        output, _, _ = parse_jsonl_output(raw)

        self.assertEqual(output, "")
        self.assertNotIn("hidden reasoning", output)

    def test_invalid_provider_usage_is_rejected(self):
        with self.assertRaisesRegex(ProviderError, "invalid"):
            parse_jsonl_output(
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": -1, "output_tokens": 2},
                    }
                )
            )
        with self.assertRaisesRegex(ValueError, "finite"):
            TokenUsage(provider_reported_cost_usd=float("nan"))


class CLIProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_is_sent_on_stdin_and_never_interpreted_as_argv(self):
        process = Mock()
        process.returncode = 0
        process.communicate = AsyncMock(return_value=(b"done", b""))
        process.kill = Mock()
        provider = CLIProvider(
            ProviderConfig(
                name="fixture",
                command="agent-cli",
                args=("run", "--model", "{model}", "--title", "{title}"),
                prompt_mode="stdin",
                output_format="text",
            )
        )
        prompt = "$(touch /tmp/should-not-exist)"

        with patch(
            "src.providers.cli.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ) as create:
            result = await provider.run(
                prompt,
                model="fixture-model",
                title="fixture title",
                cwd=".",
            )

        argv = create.await_args.args
        self.assertEqual(argv[:3], ("agent-cli", "run", "--model"))
        self.assertNotIn(prompt, argv)
        process.communicate.assert_awaited_once_with(prompt.encode("utf-8"))
        self.assertEqual(result.output, "done")
        self.assertEqual(
            create.await_args.kwargs["start_new_session"], os.name == "posix"
        )

    async def test_cancellation_terminates_and_reaps_provider_process_group(self):
        blocker = asyncio.Event()

        async def communicate(_input=None):
            await blocker.wait()
            return b"", b""

        process = Mock()
        process.pid = 4242
        process.returncode = None
        process.communicate = AsyncMock(side_effect=communicate)
        process.wait = AsyncMock(return_value=0)
        process.kill = Mock()
        provider = CLIProvider(
            ProviderConfig(
                name="fixture",
                command="agent-cli",
                args=("run",),
                prompt_mode="stdin",
                output_format="text",
            )
        )

        with (
            patch(
                "src.providers.cli.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            patch("src.providers.cli.os.killpg") as kill_group,
        ):
            task = asyncio.create_task(
                provider.run("prompt", model="model", title="title", cwd=".")
            )
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        if os.name == "posix":
            self.assertEqual(
                kill_group.call_args_list[0].args,
                (4242, signal.SIGTERM),
            )
            self.assertEqual(
                kill_group.call_args_list[-1].args,
                (4242, signal.SIGKILL),
            )
        else:
            process.kill.assert_called_once()
        process.wait.assert_awaited()

    async def test_cleanup_signals_group_after_leader_already_exited(self):
        process = Mock()
        process.pid = 4242
        process.returncode = 0
        process.wait = AsyncMock(return_value=0)
        process.kill = Mock()

        with patch("src.providers.cli.os.killpg") as kill_group:
            await CLIProvider._terminate_process_group(process)

        if os.name == "posix":
            self.assertEqual(
                [call.args for call in kill_group.call_args_list],
                [(4242, signal.SIGTERM), (4242, signal.SIGKILL)],
            )
        else:
            process.kill.assert_not_called()

    async def test_cleanup_ignores_final_group_signal_permission_error(self):
        if os.name != "posix":
            self.skipTest("process-group signals are POSIX-only")
        process = Mock()
        process.pid = 4242
        process.returncode = 0
        process.wait = AsyncMock(return_value=0)
        process.kill = Mock()

        with patch(
            "src.providers.cli.os.killpg",
            side_effect=[None, PermissionError("group already terminated")],
        ):
            await CLIProvider._terminate_process_group(process)

        process.wait.assert_awaited()
        process.kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
