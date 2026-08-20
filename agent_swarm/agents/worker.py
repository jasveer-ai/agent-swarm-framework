from __future__ import annotations

from agent_swarm.agents.base import ObjectAgent, generation
from agent_swarm.core.run import TaskOutcome, TaskSpec


class WorkerAgent(ObjectAgent):
    """You execute one scoped task and return evidence-backed results."""

    def validate_assignment(self, task: TaskSpec) -> None:
        """Fail before a model call if the task exceeds declared capabilities."""

        missing = set(task.required_capabilities) - set(self.capabilities)
        if missing:
            raise ValueError(
                f"Agent {self.profile.agent_id} lacks capabilities {sorted(missing)}"
            )

    @generation(strategy="agentic")
    async def execute_task(self, goal: str, task: TaskSpec) -> TaskOutcome:
        """Execute exactly one assigned task in the declared workspace.

        Respect the object's access boundary. Report only changes and checks
        actually performed. Return blocked when missing authority, tools, or
        evidence prevents a truthful completion claim.
        """

        ...
