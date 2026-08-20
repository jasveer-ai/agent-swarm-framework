"""Opt-in live CLI-provider test. This can consume provider quota and edit the cwd."""

import asyncio
import os
import sys

from src.core.config import load_config
from src.core.run import TaskPlan
from src.swarm_runner import SwarmRunner


async def run_live_test():
    if os.environ.get("RUN_LIVE_SWARM") != "1":
        print("SKIPPED: set RUN_LIVE_SWARM=1 to allow real provider calls")
        return True

    plan = TaskPlan.from_data(
        [
            {
                "id": "live-proof",
                "description": (
                    "Create swarm_proof.txt containing 'Agent Swarm is operational', then "
                    "report the exact verification performed"
                ),
                "required_capabilities": ["implementation", "testing"],
                "complexity": "low",
                "access": "workspace_write",
                "estimated_input_tokens": 1000,
                "max_output_tokens": 1000,
            }
        ],
        source="integration_test",
    )
    result = await SwarmRunner(load_config(".swarm/config.yaml")).run(
        "Prove the configured worker can edit the workspace",
        cwd=os.getcwd(),
        plan=plan,
    )
    print(result.to_json())
    return result.record.status == "succeeded" and os.path.exists("swarm_proof.txt")


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run_live_test()) else 1)
