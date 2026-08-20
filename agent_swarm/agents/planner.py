from __future__ import annotations

from agent_swarm.agents.base import ObjectAgent, generation
from agent_swarm.core.run import TaskPlan


class PlanningAgent(ObjectAgent):
    """You decompose a goal into independent, capability-scoped tasks."""

    @generation(strategy="predict")
    async def create_plan(
        self,
        goal: str,
        available_capabilities: tuple[str, ...],
    ) -> TaskPlan:
        """Create the smallest useful task plan.

        Use only available capabilities. Give every task an honest complexity,
        access boundary, minimum quality, estimated input tokens, and maximum
        output tokens. Declare dependencies only when ordering is required.
        Workspace changes require workspace_write access. Do not add a task
        whose only purpose is to restate or summarize another task.
        """

        ...
