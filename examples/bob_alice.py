"""Zero-cost builder/reviewer demo with a complete conversation transcript."""

import asyncio
import json

from agent_swarm.core.config import SwarmConfig
from agent_swarm.core.run import TaskPlan
from agent_swarm.providers.base import ProviderResult, TokenUsage
from agent_swarm.swarm_runner import SwarmRunner


class BobAliceProvider:
    name = "scripted"

    def __init__(self):
        self.outputs = [
            json.dumps(
                {
                    "status": "completed",
                    "summary": "Built the requested artifact; check A passed.",
                    "evidence": ["Check A"],
                    "changed_files": ["artifact.txt"],
                    "unresolved_risks": [],
                }
            ),
            json.dumps(
                {
                    "verdict": "APPROVE",
                    "summary": "Check A is present.",
                    "findings": [],
                }
            ),
        ]

    async def run(self, prompt, *, model, title, cwd):
        return ProviderResult(
            output=self.outputs.pop(0),
            usage=TokenUsage(input_tokens=20, output_tokens=10, source="scripted"),
            provider=self.name,
            model=model,
            duration_seconds=0,
        )


async def main():
    config = SwarmConfig.from_dict(
        {
            "providers": {
                "scripted_read": {
                    "command": "unused",
                    "args": [],
                    "enforced_access": "read_only",
                },
                "scripted_write": {
                    "command": "unused",
                    "args": [],
                    "enforced_access": "workspace_write",
                },
            },
            "overseer": {
                "identity": "Codex caller",
                "role": "overseer",
                "provider": "scripted_read",
                "model": "overseer",
                "strategy": "predict",
                "access": "read_only",
                "quality_tier": "high",
            },
            "workers": {
                "bob": {
                    "identity": "Bob Builder",
                    "role": "worker",
                    "provider": "scripted_write",
                    "model": "builder",
                    "capabilities": ["implementation"],
                    "strategy": "agentic",
                    "access": "workspace_write",
                    "quality_tier": "high",
                    "cost_rank": 1,
                    "validation_retries": 0,
                },
                "alice": {
                    "identity": "Alice Reviewer",
                    "role": "reviewer",
                    "provider": "scripted_read",
                    "model": "reviewer",
                    "capabilities": ["review"],
                    "strategy": "predict",
                    "access": "read_only",
                    "quality_tier": "high",
                    "cost_rank": 1,
                },
            },
            "verification": {"enabled": True, "complexities": ["high"]},
        }
    )
    plan = TaskPlan.from_data(
        [
            {
                "id": "build",
                "description": "Build the artifact",
                "required_capabilities": ["implementation"],
                "complexity": "high",
                "access": "workspace_write",
            }
        ],
        source="current_codex",
    )
    provider = BobAliceProvider()
    result = await SwarmRunner(
        config,
        providers={"scripted_read": provider, "scripted_write": provider},
    ).run("Build and review", cwd=".", plan=plan)
    print(result.to_json())


if __name__ == "__main__":
    asyncio.run(main())
