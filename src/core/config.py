from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Pricing:
    input_per_million_usd: float
    cached_input_per_million_usd: float
    output_per_million_usd: float


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    command: str
    args: Tuple[str, ...]
    prompt_mode: str = "stdin"
    output_format: str = "text"
    timeout_seconds: int = 300
    enforced_access: str = "unrestricted"
    pricing: Optional[Pricing] = None

    @classmethod
    def from_dict(cls, name: str, data: Mapping[str, Any]) -> "ProviderConfig":
        prompt_mode = str(data.get("prompt_mode", "stdin"))
        if prompt_mode != "stdin":
            raise ConfigurationError(f"Provider {name!r} prompt_mode must be 'stdin'")
        pricing_data = data.get("pricing")
        pricing = None
        if isinstance(pricing_data, dict):
            pricing = Pricing(
                input_per_million_usd=float(pricing_data["input_per_million_usd"]),
                cached_input_per_million_usd=float(
                    pricing_data.get(
                        "cached_input_per_million_usd",
                        pricing_data["input_per_million_usd"],
                    )
                ),
                output_per_million_usd=float(pricing_data["output_per_million_usd"]),
            )
            rates = (
                pricing.input_per_million_usd,
                pricing.cached_input_per_million_usd,
                pricing.output_per_million_usd,
            )
            if any(not math.isfinite(rate) or rate < 0 for rate in rates):
                raise ConfigurationError(
                    f"Provider {name!r} pricing rates must be finite and non-negative"
                )
        enforced_access = str(data.get("enforced_access", "unrestricted"))
        if enforced_access not in {"read_only", "workspace_write", "unrestricted"}:
            raise ConfigurationError(
                f"Provider {name!r} enforced_access must be read_only, "
                "workspace_write, or unrestricted"
            )
        values = cls(
            name=name,
            command=str(data["command"]),
            args=tuple(str(value) for value in data.get("args", [])),
            prompt_mode=prompt_mode,
            output_format=str(data.get("output_format", "text")),
            timeout_seconds=int(data.get("timeout_seconds", 300)),
            enforced_access=enforced_access,
            pricing=pricing,
        )
        if values.timeout_seconds < 1:
            raise ConfigurationError(
                f"Provider {name!r} timeout_seconds must be positive"
            )
        if not values.command.strip():
            raise ConfigurationError(f"Provider {name!r} command must not be empty")
        if any("{prompt" in argument for argument in values.args):
            raise ConfigurationError(
                f"Provider {name!r} must receive prompts only through standard input"
            )
        if (
            Path(values.command).name == "codex"
            and values.enforced_access != "unrestricted"
        ):
            unsafe_flags = {
                "--dangerously-bypass-approvals-and-sandbox",
                "--dangerously-bypass-hook-trust",
            }
            if any(argument in unsafe_flags for argument in values.args):
                raise ConfigurationError(
                    f"Bounded Codex provider {name!r} cannot use dangerous bypass flags"
                )
            if any(
                argument == "--add-dir" or argument.startswith("--add-dir=")
                for argument in values.args
            ):
                raise ConfigurationError(
                    f"Bounded Codex provider {name!r} cannot add writable directories"
                )
            for index, argument in enumerate(values.args):
                if argument in {"-c", "--config"}:
                    override = (
                        values.args[index + 1] if index + 1 < len(values.args) else ""
                    )
                    if "sandbox" in override.lower():
                        raise ConfigurationError(
                            f"Bounded Codex provider {name!r} cannot override sandbox config"
                        )
                elif argument.startswith("--config=") and "sandbox" in argument.lower():
                    raise ConfigurationError(
                        f"Bounded Codex provider {name!r} cannot override sandbox config"
                    )

            sandboxes = []
            index = 0
            while index < len(values.args):
                argument = values.args[index]
                if argument in {"--sandbox", "-s"}:
                    if index + 1 >= len(values.args):
                        raise ConfigurationError(
                            f"Codex provider {name!r} has an incomplete sandbox flag"
                        )
                    sandboxes.append(values.args[index + 1])
                    index += 2
                    continue
                if argument.startswith("--sandbox=") or argument.startswith("-s="):
                    sandboxes.append(argument.split("=", 1)[1])
                index += 1
            if len(sandboxes) != 1:
                raise ConfigurationError(
                    f"Codex provider {name!r} must pass exactly one explicit sandbox"
                )
            sandbox = sandboxes[0]
            expected_sandbox = {
                "read_only": "read-only",
                "workspace_write": "workspace-write",
            }[values.enforced_access]
            if sandbox != expected_sandbox:
                raise ConfigurationError(
                    f"Codex provider {name!r} declares {values.enforced_access!r} "
                    f"but configures sandbox {sandbox!r}"
                )
        return values


