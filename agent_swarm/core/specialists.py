"""Generic, fail-closed specialist selection contracts and routing."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_swarm.core.config import AgentProfile

AccessBoundary = Literal["read_only", "workspace_write"]


class NoEligibleSpecialist(RuntimeError):
    """Raised when no registered specialist satisfies a signal."""


class PolicyDenied(PermissionError):
    """Raised when an approval policy does not permit a requested action."""


class WorkSignal(BaseModel):
    """A typed request that may be routed to a registered specialist."""

    model_config = ConfigDict(populate_by_name=True)

    signal_id: str = Field(alias="id")
    summary: str
    requested_action: str
    required_capabilities: tuple[str, ...] = ()
    access: AccessBoundary = "read_only"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("signal_id", "summary", "requested_action")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("required_capabilities")
    @classmethod
    def capabilities_are_non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(capability.strip() for capability in value)
        if any(not capability for capability in normalized):
            raise ValueError("capabilities must not be blank")
        return normalized


class EvidenceArtifact(BaseModel):
    """A serializable unit of evidence supporting a decision or outcome."""

    model_config = ConfigDict(populate_by_name=True)

    artifact_id: str = Field(alias="id")
    kind: str
    content: str
    source: str = ""

    @field_validator("artifact_id", "kind", "content")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class DecisionBrief(BaseModel):
    """A typed record of a routing approval or denial."""

    model_config = ConfigDict(populate_by_name=True)

    decision_id: str = Field(alias="id")
    signal_id: str
    status: Literal["approved", "denied"]
    summary: str
    selected_specialist_id: str | None = None
    evidence: tuple[EvidenceArtifact, ...] = ()

    @field_validator("decision_id", "signal_id", "summary")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def selection_matches_status(self) -> DecisionBrief:
        if self.status == "approved" and not self.selected_specialist_id:
            raise ValueError("approved decisions require a selected specialist")
        if self.status == "denied" and self.selected_specialist_id:
            raise ValueError("denied decisions cannot select a specialist")
        return self


class ApprovalPolicy(BaseModel):
    """An allow-list policy for specialist actions and access boundaries.

    Actions are denied by default. This makes callers opt in explicitly before
    a signal can cause specialist selection or provider invocation.
    """

    allowed_actions: tuple[str, ...] = ()
    allowed_access: tuple[AccessBoundary, ...] = ("read_only", "workspace_write")

    @field_validator("allowed_actions")
    @classmethod
    def actions_are_non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(action.strip() for action in value)
        if any(not action for action in normalized):
            raise ValueError("allowed actions must not be blank")
        return normalized

    def permits(self, signal: WorkSignal) -> bool:
        return (
            signal.requested_action in self.allowed_actions
            and signal.access in self.allowed_access
        )

    def require(self, signal: WorkSignal) -> None:
        if signal.requested_action not in self.allowed_actions:
            raise PolicyDenied(
                f"Action {signal.requested_action!r} is not allowed by policy"
            )
        if signal.access not in self.allowed_access:
            raise PolicyDenied(f"Access {signal.access!r} is not allowed by policy")


class SpecialistRegistry:
    """An in-memory, deterministic registry of generic specialist profiles."""

    def __init__(self, specialists: Sequence[AgentProfile] = ()) -> None:
        self._specialists: dict[str, AgentProfile] = {}
        for specialist in specialists:
            self.register(specialist)

    def register(self, specialist: AgentProfile) -> None:
        if specialist.agent_id in self._specialists:
            raise ValueError(
                f"Specialist {specialist.agent_id!r} is already registered"
            )
        self._specialists[specialist.agent_id] = specialist

    @property
    def specialists(self) -> tuple[AgentProfile, ...]:
        return tuple(self._specialists.values())

    def eligible(
        self,
        signal: WorkSignal,
        *,
        role: str = "worker",
        exclude_specialist_ids: Sequence[str] = (),
    ) -> tuple[AgentProfile, ...]:
        excluded = set(exclude_specialist_ids)
        required = set(signal.required_capabilities)
        return tuple(
            sorted(
                (
                    specialist
                    for specialist in self._specialists.values()
                    if specialist.role == role
                    and specialist.agent_id not in excluded
                    and specialist.access == signal.access
                    and required.issubset(set(specialist.capabilities))
                ),
                key=lambda specialist: (specialist.cost_rank, specialist.agent_id),
            )
        )

    def select(
        self,
        signal: WorkSignal,
        *,
        role: str = "worker",
        exclude_specialist_ids: Sequence[str] = (),
    ) -> AgentProfile:
        eligible = self.eligible(
            signal,
            role=role,
            exclude_specialist_ids=exclude_specialist_ids,
        )
        if not eligible:
            raise NoEligibleSpecialist(
                f"No {role} satisfies capabilities "
                f"{sorted(signal.required_capabilities)}, "
                f"access {signal.access!r}, for signal {signal.signal_id!r}"
            )
        return eligible[0]


class SpecialistRouter:
    """Routes approved signals only; policy and registry failures are terminal."""

    def __init__(self, registry: SpecialistRegistry, policy: ApprovalPolicy) -> None:
        self.registry = registry
        self.policy = policy

    def route(
        self,
        signal: WorkSignal,
        *,
        role: str = "worker",
        exclude_specialist_ids: Sequence[str] = (),
    ) -> tuple[AgentProfile, DecisionBrief]:
        self.policy.require(signal)
        specialist = self.registry.select(
            signal,
            role=role,
            exclude_specialist_ids=exclude_specialist_ids,
        )
        brief = DecisionBrief(
            id=f"{signal.signal_id}:routing",
            signal_id=signal.signal_id,
            status="approved",
            summary=(
                "Selected the registered specialist with the lowest cost_rank "
                "after capability and exact-access filtering."
            ),
            selected_specialist_id=specialist.agent_id,
            evidence=(
                EvidenceArtifact(
                    id=f"{signal.signal_id}:selection",
                    kind="specialist_selection",
                    content=(
                        f"Selected {specialist.agent_id!r} for capabilities "
                        f"{sorted(signal.required_capabilities)} and access "
                        f"{signal.access!r}."
                    ),
                    source="SpecialistRegistry",
                ),
            ),
        )
        return specialist, brief
