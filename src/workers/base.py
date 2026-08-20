"""Compatibility name for the typed worker agent."""

from src.agents.worker import WorkerAgent

Worker = WorkerAgent

__all__ = ["Worker", "WorkerAgent"]