@dataclass(frozen=True)
class AgentProfile:
    agent_id: str
    identity: str
    role: str
    provider: str
    model: str
    capabilities: Tuple[str, ...] = ()
    strategy: str = "predict"
    access: str = "read_only"
    quality_tier: str = "standard"
    cost_rank: int = 100
    max_output_tokens: int = 4_000
    validation_retries: int = 1

    @classmethod
    def from_dict(cls, agent_id: str, data: Mapping[str, Any]) -> "AgentProfile":
        strategy = str(data.get("strategy", "predict"))
        if strategy not in {"predict", "agentic"}:
            raise ConfigurationError(
                f"Agent {agent_id!r} strategy must be 'predict' or 'agentic'"
            )
        access = str(data.get("access", "read_only"))
        if access not in {"read_only", "workspace_write"}:
            raise ConfigurationError(
                f"Agent {agent_id!r} access must be 'read_only' or 'workspace_write'"
            )
        quality_tier = str(data.get("quality_tier", "standard"))
        if quality_tier not in {"economy", "standard", "high"}:
            raise ConfigurationError(
                f"Agent {agent_id!r} quality_tier must be economy, standard, or high"
            )
        values = cls(
            agent_id=agent_id,
            identity=str(data.get("identity", agent_id)),
            role=str(data.get("role", "worker")),
            provider=str(data["provider"]),
            model=str(data.get("model", "")),
            capabilities=tuple(str(value) for value in data.get("capabilities", [])),
            strategy=strategy,
            access=access,
            quality_tier=quality_tier,
            cost_rank=int(data.get("cost_rank", 100)),
            max_output_tokens=int(data.get("max_output_tokens", 4_000)),
            validation_retries=int(data.get("validation_retries", 1)),
        )
        if values.cost_rank < 0 or values.max_output_tokens < 1:
            raise ConfigurationError(
                f"Agent {agent_id!r} cost_rank cannot be negative and "
                "max_output_tokens must be positive"
            )
        if values.validation_retries < 0:
            raise ConfigurationError(
                f"Agent {agent_id!r} validation_retries cannot be negative"
            )
        if not values.provider.strip() or not values.model.strip():
            raise ConfigurationError(
                f"Agent {agent_id!r} provider and model must not be empty"
            )
        return values


