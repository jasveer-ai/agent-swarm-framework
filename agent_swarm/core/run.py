from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaskSpec(BaseModel):
    """Typed task contract shared by the overseer and workers."""

    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(alias="id")
    description: str
    required_capabilities: Tuple[str, ...] = ()
    complexity: Literal["low", "medium", "high"] = "medium"
    access: Literal["read_only", "workspace_write"] = "read_only"
    minimum_quality: Optional[Literal["economy", "standard", "high"]] = None
    depends_on: Tuple[str, ...] = ()
    estimated_input_tokens: int = Field(default=0, ge=0)
    max_output_tokens: int = Field(default=0, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("task_id", "description")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(by_alias=True)


class TaskPlan(BaseModel):
    """Validated decomposition returned or supplied by an overseer."""

    tasks: Tuple[TaskSpec, ...]
    source: str = "external_overseer"

    @field_validator("tasks")
    @classmethod
    def non_empty(cls, value: Tuple[TaskSpec, ...]) -> Tuple[TaskSpec, ...]:
        if not value:
            raise ValueError("task plan must not be empty")
        return value

    @model_validator(mode="after")
    def valid_dependency_graph(self) -> "TaskPlan":
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task ids must be unique")
        known = set(task_ids)
        for task in self.tasks:
            unknown = set(task.depends_on) - known
            if unknown:
                raise ValueError(
                    f"task {task.task_id!r} has unknown dependencies {sorted(unknown)}"
                )
            if task.task_id in task.depends_on:
                raise ValueError(f"task {task.task_id!r} cannot depend on itself")

        remaining = {task.task_id: set(task.depends_on) for task in self.tasks}
        resolved: set[str] = set()
        while remaining:
            ready = [
                task_id
                for task_id, dependencies in remaining.items()
                if dependencies.issubset(resolved)
            ]
            if not ready:
                raise ValueError("task plan contains a dependency cycle")
            resolved.update(ready)
            for task_id in ready:
                del remaining[task_id]
        return self

    @classmethod
    def from_data(cls, data: Any, *, source: str = "external_overseer") -> "TaskPlan":
        if isinstance(data, list):
            data = {"tasks": data}
        elif isinstance(data, dict):
            data = {**data, "source": source}
        else:
            raise ValueError("Task plan must be a list or object with tasks")
        data.setdefault("source", source)
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, value: str, *, source: str = "external_overseer") -> "TaskPlan":
        return cls.from_data(json.loads(value), source=source)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(by_alias=True)


class TaskOutcome(BaseModel):
    status: Literal["completed", "blocked", "failed"]
    summary: str
    evidence: Tuple[str, ...] = ()
    changed_files: Tuple[str, ...] = ()
    unresolved_risks: Tuple[str, ...] = ()

    @field_validator("summary")
    @classmethod
    def summary_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("evidence")
    @classmethod
    def evidence_non_empty(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("evidence items must not be blank")
        return normalized

    @model_validator(mode="after")
    def completed_has_evidence(self) -> "TaskOutcome":
        if self.status == "completed" and not self.evidence:
            raise ValueError("completed outcomes require at least one evidence item")
        return self


class ReviewDecision(BaseModel):
    verdict: Literal["APPROVE", "REJECT"]
    summary: str
    findings: Tuple[str, ...] = ()

    @field_validator("summary")
    @classmethod
    def summary_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


@dataclass
class SelectionRecord:
    task_id: str
    required_capabilities: List[str]
    eligible_agents: List[Dict[str, Any]]
    selected_agent_id: str
    reason: str


@dataclass
class InvocationRecord:
    invocation_id: str
    task_id: str
    agent_id: str
    provider: str
    model: str
    attempt: int
    status: str
    started_at: float
    finished_at: float
    duration_seconds: float
    usage: Dict[str, Any]
    accounted_cost_usd: Optional[float]
    cost_source: str
    error: Optional[str] = None


@dataclass
class TaskRecord:
    task_id: str
    description: str
    agent_id: str
    status: str
    output: str = ""
    outcome: Optional[Dict[str, Any]] = None
    review: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    terminal_message_id: Optional[str] = None


@dataclass
class RunRecord:
    goal: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    schema_version: str = "1.0"
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    plan_source: str = ""
    plan: Optional[Dict[str, Any]] = None
    tasks: List[TaskRecord] = field(default_factory=list)
    selections: List[SelectionRecord] = field(default_factory=list)
    invocations: List[InvocationRecord] = field(default_factory=list)
    bus_history: List[Dict[str, Any]] = field(default_factory=list)
    conversations: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    agent_conversations: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    usage: Dict[str, Any] = field(default_factory=dict)

    def finish(self, status: str) -> None:
        self.status = status
        self.finished_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SwarmRunResult:
    final_output: str
    record: RunRecord
    events: Tuple[Dict[str, Any], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {"final_output": self.final_output, "run": self.record.to_dict()}

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def events_to_ndjson(self) -> str:
        """Serialize the canonical bus chronology as one JSON object per line."""

        events = self.events or tuple(self.record.bus_history)
        return "\n".join(
            json.dumps(event, separators=(",", ":"), sort_keys=True) for event in events
        )
