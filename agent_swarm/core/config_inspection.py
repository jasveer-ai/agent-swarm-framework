"""Passive, deterministic rendering of validated swarm configuration."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agent_swarm.core.config import AgentProfile, ProviderConfig, SwarmConfig
from agent_swarm.providers.base import redact_diagnostic

_PROBE_TIMEOUT_SECONDS = 2
_PROBE_OUTPUT_LIMIT = 240
_SECRET_OPTION_NAMES = {
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "authorization",
    "bearer_token",
    "client_secret",
    "github_token",
    "password",
    "secret",
    "token",
}


def _is_secret_option(argument: str) -> bool:
    option = argument.lstrip("-").split("=", 1)[0]
    normalized = re.sub(r"[-_]", "_", option).lower()
    return normalized in _SECRET_OPTION_NAMES


def _redact_arguments(arguments: tuple[str, ...]) -> list[str]:
    """Redact both ``--secret=value`` and ``--secret value`` CLI forms."""

    redacted: list[str] = []
    redact_next = False
    for argument in arguments:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        if _is_secret_option(argument):
            if "=" in argument:
                option, _ = argument.split("=", 1)
                redacted.append(f"{option}=<redacted>")
            else:
                redacted.append(argument)
                redact_next = True
            continue
        redacted.append(redact_diagnostic(argument))
    return redacted


def _resolved_executable(command: str) -> str | None:
    """Return an absolute executable path without starting a process."""

    found = shutil.which(command)
    return os.path.realpath(found) if found else None


def _agent_view(profile: AgentProfile) -> dict[str, Any]:
    return {
        "access": profile.access,
        "capabilities": list(profile.capabilities),
        "cost_rank": profile.cost_rank,
        "id": profile.agent_id,
        "identity": profile.identity,
        "max_output_tokens": profile.max_output_tokens,
        "model": profile.model,
        "provider": profile.provider,
        "quality_tier": profile.quality_tier,
        "role": profile.role,
        "strategy": profile.strategy,
        "validation_retries": profile.validation_retries,
    }


def _provider_view(
    name: str, provider: ProviderConfig, resolved: str | None, duplicates: list[str]
) -> dict[str, Any]:
    return {
        "args": _redact_arguments(provider.args),
        "command": provider.command,
        "duplicate_command_with": duplicates,
        "enforced_access": provider.enforced_access,
        "name": name,
        "output_format": provider.output_format,
        "pricing": (
            None
            if provider.pricing is None
            else {
                "cached_input_per_million_usd": (
                    provider.pricing.cached_input_per_million_usd
                ),
                "input_per_million_usd": provider.pricing.input_per_million_usd,
                "output_per_million_usd": provider.pricing.output_per_million_usd,
            }
        ),
        "prompt_mode": provider.prompt_mode,
        "resolved_executable": resolved,
        "timeout_seconds": provider.timeout_seconds,
    }


def _probe(
    executable: str | None,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, str | int | None]:
    if executable is None:
        return {"output": None, "status": "missing_executable"}
    try:
        completed = run(
            [executable, "--version"],
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"output": None, "status": "timeout"}
    except OSError as error:
        return {
            "output": redact_diagnostic(str(error), limit=_PROBE_OUTPUT_LIMIT),
            "status": "execution_error",
        }

    output = (completed.stdout or completed.stderr or "").replace("\n", " ")
    output = " ".join(output.split())
    result: dict[str, str | int | None] = {
        "output": redact_diagnostic(output, limit=_PROBE_OUTPUT_LIMIT) or None,
        "status": "ok" if completed.returncode == 0 else "nonzero_exit",
    }
    if completed.returncode != 0:
        result["returncode"] = completed.returncode
    return result


def inspect_config(
    config: SwarmConfig,
    config_path: str | Path,
    *,
    probe_versions: bool = False,
    run_probe: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Produce a JSON-safe view without invoking providers by default."""

    ordered_providers = sorted(config.providers.items())
    resolutions = {
        name: _resolved_executable(provider.command)
        for name, provider in ordered_providers
    }
    command_groups: dict[str, list[str]] = {}
    for name, provider in ordered_providers:
        key = resolutions[name] or f"command:{provider.command}"
        command_groups.setdefault(key, []).append(name)

    providers = []
    probes: dict[str, dict[str, str | int | None]] = {}
    for name, provider in ordered_providers:
        key = resolutions[name] or f"command:{provider.command}"
        peers = command_groups[key]
        providers.append(
            _provider_view(
                name,
                provider,
                resolutions[name],
                [peer for peer in peers if peer != name],
            )
        )
        if probe_versions:
            leader = peers[0]
            if name == leader:
                probes[name] = _probe(resolutions[name], run_probe)
            else:
                probes[name] = {"same_as": leader, "status": "duplicate_command"}

    result: dict[str, Any] = {
        "agents": {
            "overseer": _agent_view(config.overseer),
            "workers_and_reviewers": [
                _agent_view(profile)
                for profile in sorted(config.workers, key=lambda item: item.agent_id)
            ],
        },
        "budgets": {
            "max_concurrency": config.budgets.max_concurrency,
            "max_estimated_cost_usd": config.budgets.max_estimated_cost_usd,
            "max_provider_calls": config.budgets.max_provider_calls,
            "max_total_tokens": config.budgets.max_total_tokens,
            "provider_retry_limit": config.budgets.provider_retry_limit,
        },
        "bus_handoff_shape": {
            "envelope_fields": [
                "id",
                "run_id",
                "task_id",
                "correlation_id",
                "causation_id",
                "sender_id",
                "receiver_id",
                "type",
                "payload",
                "metadata",
            ],
            "flows": [
                "caller -> overseer: run.request",
                "overseer -> swarm: plan.created",
                "overseer -> worker: task.assigned",
                "worker -> overseer: task.result | task.failed",
                "overseer -> reviewer: review.request (when required)",
                "reviewer -> overseer: review.result (when required)",
                "swarm -> overseer: run.aggregated",
                "overseer -> caller: run.completed",
            ],
        },
        "config_path": str(Path(config_path).resolve()),
        "output_history": {
            "include_bus_history": config.output.include_bus_history,
            "include_conversations": config.output.include_conversations,
        },
        "providers": providers,
        "routing_rules": [
            {"capabilities": list(rule.capabilities), "keywords": list(rule.keywords)}
            for rule in config.routing_rules
        ],
        "verification": {
            "complexities": list(config.verification.complexities),
            "enabled": config.verification.enabled,
        },
    }
    if probe_versions:
        result["provider_version_probes"] = probes
    return result