@dataclass(frozen=True)
class RoutingRule:
    keywords: Tuple[str, ...]
    capabilities: Tuple[str, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RoutingRule":
        return cls(
            keywords=tuple(str(value).lower() for value in data.get("keywords", [])),
            capabilities=tuple(str(value) for value in data.get("capabilities", [])),
        )


@dataclass(frozen=True)
class BudgetConfig:
    max_concurrency: int = 1
    provider_retry_limit: int = 1
    max_provider_calls: int = 20
    max_total_tokens: int = 250_000
    max_estimated_cost_usd: float = 0.0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BudgetConfig":
        values = cls(
            max_concurrency=int(data.get("max_concurrency", 1)),
            provider_retry_limit=int(data.get("provider_retry_limit", 1)),
            max_provider_calls=int(data.get("max_provider_calls", 20)),
            max_total_tokens=int(data.get("max_total_tokens", 250_000)),
            max_estimated_cost_usd=float(data.get("max_estimated_cost_usd", 0.0)),
        )
        if (
            min(
                values.max_concurrency,
                values.max_provider_calls,
                values.max_total_tokens,
            )
            < 1
        ):
            raise ConfigurationError(
                "max_concurrency, max_provider_calls, and max_total_tokens must be positive"
            )
        if (
            values.provider_retry_limit < 0
            or not math.isfinite(values.max_estimated_cost_usd)
            or values.max_estimated_cost_usd < 0
        ):
            raise ConfigurationError(
                "provider_retry_limit cannot be negative and max_estimated_cost_usd "
                "must be finite and non-negative"
            )
        return values


@dataclass(frozen=True)
class VerificationConfig:
    enabled: bool = True
    complexities: Tuple[str, ...] = ("high",)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VerificationConfig":
        values = cls(
            enabled=bool(data.get("enabled", True)),
            complexities=tuple(
                str(value) for value in data.get("complexities", ["high"])
            ),
        )
        invalid = sorted(set(values.complexities) - {"low", "medium", "high"})
        if invalid:
            raise ConfigurationError(
                "verification complexities must be low, medium, or high: "
                + ", ".join(invalid)
            )
        return values


@dataclass(frozen=True)
class OutputConfig:
    include_bus_history: bool = True
    include_conversations: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OutputConfig":
        return cls(
            include_bus_history=bool(data.get("include_bus_history", True)),
            include_conversations=bool(data.get("include_conversations", True)),
        )


@dataclass(frozen=True)
class SwarmConfig:
    providers: Dict[str, ProviderConfig]
    overseer: AgentProfile
    workers: Tuple[AgentProfile, ...]
    routing_rules: Tuple[RoutingRule, ...]
    budgets: BudgetConfig
    verification: VerificationConfig
    output: OutputConfig

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SwarmConfig":
        providers_data = data.get("providers") or {}
        if not providers_data:
            raise ConfigurationError("At least one provider must be configured")
        providers = {
            name: ProviderConfig.from_dict(name, provider_data)
            for name, provider_data in providers_data.items()
        }
        if "overseer" not in data:
            raise ConfigurationError("An overseer profile must be configured")
        overseer = AgentProfile.from_dict("overseer", data["overseer"])
        worker_data = data.get("workers") or {}
        workers = tuple(
            AgentProfile.from_dict(agent_id, profile)
            for agent_id, profile in worker_data.items()
        )
        if not workers:
            raise ConfigurationError("At least one worker profile must be configured")
        missing = sorted(
            {profile.provider for profile in (overseer, *workers)} - set(providers)
        )
        if missing:
            raise ConfigurationError(
                "Unknown provider references: " + ", ".join(missing)
            )
        if overseer.role != "overseer":
            raise ConfigurationError("The overseer profile role must be 'overseer'")
        if overseer.strategy != "predict":
            raise ConfigurationError("The overseer profile strategy must be 'predict'")
        invalid_roles = sorted(
            profile.agent_id
            for profile in workers
            if profile.role not in {"worker", "reviewer"}
        )
        if invalid_roles:
            raise ConfigurationError(
                "Worker profiles must use role 'worker' or 'reviewer': "
                + ", ".join(invalid_roles)
            )
        invalid_strategies = sorted(
            profile.agent_id
            for profile in workers
            if (profile.role == "worker" and profile.strategy != "agentic")
            or (profile.role == "reviewer" and profile.strategy != "predict")
        )
        if invalid_strategies:
            raise ConfigurationError(
                "Workers require strategy 'agentic' and reviewers require 'predict': "
                + ", ".join(invalid_strategies)
            )
        access_mismatches = sorted(
            profile.agent_id
            for profile in (overseer, *workers)
            if providers[profile.provider].enforced_access != profile.access
        )
        if access_mismatches:
            raise ConfigurationError(
                "Agent access must exactly match the provider-enforced boundary; "
                "unrestricted providers cannot be routed safely: "
                + ", ".join(access_mismatches)
            )
        invalid_mutators = sorted(
            profile.agent_id
            for profile in workers
            if profile.role == "worker"
            and set(profile.capabilities).intersection(
                {"documentation", "implementation"}
            )
            and profile.access != "workspace_write"
        )
        if invalid_mutators:
            raise ConfigurationError(
                "Documentation and implementation workers require workspace_write: "
                + ", ".join(invalid_mutators)
            )
        retrying_mutators = sorted(
            profile.agent_id
            for profile in workers
            if profile.access == "workspace_write" and profile.validation_retries > 0
        )
        if retrying_mutators:
            raise ConfigurationError(
                "workspace_write profiles must set validation_retries to 0: "
                + ", ".join(retrying_mutators)
            )
        routing_data = data.get("routing") or {}
        return cls(
            providers=providers,
            overseer=overseer,
            workers=workers,
            routing_rules=tuple(
                RoutingRule.from_dict(rule) for rule in routing_data.get("rules", [])
            ),
            budgets=BudgetConfig.from_dict(data.get("budgets") or {}),
            verification=VerificationConfig.from_dict(data.get("verification") or {}),
            output=OutputConfig.from_dict(data.get("output") or {}),
        )


def load_config(path: str | Path) -> SwarmConfig:
    import yaml

    with Path(path).open("r", encoding="utf-8") as handle:
        return SwarmConfig.from_dict(yaml.safe_load(handle) or {})
