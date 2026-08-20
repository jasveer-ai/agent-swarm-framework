"""Compatibility exports for the paper-inspired object agent API.

New code should import from :mod:`agent_swarm.agents` directly. Keeping these names as
aliases avoids maintaining a second, incompatible agent hierarchy.
"""

from dataclasses import dataclass
from enum import Enum

from agent_swarm.agents.base import ObjectAgent, generation


class AgentRole(str, Enum):
    OVERSEER = "overseer"
    WORKER = "worker"
    REVIEWER = "reviewer"


class AgentStatus(str, Enum):
    IDLE = "idle"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    ERROR = "error"


@dataclass(frozen=True)
class Capability:
    name: str
    description: str = ""


BaseAgent = ObjectAgent

__all__ = [
    "AgentRole",
    "AgentStatus",
    "BaseAgent",
    "Capability",
    "ObjectAgent",
    "generation",
]
