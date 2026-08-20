"""Compatibility name for the typed worker agent."""

from agent_swarm.agents.worker import WorkerAgent

Worker = WorkerAgent

__all__ = ["Worker", "WorkerAgent"]
