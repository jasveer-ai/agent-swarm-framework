"""Compatibility name for nested typed planning agents.

Nested planners use the same object contract as the root planner. The caller is
responsible for enforcing nesting and budget limits before invoking one.
"""

from src.agents.planner import PlanningAgent

SubOrchestrator = PlanningAgent

__all__ = ["PlanningAgent", "SubOrchestrator"]
