from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Dict, Mapping, Optional

from pydantic import BaseModel, TypeAdapter, ValidationError

from src.core.config import AgentProfile, BudgetConfig, Pricing, ProviderConfig
from src.core.run import InvocationRecord, RunRecord
from src.providers.base import (
    ModelProvider,
    ProviderError,
    ProviderResult,
    TokenUsage,
    redact_diagnostic,
)


class BudgetExceeded(RuntimeError):
    pass


class GenerationContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    tokens: int
    estimated_cost_usd: Optional[float]


def estimate_cost(usage: TokenUsage, pricing: Optional[Pricing]) -> Optional[float]:
    if usage.provider_reported_cost_usd is not None:
        return usage.provider_reported_cost_usd
    if pricing is None or usage.input_tokens is None or usage.output_tokens is None:
        return None
    cached = min(usage.cached_input_tokens or 0, usage.input_tokens)
    uncached = usage.input_tokens - cached
    return (
        uncached * pricing.input_per_million_usd
        + cached * pricing.cached_input_per_million_usd
        + usage.output_tokens * pricing.output_per_million_usd
    ) / 1_000_000


class UsageLedger:
    def __init__(self, budgets: BudgetConfig):
        self.budgets = budgets
        self.calls = 0
        self.committed_tokens = 0
        self.reserved_tokens = 0
        self.committed_cost_usd = 0.0
        self.reserved_cost_usd = 0.0
        self.unknown_usage_calls = 0
        self.unknown_cost_calls = 0
        self.by_agent: Dict[str, Dict[str, float | int]] = {}
        self.by_provider_model: Dict[str, Dict[str, float | int]] = {}
        self._reservations: Dict[str, Reservation] = {}
        self._lock = asyncio.Lock()

    async def reserve(
        self,
        *,
        prompt: str,
        profile: AgentProfile,
        provider: ProviderConfig,
        estimated_input_tokens: int = 0,
        max_output_tokens: int = 0,
    ) -> Reservation:
        prompt_estimate = max(1, len(prompt) // 4)
        estimated_input = max(estimated_input_tokens, prompt_estimate)
        estimated_output = max_output_tokens or profile.max_output_tokens
        estimated_usage = TokenUsage(
            input_tokens=estimated_input,
            output_tokens=estimated_output,
            source="estimated",
        )
        estimated_cost = estimate_cost(estimated_usage, provider.pricing)

        async with self._lock:
            if self.calls >= self.budgets.max_provider_calls:
                raise BudgetExceeded("provider call budget exhausted")
            if (
                self.committed_tokens
                + self.reserved_tokens
                + estimated_usage.total_tokens
                > self.budgets.max_total_tokens
            ):
                raise BudgetExceeded("token budget would be exceeded by the next call")
            if self.budgets.max_estimated_cost_usd > 0:
                if estimated_cost is None:
                    raise BudgetExceeded(
                        f"provider {provider.name!r} has no pricing for strict USD budget"
                    )
                if (
                    self.committed_cost_usd + self.reserved_cost_usd + estimated_cost
                    > self.budgets.max_estimated_cost_usd
                ):
                    raise BudgetExceeded(
                        "USD budget would be exceeded by the next call"
                    )

            reservation = Reservation(
                reservation_id=str(uuid.uuid4()),
                tokens=estimated_usage.total_tokens or 0,
                estimated_cost_usd=estimated_cost,
            )
            self.calls += 1
            self.reserved_tokens += reservation.tokens
            self.reserved_cost_usd += estimated_cost or 0.0
            self._reservations[reservation.reservation_id] = reservation
            return reservation

    async def reconcile(
        self,
        reservation: Reservation,
        *,
        profile: AgentProfile,
        result: ProviderResult,
        pricing: Optional[Pricing],
    ) -> tuple[Optional[float], str]:
        actual_tokens = result.usage.total_tokens
        actual_cost = estimate_cost(result.usage, pricing)
        budget_tokens = (
            actual_tokens if actual_tokens is not None else reservation.tokens
        )
        budget_cost = (
            actual_cost
            if actual_cost is not None
            else reservation.estimated_cost_usd or 0.0
        )
        accounted_cost = (
            actual_cost if actual_cost is not None else reservation.estimated_cost_usd
        )
        cost_source = (
            "provider_reported"
            if result.usage.provider_reported_cost_usd is not None
            else "configured_pricing_estimate"
            if actual_cost is not None
            else "reservation_estimate"
            if reservation.estimated_cost_usd is not None
            else "unavailable"
        )
        async with self._lock:
            self._reservations.pop(reservation.reservation_id, None)
            self.reserved_tokens -= reservation.tokens
            self.reserved_cost_usd -= reservation.estimated_cost_usd or 0.0
            self.committed_tokens += budget_tokens
            self.committed_cost_usd += budget_cost
            if actual_tokens is None:
                self.unknown_usage_calls += 1
            if actual_cost is None:
                self.unknown_cost_calls += 1

            self._add_summary(
                self.by_agent,
                profile.agent_id,
                result.usage,
                accounted_cost,
                cost_source,
            )
            self._add_summary(
                self.by_provider_model,
                f"{result.provider}/{result.model}",
                result.usage,
                accounted_cost,
                cost_source,
            )

        return accounted_cost, cost_source

    async def reconcile_failure(
        self,
        reservation: Reservation,
        *,
        profile: AgentProfile,
        provider_name: str,
        model: str,
        usage: Optional[TokenUsage],
        pricing: Optional[Pricing],
    ) -> tuple[Optional[float], str]:
        reported_usage = usage or TokenUsage(source="unknown")
        actual_tokens = reported_usage.total_tokens
        actual_cost = estimate_cost(reported_usage, pricing)
        budget_tokens = (
            actual_tokens if actual_tokens is not None else reservation.tokens
        )
        budget_cost = (
            actual_cost
            if actual_cost is not None
            else reservation.estimated_cost_usd or 0.0
        )
        cost_source = (
            "provider_reported"
            if reported_usage.provider_reported_cost_usd is not None
            else "configured_pricing_estimate"
            if actual_cost is not None
            else "reservation_estimate"
            if reservation.estimated_cost_usd is not None
            else "unavailable"
        )
        async with self._lock:
            self._reservations.pop(reservation.reservation_id, None)
            self.reserved_tokens -= reservation.tokens
            self.reserved_cost_usd -= reservation.estimated_cost_usd or 0.0
            self.committed_tokens += budget_tokens
            self.committed_cost_usd += budget_cost
            if actual_tokens is None:
                self.unknown_usage_calls += 1
            if actual_cost is None:
                self.unknown_cost_calls += 1
            accounted_cost = (
                actual_cost
                if actual_cost is not None
                else reservation.estimated_cost_usd
            )
            self._add_summary(
                self.by_agent,
                profile.agent_id,
                reported_usage,
                accounted_cost,
                cost_source,
            )
            self._add_summary(
                self.by_provider_model,
                f"{provider_name}/{model}",
                reported_usage,
                accounted_cost,
                cost_source,
            )
        return (
            actual_cost if actual_cost is not None else reservation.estimated_cost_usd,
            cost_source,
        )

    def overage_reason(self) -> Optional[str]:
        if self.committed_tokens > self.budgets.max_total_tokens:
            return "provider reported usage above the token budget"
        if (
            self.budgets.max_estimated_cost_usd > 0
            and self.committed_cost_usd > self.budgets.max_estimated_cost_usd
        ):
            return "provider reported usage above the USD budget"
        return None

    @staticmethod
    def _add_summary(
        summaries: Dict[str, Dict[str, float | int]],
        key: str,
        usage: TokenUsage,
        cost: Optional[float],
        cost_source: str,
    ) -> None:
        summary = summaries.setdefault(
            key,
            {
                "calls": 0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
                "provider_reported_cost_usd": 0.0,
                "estimated_cost_usd": 0.0,
                "accounted_cost_usd": 0.0,
                "unknown_usage_calls": 0,
                "unknown_cost_calls": 0,
            },
        )
        summary["calls"] += 1
        if usage.total_tokens is None:
            summary["unknown_usage_calls"] += 1
        for field in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        ):
            value = getattr(usage, field)
            if value is not None:
                summary[field] += value
        if cost is None:
            summary["unknown_cost_calls"] += 1
        else:
            summary["accounted_cost_usd"] += cost
            if cost_source == "provider_reported":
                summary["provider_reported_cost_usd"] += cost
            else:
                summary["estimated_cost_usd"] += cost
            if cost_source == "reservation_estimate":
                summary["unknown_cost_calls"] += 1

    def summary(self) -> Dict[str, object]:
        provider_reported_cost = sum(
            float(summary["provider_reported_cost_usd"])
            for summary in self.by_agent.values()
        )
        estimated_cost = sum(
            float(summary["estimated_cost_usd"]) for summary in self.by_agent.values()
        )
        return {
            "provider_calls": self.calls,
            "budget_accounted_tokens": self.committed_tokens,
            "provider_reported_cost_usd": provider_reported_cost,
            "estimated_cost_usd": estimated_cost,
            "accounted_cost_usd": provider_reported_cost + estimated_cost,
            "budget_accounted_cost_usd": self.committed_cost_usd,
            "unknown_usage_calls": self.unknown_usage_calls,
            "unknown_cost_calls": self.unknown_cost_calls,
            "by_agent": self.by_agent,
            "by_provider_model": self.by_provider_model,
            "limits": {
                "max_provider_calls": self.budgets.max_provider_calls,
                "max_total_tokens": self.budgets.max_total_tokens,
                "max_estimated_cost_usd": self.budgets.max_estimated_cost_usd,
                "max_concurrency": self.budgets.max_concurrency,
                "provider_retry_limit": self.budgets.provider_retry_limit,
            },
        }


