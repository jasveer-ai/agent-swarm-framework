from __future__ import annotations

from agent_swarm.agents.base import ObjectAgent, generation
from agent_swarm.core.run import ReviewDecision, TaskOutcome, TaskSpec


class ReviewerAgent(ObjectAgent):
    """You independently assess whether a task result is complete and evidenced."""

    @generation(strategy="predict")
    async def review_task(
        self,
        task: TaskSpec,
        outcome: TaskOutcome,
    ) -> ReviewDecision:
        """Approve only when the outcome satisfies the task and cites real evidence.

        Reject missing verification, unsupported claims, hidden scope expansion,
        or unresolved risk that invalidates completion.
        """

        ...
