"""Compatibility name for a task-performing worker agent."""

from agent_swarm.agents.worker import WorkerAgent

Builder = WorkerAgent

__all__ = ["Builder", "WorkerAgent"]
