from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import ClassVar

from agent_swarm.core.config import AgentProfile, RoutingRule
from agent_swarm.core.run import SelectionRecord, TaskSpec
from agent_swarm.core.specialists import SpecialistRegistry, WorkSignal


class NoEligibleWorker(RuntimeError):
    pass


class WorkerSelector:
    QUALITY_RANK: ClassVar[dict[str, int]] = {"economy": 0, "standard": 1, "high": 2}
    COMPLEXITY_QUALITY: ClassVar[dict[str, str]] = {
        "low": "economy",
        "medium": "standard",
        "high": "high",
    }

    def __init__(
        self, workers: Sequence[AgentProfile], routing_rules: Sequence[RoutingRule]
    ) -> None:
        self.workers = tuple(workers)
        self.routing_rules = tuple(routing_rules)
        self.registry = SpecialistRegistry(self.workers)

    def required_capabilities(
        self, task: TaskSpec, *, role: str = "worker"
    ) -> set[str]:
        if role == "reviewer":
            return set(task.required_capabilities)
        required = set(task.required_capabilities)
        description = task.description.lower()
        for rule in self.routing_rules:
            if any(
                self._contains_keyword(description, keyword)
                for keyword in rule.keywords
            ):
                required.update(rule.capabilities)
        return required

    @staticmethod
    def _contains_keyword(description: str, keyword: str) -> bool:
        """Match routing terms as tokens or phrases, never as substrings."""

        pattern = rf"(?<![a-z0-9_]){re.escape(keyword.lower())}(?![a-z0-9_])"
        return re.search(pattern, description) is not None

    def select(
        self,
        task: TaskSpec,
        *,
        role: str = "worker",
        exclude_agent_ids: Iterable[str] = (),
    ) -> tuple[AgentProfile, SelectionRecord]:
        excluded = set(exclude_agent_ids)
        required = self.required_capabilities(task, role=role)
        required_access = task.access
        required_quality = (
            task.minimum_quality or self.COMPLEXITY_QUALITY[task.complexity]
        )
        signal = WorkSignal(
            id=task.task_id,
            summary=task.description,
            requested_action="execute_task",
            required_capabilities=tuple(sorted(required)),
            access=required_access,
        )
        eligible = [
            worker
            for worker in self.registry.eligible(
                signal,
                role=role,
                exclude_specialist_ids=tuple(excluded),
            )
            if self.QUALITY_RANK[worker.quality_tier]
            >= self.QUALITY_RANK[required_quality]
        ]
        if not eligible:
            raise NoEligibleWorker(
                f"No {role} satisfies capabilities {sorted(required)}, access "
                f"{required_access!r}, and quality {required_quality!r} "
                f"for {task.task_id}"
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
                "lowest cost_rank after role, capability, exact-access, and "
                "quality filters; "
                "agent_id breaks ties"
            ),
        )
