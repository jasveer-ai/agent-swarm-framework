"""Compatibility name for a task-performing worker agent."""

from src.agents.worker import WorkerAgent

Builder = WorkerAgent

__all__ = ["Builder", "WorkerAgent"]
