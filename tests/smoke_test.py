"""Zero-cost executable smoke test for the real SwarmRunner lifecycle."""

import asyncio
import json

from agent_swarm.core.config import SwarmConfig
from agent_swarm.core.run import TaskPlan
from agent_swarm.providers.base import ProviderResult, TokenUsage
from agent_swarm.swarm_runner import SwarmRunner


class SmokeProvider:
    name = "fake"

    async def run(self, prompt, *, model, title, cwd):
        return ProviderResult(
            output=json.dumps(
                {
                    "status": "completed",
                    "summary": "smoke task completed with evidence",
                    "evidence": ["scripted smoke fixture"],
                    "changed_files": [],
                    "unresolved_risks": [],
                }
            ),
            usage=TokenUsage(input_tokens=10, output_tokens=5, source="scripted"),
            provider=self.name,
            model=model,
            duration_seconds=0,
        )


async def run_smoke_test():
    config = SwarmConfig.from_dict(
        {
            "providers": {
                "fake": {
                    "command": "unused",
                    "args": [],
                    "enforced_access": "read_only",
                }
            },
            "overseer": {
                "role": "overseer",
                "provider": "fake",
                "model": "overseer",
                "strategy": "predict",
                "access": "read_only",
                "quality_tier": "high",
            },
            "workers": {
                "worker": {
                    "role": "worker",
                    "provider": "fake",
                    "model": "worker",
                    "capabilities": ["analysis"],
                    "strategy": "agentic",
                    "access": "read_only",
                    "quality_tier": "economy",
                }
            },
            "verification": {"enabled": False},
        }
    )
    plan = TaskPlan.from_data(
        [
            {
                "id": "smoke",
                "description": "Exercise the lifecycle",
                "required_capabilities": ["analysis"],
                "complexity": "low",
            }
        ]
    )
    result = await SwarmRunner(config, providers={"fake": SmokeProvider()}).run(
        "Smoke test", cwd=".", plan=plan
    )
    assert result.record.status == "succeeded"
    assert [event["topic"] for event in result.record.bus_history] == [
        "run.request",
        "plan.created",
        "task.assigned",
        "task.result",
        "run.aggregated",
        "run.completed",
    ]
    print(result.to_json())


if __name__ == "__main__":
    asyncio.run(run_smoke_test())