class AgentRuntime:
    def __init__(
        self,
        providers: Mapping[str, ModelProvider],
        provider_configs: Mapping[str, ProviderConfig],
        budgets: BudgetConfig,
    ) -> None:
        self.providers = providers
        self.provider_configs = provider_configs
        self.budgets = budgets
        self.ledger = UsageLedger(budgets)
        self._semaphore = asyncio.Semaphore(budgets.max_concurrency)

    async def execute(
        self,
        profile: AgentProfile,
        prompt: str,
        *,
        task_id: str,
        title: str,
        cwd: str,
        record: RunRecord,
        estimated_input_tokens: int = 0,
        max_output_tokens: int = 0,
    ) -> ProviderResult:
        provider = self.providers[profile.provider]
        provider_config = self.provider_configs[profile.provider]
        last_error: Optional[ProviderError] = None
        retry_limit = (
            0
            if profile.access == "workspace_write"
            else self.budgets.provider_retry_limit
        )
        for attempt in range(1, retry_limit + 2):
            reservation = await self.ledger.reserve(
                prompt=prompt,
                profile=profile,
                provider=provider_config,
                estimated_input_tokens=estimated_input_tokens,
                max_output_tokens=max_output_tokens,
            )
            invocation_id = str(uuid.uuid4())
            started = time.time()
            try:
                async with self._semaphore:
                    result = await provider.run(
                        prompt,
                        model=profile.model,
                        title=title,
                        cwd=cwd,
                    )
                cost, cost_source = await self.ledger.reconcile(
                    reservation,
                    profile=profile,
                    result=result,
                    pricing=provider_config.pricing,
                )
                record.invocations.append(
                    InvocationRecord(
                        invocation_id=invocation_id,
                        task_id=task_id,
                        agent_id=profile.agent_id,
                        provider=result.provider,
                        model=result.model,
                        attempt=attempt,
                        status="succeeded",
                        started_at=started,
                        finished_at=time.time(),
                        duration_seconds=result.duration_seconds,
                        usage=result.usage.to_dict(),
                        accounted_cost_usd=cost,
                        cost_source=cost_source,
                    )
                )
                overage = self.ledger.overage_reason()
                if overage:
                    raise BudgetExceeded(overage)
                return result
            except asyncio.CancelledError:
                accounted_cost, cost_source = await self.ledger.reconcile_failure(
                    reservation,
                    profile=profile,
                    provider_name=profile.provider,
                    model=profile.model,
                    usage=None,
                    pricing=provider_config.pricing,
                )
                finished = time.time()
                record.invocations.append(
                    InvocationRecord(
                        invocation_id=invocation_id,
                        task_id=task_id,
                        agent_id=profile.agent_id,
                        provider=profile.provider,
                        model=profile.model,
                        attempt=attempt,
                        status="cancelled",
                        started_at=started,
                        finished_at=finished,
                        duration_seconds=finished - started,
                        usage=TokenUsage(source="unknown").to_dict(),
                        accounted_cost_usd=accounted_cost,
                        cost_source=cost_source,
                        error="provider invocation cancelled",
                    )
                )
                raise
            except ProviderError as error:
                safe_error = ProviderError(
                    redact_diagnostic(str(error)),
                    transient=error.transient,
                    usage=error.usage,
                    duration_seconds=error.duration_seconds,
                )
                accounted_cost, cost_source = await self.ledger.reconcile_failure(
                    reservation,
                    profile=profile,
                    provider_name=profile.provider,
                    model=profile.model,
                    usage=error.usage,
                    pricing=provider_config.pricing,
                )
                last_error = safe_error
                finished = time.time()
                record.invocations.append(
                    InvocationRecord(
                        invocation_id=invocation_id,
                        task_id=task_id,
                        agent_id=profile.agent_id,
                        provider=profile.provider,
                        model=profile.model,
                        attempt=attempt,
                        status="failed",
                        started_at=started,
                        finished_at=finished,
                        duration_seconds=(
                            error.duration_seconds
                            if error.duration_seconds is not None
                            else finished - started
                        ),
                        usage=(error.usage or TokenUsage(source="unknown")).to_dict(),
                        accounted_cost_usd=accounted_cost,
                        cost_source=cost_source,
                        error=str(safe_error),
                    )
                )
                overage = self.ledger.overage_reason()
                if overage:
                    raise BudgetExceeded(overage)
                if not error.transient or attempt > retry_limit:
                    raise safe_error from error
            except BudgetExceeded:
                raise
            except Exception as error:
                wrapped = ProviderError(
                    f"Provider {profile.provider!r} failed unexpectedly: "
                    f"{redact_diagnostic(str(error))}"
                )
                accounted_cost, cost_source = await self.ledger.reconcile_failure(
                    reservation,
                    profile=profile,
                    provider_name=profile.provider,
                    model=profile.model,
                    usage=None,
                    pricing=provider_config.pricing,
                )
                finished = time.time()
                record.invocations.append(
                    InvocationRecord(
                        invocation_id=invocation_id,
                        task_id=task_id,
                        agent_id=profile.agent_id,
                        provider=profile.provider,
                        model=profile.model,
                        attempt=attempt,
                        status="failed",
                        started_at=started,
                        finished_at=finished,
                        duration_seconds=finished - started,
                        usage=TokenUsage(source="unknown").to_dict(),
                        accounted_cost_usd=accounted_cost,
                        cost_source=cost_source,
                        error=str(wrapped)[:1000],
                    )
                )
                overage = self.ledger.overage_reason()
                if overage:
                    raise BudgetExceeded(overage)
                raise wrapped from error
        raise last_error or ProviderError("provider execution failed")

    async def generate(
        self,
        *,
        profile: AgentProfile,
        agent: Any,
        method_name: str,
        signature: str,
        instructions: str,
        arguments: Dict[str, Any],
        return_type: Any,
        strategy: str,
        task_id: str,
        cwd: str,
        record: RunRecord,
    ) -> Any:
        prompt = self._generation_prompt(
            agent=agent,
            method_name=method_name,
            signature=signature,
            instructions=instructions,
            arguments=arguments,
            return_type=return_type,
            strategy=strategy,
        )
        validation_error = ""
        requested_output_tokens = getattr(agent, "max_output_tokens", 0)
        admitted_output_tokens = (
            min(requested_output_tokens, profile.max_output_tokens)
            if requested_output_tokens
            else profile.max_output_tokens
        )
        for validation_attempt in range(profile.validation_retries + 1):
            request = prompt
            if validation_error:
                request += (
                    "\n\nThe previous response violated the return contract. Correct it without "
                    f"changing the task scope. Validation error:\n{validation_error[:1500]}"
                )
            result = await self.execute(
                profile,
                request,
                task_id=task_id,
                title=f"{profile.identity}: {method_name}",
                cwd=cwd,
                record=record,
                estimated_input_tokens=getattr(agent, "estimated_input_tokens", 0),
                max_output_tokens=admitted_output_tokens,
            )
            try:
                return self._validate_return(result.output, return_type)
            except (
                ValidationError,
                ValueError,
                TypeError,
                json.JSONDecodeError,
            ) as error:
                validation_error = str(error)
                if validation_attempt >= profile.validation_retries:
                    raise GenerationContractError(
                        f"{profile.agent_id}.{method_name} failed its typed return contract "
                        f"after {validation_attempt + 1} attempt(s): {validation_error[:1000]}"
                    ) from error
        raise GenerationContractError(
            f"{profile.agent_id}.{method_name} returned no value"
        )

    @staticmethod
    def _generation_prompt(
        *,
        agent: Any,
        method_name: str,
        signature: str,
        instructions: str,
        arguments: Dict[str, Any],
        return_type: Any,
        strategy: str,
    ) -> str:
        agent_doc = type(agent).__doc__ or ""
        state = AgentRuntime._bounded_json(agent.public_state())
        rendered_arguments = AgentRuntime._bounded_json(arguments, max_chars=None)
        try:
            schema = TypeAdapter(return_type).json_schema()
            contract = json.dumps(schema, sort_keys=True)
        except Exception:
            contract = repr(return_type)
        strategy_instruction = (
            "Use the provider's available tools when needed and stay inside the declared "
            "access/workspace boundary."
            if strategy == "agentic"
            else "Reason from the supplied values without changing the workspace."
        )
        return (
            f"Agent object: {type(agent).__name__}\n"
            f"Agent role: {agent_doc}\n"
            f"Public object state: {state}\n\n"
            f"Generation method: {method_name}{signature}\n"
            f"Method instructions: {instructions}\n"
            f"Bound arguments: {rendered_arguments}\n\n"
            f"Strategy: {strategy}. {strategy_instruction}\n"
            f"Return contract (JSON Schema): {contract}\n\n"
            "Return only JSON conforming to the return contract. Do not include hidden "
            "reasoning, Markdown fences, or claims unsupported by performed evidence."
        )

    @staticmethod
    def _bounded_json(value: Any, *, max_chars: Optional[int] = 20_000) -> str:
        def default(item: Any) -> Any:
            if isinstance(item, BaseModel):
                return item.model_dump(by_alias=True)
            if is_dataclass(item):
                return asdict(item)
            if isinstance(item, tuple):
                return list(item)
            return repr(item)

        rendered = json.dumps(value, default=default, sort_keys=True)
        if max_chars is None or len(rendered) <= max_chars:
            return rendered
        head = max_chars // 2
        tail = max_chars - head
        return rendered[:head] + "<truncated>" + rendered[-tail:]

    @staticmethod
    def _validate_return(output: str, return_type: Any) -> Any:
        if return_type is str:
            return output
        payload = AgentRuntime._extract_json(output)
        return TypeAdapter(return_type).validate_json(payload)

    @staticmethod
    def _extract_json(output: str) -> str:
        stripped = output.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()
        try:
            json.loads(stripped)
            return stripped
        except json.JSONDecodeError:
            pass
        starts = [
            index for index in (stripped.find("{"), stripped.find("[")) if index >= 0
        ]
        if not starts:
            raise json.JSONDecodeError("No JSON object or array found", stripped, 0)
        start = min(starts)
        end = max(stripped.rfind("}"), stripped.rfind("]"))
        if end <= start:
            raise json.JSONDecodeError("Incomplete JSON value", stripped, start)
        candidate = stripped[start : end + 1]
        json.loads(candidate)
        return candidate
