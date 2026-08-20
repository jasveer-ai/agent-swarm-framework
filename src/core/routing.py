from __future__ import annotations

from typing import Iterable, Sequence, Set

from src.core.config import AgentProfile, RoutingRule
from src.core.run import SelectionRecord, TaskSpec


class NoEligibleWorker(RuntimeError):
    pass


class WorkerSelector:
    QUALITY_RANK = {"economy": 0, "standard": 1, "high": 2}
    COMPLEXITY_QUALITY = {"low": "economy", "medium": "standard", "high": "high"}

    def __init__(
        self, workers: Sequence[AgentProfile], routing_rules: Sequence[RoutingRule]
    ) -> None:
        self.workers = tuple(workers)
        self.routing_rules = tuple(routing_rules)

    def required_capabilities(self, task: TaskSpec) -> Set[str]:
        required = set(task.required_capabilities)
        description = task.description.lower()
        for rule in self.routing_rules:
            if any(keyword in description for keyword in rule.keywords):
                required.update(rule.capabilities)
        return required

    def select(
        self,
        task: TaskSpec,
        *,
        role: str = "worker",
        exclude_agent_ids: Iterable[str] = (),
    ) -> tuple[AgentProfile, SelectionRecord]:
        excluded = set(exclude_agent_ids)
        required = self.required_capabilities(task)
        required_access = task.access
        required_quality = (
            task.minimum_quality or self.COMPLEXITY_QUALITY[task.complexity]
        )
        eligible = [
            worker
            for worker in self.workers
            if worker.role == role
            and worker.agent_id not in excluded
            and required.issubset(set(worker.capabilities))
            and worker.access == required_access
            and self.QUALITY_RANK[worker.quality_tier]
            >= self.QUALITY_RANK[required_quality]
        ]
        if not eligible:
            raise NoEligibleWorker(
                f"No {role} satisfies capabilities {sorted(required)}, access "
                f"{required_access!r}, and quality {required_quality!r} for {task.task_id}"
            )
        eligible.sort(key=lambda worker: (worker.cost_rank, worker.agent_id))
        selected = eligible[0]
        candidates = [
            {
                "agent_id": worker.agent_id,
                "provider": worker.provider,
                "model": worker.model,
                "access": worker.access,
                "quality_tier": worker.quality_tier,
                "cost_rank": worker.cost_rank,
            }
            for worker in eligible
        ]
        return selected, SelectionRecord(
            task_id=task.task_id,
            required_capabilities=sorted(required),
            eligible_agents=candidates,
            selected_agent_id=selected.agent_id,
            reason=(
                "lowest cost_rank after role, capability, exact-access, and quality filters; "
                "agent_id breaks ties"
            ),
        )