def render_human(data: Mapping[str, Any]) -> str:
    """Render the normalized document for terminal inspection."""

    lines = [f"Validated swarm configuration: {data['config_path']}", "", "Providers:"]
    for provider in data["providers"]:
        resolved = provider["resolved_executable"] or "not found"
        duplicate = provider["duplicate_command_with"]
        suffix = f"; shared with {', '.join(duplicate)}" if duplicate else ""
        lines.append(
            f"- {provider['name']}: {provider['command']} -> {resolved}; "
            f"enforced access={provider['enforced_access']}{suffix}"
        )
    agents = data["agents"]
    lines.extend(["", "Agents:"])
    for profile in [agents["overseer"], *agents["workers_and_reviewers"]]:
        capabilities = ", ".join(profile["capabilities"]) or "none"
        lines.append(
            f"- {profile['id']} ({profile['role']}): {profile['provider']}/"
            f"{profile['model']}; capabilities={capabilities}; "
            f"access={profile['access']}; "
            f"quality={profile['quality_tier']}; cost rank={profile['cost_rank']}; "
            f"strategy={profile['strategy']}"
        )
    lines.extend(["", "Routing rules:"])
    for rule in data["routing_rules"]:
        lines.append(
            f"- {', '.join(rule['keywords'])} -> {', '.join(rule['capabilities'])}"
        )
    lines.extend(
        [
            "",
            f"Budgets: {data['budgets']}",
            f"Verification: {data['verification']}",
            f"Output history: {data['output_history']}",
            "",
            "Bus-mediated handoff:",
        ]
    )
    lines.extend(f"- {flow}" for flow in data["bus_handoff_shape"]["flows"])
    if "provider_version_probes" in data:
        lines.extend(["", "Provider version probes:"])
        for name, result in data["provider_version_probes"].items():
            lines.append(f"- {name}: {result}")
    return "\n".join(lines)
