from __future__ import annotations

import asyncio
import json
import math
import os
import signal
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.core.config import ProviderConfig
from src.providers.base import (
    ProviderError,
    ProviderResult,
    TokenUsage,
    redact_diagnostic,
)


def _integer(mapping: Mapping[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        if key not in mapping or mapping[key] is None:
            continue
        value = mapping[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ProviderError(
                f"Provider reported invalid non-negative integer for {key!r}"
            )
        return value
    return None


def _usage_from_event(event: Mapping[str, Any]) -> Optional[TokenUsage]:
    event_type = event.get("type")
    usage: Optional[Mapping[str, Any]] = None
    cost: Optional[float] = None
    if event_type == "turn.completed" and isinstance(event.get("usage"), dict):
        usage = event["usage"]
    elif event_type == "step_finish" and isinstance(event.get("part"), dict):
        part = event["part"]
        tokens = part.get("tokens")
        if isinstance(tokens, dict):
            usage = tokens
        if part.get("cost") is not None:
            raw_cost = part["cost"]
            if (
                isinstance(raw_cost, bool)
                or not isinstance(raw_cost, (int, float))
                or not math.isfinite(float(raw_cost))
                or raw_cost < 0
            ):
                raise ProviderError("Provider reported invalid cost telemetry")
            cost = float(raw_cost)
    if usage is None:
        return None

    cache = usage.get("cache") if isinstance(usage.get("cache"), dict) else {}
    input_tokens = _integer(usage, "input_tokens", "input", "prompt_tokens")
    cached_tokens = _integer(
        usage, "cached_input_tokens", "cache_read_input_tokens", "cache_read"
    )
    if cached_tokens is None:
        cached_tokens = _integer(cache, "read")
    output_tokens = _integer(usage, "output_tokens", "output", "completion_tokens")
    reasoning_tokens = _integer(
        usage, "reasoning_output_tokens", "reasoning_tokens", "reasoning"
    )
    cache_write = _integer(usage, "cache_write_input_tokens", "cache_write")
    if cache_write is None:
        cache_write = _integer(cache, "write")
    if input_tokens is None and output_tokens is None and cost is None:
        return None
    return TokenUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning_tokens,
        cache_write_input_tokens=cache_write,
        provider_reported_cost_usd=cost,
        source="provider",
    )


def _text_from_event(event: Mapping[str, Any]) -> Optional[str]:
    item = event.get("item")
    if isinstance(item, dict) and item.get("type") in {"agent_message", "message"}:
        text = item.get("text") or item.get("content")
        if isinstance(text, str):
            return text

    part = event.get("part")
    if (
        event.get("type") in {"text", "message", "agent_message"}
        and isinstance(part, dict)
        and part.get("type") not in {"reasoning", "thinking"}
    ):
        text = part.get("text")
        if isinstance(text, str):
            return text

    if event.get("type") in {"text", "message", "agent_message"}:
        text = event.get("text") or event.get("content")
        if isinstance(text, str):
            return text
    return None


def parse_jsonl_output(raw: str) -> Tuple[str, TokenUsage, int]:
    texts: List[str] = []
    usages: List[TokenUsage] = []
    seen_step_ids: set[str] = set()
    event_count = 0
    failures: List[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_count += 1
        if event.get("type") in {"error", "turn.failed"}:
            detail = event.get("error") or event.get("message") or event.get("part")
            failures.append(redact_diagnostic(str(detail), limit=500))
        text = _text_from_event(event)
        if text:
            texts.append(text)
        usage = _usage_from_event(event)
        if usage:
            part = event.get("part")
            part_id = part.get("id") if isinstance(part, dict) else None
            if event.get("type") == "step_finish" and part_id:
                if part_id in seen_step_ids:
                    continue
                seen_step_ids.add(part_id)
            usages.append(usage)

    def sum_known(attribute: str) -> Optional[int]:
        values = [getattr(usage, attribute) for usage in usages]
        known = [value for value in values if value is not None]
        return sum(known) if known else None

    costs = [
        usage.provider_reported_cost_usd
        for usage in usages
        if usage.provider_reported_cost_usd is not None
    ]
    aggregate = TokenUsage(
        input_tokens=sum_known("input_tokens"),
        cached_input_tokens=sum_known("cached_input_tokens"),
        output_tokens=sum_known("output_tokens"),
        reasoning_output_tokens=sum_known("reasoning_output_tokens"),
        cache_write_input_tokens=sum_known("cache_write_input_tokens"),
        provider_reported_cost_usd=sum(costs) if costs else None,
        source="provider" if usages else "unknown",
    )
    if failures:
        raise ProviderError(
            "Provider event reported failure: " + failures[-1],
            usage=aggregate if usages else None,
        )
    output = texts[-1].strip() if texts else ""
    return output, aggregate, event_count


class CLIProvider:
    """Shell-free adapter for a configured non-interactive agent CLI."""

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.name = config.name

    @staticmethod
    async def _terminate_process_group(process) -> None:
        if os.name == "posix" and getattr(process, "pid", None):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            except OSError:
                if process.returncode is None:
                    process.kill()
        else:
            if process.returncode is not None:
                return
            process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
            if os.name != "posix" or not getattr(process, "pid", None):
                return
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            return
        except asyncio.TimeoutError:
            pass
        if os.name == "posix" and getattr(process, "pid", None):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            except OSError:
                if process.returncode is None:
                    process.kill()
        else:
            process.kill()
        await process.wait()

    async def run(
        self,
        prompt: str,
        *,
        model: str,
        title: str,
        cwd: str,
    ) -> ProviderResult:
        values = {
            "model": model,
            "title": title,
            "cwd": os.path.abspath(cwd),
        }
        try:
            args = [argument.format_map(values) for argument in self.config.args]
        except KeyError as error:
            raise ProviderError(
                f"Provider {self.name!r} uses unknown argument placeholder {error}"
            ) from error

        started = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                self.config.command,
                *args,
                cwd=cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
        except FileNotFoundError as error:
            raise ProviderError(
                f"Provider executable not found: {self.config.command}"
            ) from error
        except OSError as error:
            raise ProviderError(
                f"Provider {self.name!r} could not start: "
                f"{redact_diagnostic(str(error), limit=500)}"
            ) from error

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(prompt.encode("utf-8")),
                timeout=self.config.timeout_seconds,
            )
        except asyncio.TimeoutError as error:
            await asyncio.shield(self._terminate_process_group(process))
            raise ProviderError(
                f"Provider {self.name!r} timed out after "
                f"{self.config.timeout_seconds}s",
                transient=True,
                duration_seconds=time.monotonic() - started,
            ) from error
        except asyncio.CancelledError:
            await asyncio.shield(self._terminate_process_group(process))
            raise

        duration = time.monotonic() - started
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            detail = redact_diagnostic(stderr_text or stdout_text or "no output")
            partial_usage = None
            if self.config.output_format in {"jsonl", "codex-jsonl", "opencode-jsonl"}:
                try:
                    _, partial_usage, _ = parse_jsonl_output(stdout_text)
                except ProviderError as parsed_error:
                    partial_usage = parsed_error.usage
            raise ProviderError(
                f"Provider {self.name!r} exited {process.returncode}: {detail}",
                transient=process.returncode in {75, 124, 137},
                usage=partial_usage,
                duration_seconds=duration,
            )

        if self.config.output_format in {"jsonl", "codex-jsonl", "opencode-jsonl"}:
            output, usage, event_count = parse_jsonl_output(stdout_text)
        else:
            output, usage, event_count = stdout_text.strip(), TokenUsage(), 0
        if not output:
            raise ProviderError(
                f"Provider {self.name!r} returned no agent output: "
                f"{redact_diagnostic(stderr_text, limit=500)}"
            )
        return ProviderResult(
            output=output,
            usage=usage,
            provider=self.name,
            model=model,
            duration_seconds=duration,
            raw_event_count=event_count,
        )


def build_providers(
    configs: Mapping[str, ProviderConfig],
) -> Dict[str, CLIProvider]:
    return {name: CLIProvider(config) for name, config in configs.items()}
