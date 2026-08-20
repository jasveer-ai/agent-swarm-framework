import json
import unittest
from dataclasses import replace
from typing import Any

from src.agents.base import ObjectAgent, generation
from src.agents.planner import PlanningAgent
from src.agents.reviewer import ReviewerAgent
from src.agents.worker import WorkerAgent
from src.core.config import SwarmConfig
from src.core.run import RunRecord, TaskSpec
from src.core.runtime import AgentRuntime
from src.providers.base import ProviderResult, TokenUsage


class ReturnTypes:
    Generated = Any


class CapturingProvider:
    name = "fake"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    async def run(self, prompt, *, model, title, cwd):
        self.prompts.append(prompt)
        return ProviderResult(
            output=self.outputs.pop(0),
            usage=TokenUsage(input_tokens=10, output_tokens=5, source="fixture"),
            provider=self.name,
            model=model,
            duration_seconds=0,
        )


def config(strategy="agentic", validation_retries=1):
    return SwarmConfig.from_dict(
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
                "model": "planner",
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
                    "strategy": strategy,
                    "access": "read_only",
                    "quality_tier": "economy",
                    "validation_retries": validation_retries,
                }
            },
            "verification": {"enabled": False},
        }
    )


class AgentObjectTests(unittest.IsolatedAsyncioTestCase):
    def test_roles_share_one_object_agent_contract(self):
        self.assertTrue(issubclass(PlanningAgent, ObjectAgent))
        self.assertTrue(issubclass(WorkerAgent, ObjectAgent))
        self.assertTrue(issubclass(ReviewerAgent, ObjectAgent))
        self.assertTrue(WorkerAgent.execute_task.__generation_method__)
        self.assertEqual(WorkerAgent.execute_task.__generation_strategy__, "agentic")
        self.assertFalse(hasattr(ObjectAgent.supports, "__generation_method__"))

    def test_generation_method_requires_typed_return(self):
        with self.assertRaisesRegex(TypeError, "typed return annotation"):

            class UntypedAgent(ObjectAgent):
                @generation(strategy="predict")
                async def perform(self): ...

    async def test_generation_method_rejects_alias_resolving_to_any(self):
        class AliasAgent(ObjectAgent):
            @generation(strategy="agentic")
            async def perform(self) -> object: ...

        AliasAgent.perform.__wrapped__.__annotations__["return"] = (
            "ReturnTypes.Generated"
        )
        provider = CapturingProvider([])
        swarm_config = config(validation_retries=0)
        agent = AliasAgent(
            profile=swarm_config.workers[0],
            generation_runtime=AgentRuntime(
                {"fake": provider}, swarm_config.providers, swarm_config.budgets
            ),
            task_id="t1",
            cwd=".",
            run_record=RunRecord(goal="inspect"),
        )

        with self.assertRaisesRegex(Exception, "resolved to Any"):
            await agent.perform()
        self.assertEqual(provider.prompts, [])

    async def test_typed_generation_retries_invalid_json_and_keeps_arguments_separate(
        self,
    ):
        provider = CapturingProvider(
            [
                "not json",
                json.dumps(
                    {
                        "status": "completed",
                        "summary": "done",
                        "evidence": ["fixture"],
                        "changed_files": [],
                        "unresolved_risks": [],
                    }
                ),
            ]
        )
        swarm_config = config()
        record = RunRecord(goal="inspect")
        runtime = AgentRuntime(
            {"fake": provider}, swarm_config.providers, swarm_config.budgets
        )
        agent = WorkerAgent(
            profile=swarm_config.workers[0],
            generation_runtime=runtime,
            task_id="t1",
            cwd=".",
            run_record=record,
        )
        task = TaskSpec(
            id="t1",
            description="Inspect the parser",
            required_capabilities=("analysis",),
            complexity="low",
        )

        self.assertTrue(agent.supports("analysis"))
        self.assertEqual(provider.prompts, [])
        result = await agent.execute_task("Inspect", task)

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(provider.prompts), 2)
        self.assertIn("Generation method: execute_task", provider.prompts[0])
        self.assertIn("Bound arguments:", provider.prompts[0])
        self.assertIn("Inspect the parser", provider.prompts[0])
        self.assertIn("previous response violated", provider.prompts[1])

    async def test_profile_strategy_mismatch_fails_before_provider_call(self):
        provider = CapturingProvider([])
        swarm_config = config(validation_retries=0)
        invalid_profile = replace(swarm_config.workers[0], strategy="predict")
        agent = WorkerAgent(
            profile=invalid_profile,
            generation_runtime=AgentRuntime(
                {"fake": provider}, swarm_config.providers, swarm_config.budgets
            ),
            task_id="t1",
            cwd=".",
            run_record=RunRecord(goal="inspect"),
        )

        with self.assertRaisesRegex(ValueError, "requires 'agentic'"):
            await agent.execute_task(
                "Inspect",
                TaskSpec(id="t1", description="Inspect", complexity="low"),
            )
        self.assertEqual(provider.prompts, [])


if __name__ == "__main__":
    unittest.main()
