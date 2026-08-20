import asyncio
import json
import unittest

from agent_swarm.core.config import SwarmConfig
from agent_swarm.core.run import TaskPlan
from agent_swarm.providers.base import ProviderError, ProviderResult, TokenUsage
from agent_swarm.swarm_runner import SwarmRunner


def outcome(status="completed", summary="worker evidence"):
    return json.dumps(
        {
            "status": status,
            "summary": summary,
            "evidence": ["scripted provider fixture"],
            "changed_files": [],
            "unresolved_risks": [],
        }
    )


def review(verdict="APPROVE"):
    return json.dumps(
        {
            "verdict": verdict,
            "summary": "scripted independent review",
            "findings": [] if verdict == "APPROVE" else ["missing evidence"],
        }
    )


class ScriptedProvider:
    name = "fake"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    async def run(self, prompt, *, model, title, cwd):
        self.calls.append(
            {"prompt": prompt, "model": model, "title": title, "cwd": cwd}
        )
        output_value = self.outputs.pop(0)
        if isinstance(output_value, Exception):
            raise output_value
        if isinstance(output_value, ProviderResult):
            return output_value
        return ProviderResult(
            output=output_value,
            usage=TokenUsage(
                input_tokens=100,
                cached_input_tokens=25,
                output_tokens=20,
                source="provider",
            ),
            provider=self.name,
            model=model,
            duration_seconds=0.01,
        )


class ConcurrentProvider(ScriptedProvider):
    def __init__(self, outputs):
        super().__init__(outputs)
        self.active = 0
        self.max_active = 0

    async def run(self, prompt, *, model, title, cwd):
        self.calls.append(
            {"prompt": prompt, "model": model, "title": title, "cwd": cwd}
        )
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            output_value = self.outputs.pop(0)
            return ProviderResult(
                output=output_value,
                usage=TokenUsage(input_tokens=10, output_tokens=5, source="fixture"),
                provider=self.name,
                model=model,
                duration_seconds=0.01,
            )
        finally:
            self.active -= 1


class MissingUsageProvider(ScriptedProvider):
    async def run(self, prompt, *, model, title, cwd):
        self.calls.append(
            {"prompt": prompt, "model": model, "title": title, "cwd": cwd}
        )
        return ProviderResult(
            output=self.outputs.pop(0),
            usage=TokenUsage(source="unavailable"),
            provider=self.name,
            model=model,
            duration_seconds=0.01,
        )


class GateObservingProvider(ScriptedProvider):
    def __init__(self):
        super().__init__([])
        self.writer_started = asyncio.Event()
        self.release_writer = asyncio.Event()
        self.planner_called = asyncio.Event()

    async def run(self, prompt, *, model, title, cwd):
        self.calls.append(
            {"prompt": prompt, "model": model, "title": title, "cwd": cwd}
        )
        if model == "small-builder-model":
            self.writer_started.set()
            await self.release_writer.wait()
            output_value = outcome(summary="write complete")
        elif model == "review-model":
            output_value = review()
        elif model == "overseer-model":
            self.planner_called.set()
            output_value = json.dumps(
                {
                    "tasks": [
                        {
                            "id": "read",
                            "description": "Analyze",
                            "complexity": "low",
                            "required_capabilities": ["analysis"],
                        }
                    ]
                }
            )
        else:
            output_value = outcome(summary="analysis complete")
        return ProviderResult(
            output=output_value,
            usage=TokenUsage(input_tokens=10, output_tokens=5, source="fixture"),
            provider=self.name,
            model=model,
            duration_seconds=0.01,
        )
def make_config(**overrides):
    data = {
        "providers": {
            "fake_read": {
                "command": "unused",
                "args": [],
                "enforced_access": "read_only",
                "pricing": {
                    "input_per_million_usd": 1,
                    "cached_input_per_million_usd": 0.5,
                    "output_per_million_usd": 2,
                },
            },
            "fake_write": {
                "command": "unused",
                "args": [],
                "enforced_access": "workspace_write",
                "pricing": {
                    "input_per_million_usd": 1,
                    "cached_input_per_million_usd": 0.5,
                    "output_per_million_usd": 2,
                },
            },
        },
        "overseer": {
            "identity": "Caller Codex",
            "role": "overseer",
            "provider": "fake_read",
            "model": "overseer-model",
            "capabilities": ["planning"],
            "strategy": "predict",
            "access": "read_only",
            "quality_tier": "high",
            "validation_retries": 0,
        },
        "workers": {
            "economy": {
                "identity": "Economy worker",
                "role": "worker",
                "provider": "fake_read",
                "model": "small-model",
                "capabilities": ["analysis"],
                "strategy": "agentic",
                "access": "read_only",
                "quality_tier": "economy",
                "cost_rank": 1,
                "max_output_tokens": 200,
                "validation_retries": 0,
            },
            "economy_builder": {
                "identity": "Economy builder",
                "role": "worker",
                "provider": "fake_write",
                "model": "small-builder-model",
                "capabilities": ["implementation"],
                "strategy": "agentic",
                "access": "workspace_write",
                "quality_tier": "economy",
                "cost_rank": 1,
                "max_output_tokens": 200,
                "validation_retries": 0,
            },
            "premium": {
                "identity": "Premium worker",
                "role": "worker",
                "provider": "fake_write",
                "model": "large-model",
                "capabilities": ["analysis", "implementation"],
                "strategy": "agentic",
                "access": "workspace_write",
                "quality_tier": "high",
                "cost_rank": 20,
                "max_output_tokens": 200,
                "validation_retries": 0,
            },
            "reviewer": {
                "identity": "Reviewer",
                "role": "reviewer",
                "provider": "fake_read",
                "model": "review-model",
                "capabilities": ["review"],
                "strategy": "predict",
                "access": "read_only",
                "quality_tier": "high",
                "cost_rank": 5,
                "max_output_tokens": 200,
                "validation_retries": 0,
            },
        },
        "budgets": {
            "max_concurrency": 2,
            "provider_retry_limit": 0,
            "max_provider_calls": 10,
            "max_total_tokens": 10000,
        },
        "verification": {"enabled": True, "complexities": ["high"]},
        "output": {
            "include_bus_history": True,
            "include_conversations": True,
        },
    }
    for key, value in overrides.items():
        data[key] = value
    return SwarmConfig.from_dict(data)


def provider_map(provider):
    return {"fake_read": provider, "fake_write": provider}


class SwarmRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_plan_skips_nested_overseer_call(self):
        provider = ScriptedProvider([outcome()])
        runner = SwarmRunner(make_config(), providers=provider_map(provider))
        plan = TaskPlan.from_data(
            [
                {
                    "id": "t1",
                    "description": "Analyze the failure",
                    "complexity": "low",
                    "required_capabilities": ["analysis"],
                    "estimated_input_tokens": 100,
                    "max_output_tokens": 200,
                }
            ],
            source="current_codex",
        )

        result = await runner.run("Investigate", cwd=".", plan=plan)

        self.assertEqual(result.record.status, "succeeded")
        self.assertEqual(result.record.plan_source, "current_codex")
        self.assertEqual(result.record.plan["tasks"][0]["id"], "t1")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["model"], "small-model")
        self.assertEqual(
            result.record.invocations[0].cost_source,
            "configured_pricing_estimate",
        )
        self.assertGreater(result.record.invocations[0].accounted_cost_usd, 0)
        self.assertIn("economy->overseer", result.record.conversations)
        topics = [event["topic"] for event in result.record.bus_history]
        self.assertEqual(
            topics,
            [
                "run.request",
                "plan.created",
                "task.assigned",
                "task.result",
                "run.aggregated",
                "run.completed",
            ],
        )
        plan_event = result.record.bus_history[1]
        self.assertTrue(plan_event["message"]["metadata"]["provider_call_skipped"])
        (
            request_event,
            plan_event,
            assignment_event,
            result_event,
            aggregation_event,
            completion_event,
        ) = result.record.bus_history
        self.assertEqual(
            plan_event["message"]["causation_id"],
            request_event["message"]["id"],
        )
        self.assertEqual(
            assignment_event["message"]["causation_id"],
            plan_event["message"]["id"],
        )
        self.assertEqual(
            result_event["message"]["causation_id"],
            assignment_event["message"]["id"],
        )
        self.assertEqual(
            aggregation_event["message"]["metadata"]["caused_by_ids"],
            [result_event["message"]["id"]],
        )
        self.assertEqual(
            completion_event["message"]["causation_id"],
            aggregation_event["message"]["id"],
        )
        self.assertTrue(
            all(
                event["message"]["correlation_id"] == result.record.run_id
                for event in result.record.bus_history
            )
        )
        self.assertIn("economy", result.record.agent_conversations)

    async def test_autonomous_run_uses_typed_planner_then_worker(self):
        provider = ScriptedProvider(
            [
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "t1",
                                "description": "Analyze it",
                                "complexity": "low",
                                "required_capabilities": ["analysis"],
                            }
                        ]
                    }
                ),
                outcome(summary="analysis complete"),
            ]
        )
        runner = SwarmRunner(make_config(), providers=provider_map(provider))

        result = await runner.run("Analyze it", cwd=".")

        self.assertEqual(result.record.status, "succeeded")
        self.assertEqual(
            [call["model"] for call in provider.calls],
            ["overseer-model", "small-model"],
        )
        self.assertEqual(result.record.plan_source, "provider_overseer")

    async def test_autonomous_planning_waits_for_checkout_writer(self):
        provider = GateObservingProvider()
        config = make_config()
        write_plan = TaskPlan.from_data(
            [
                {
                    "id": "write",
                    "description": "Implement",
                    "complexity": "low",
                    "required_capabilities": ["implementation"],
                    "access": "workspace_write",
                }
            ]
        )
        writer = SwarmRunner(config, providers=provider_map(provider))
        autonomous = SwarmRunner(config, providers=provider_map(provider))

        write_task = asyncio.create_task(
            writer.run("Implement", cwd=".", plan=write_plan)
        )
        await provider.writer_started.wait()
        autonomous_task = asyncio.create_task(autonomous.run("Analyze", cwd="."))
        await asyncio.sleep(0.01)

        self.assertFalse(provider.planner_called.is_set())
        provider.release_writer.set()
        write_result, autonomous_result = await asyncio.gather(
            write_task, autonomous_task
        )

        self.assertTrue(provider.planner_called.is_set())
        self.assertEqual(write_result.record.status, "succeeded")
        self.assertEqual(autonomous_result.record.status, "succeeded")

    async def test_high_complexity_task_uses_high_quality_worker_and_reviewer(self):
        provider = ScriptedProvider([outcome(), review()])
        runner = SwarmRunner(make_config(), providers=provider_map(provider))
        plan = TaskPlan.from_data(
            [
                {
                    "id": "t1",
                    "description": "Implement the change",
                    "complexity": "high",
                    "required_capabilities": ["implementation"],
                    "access": "workspace_write",
                }
            ]
        )

        result = await runner.run("Implement", cwd=".", plan=plan)

        self.assertEqual(result.record.status, "succeeded")
        self.assertEqual(result.record.tasks[0].agent_id, "premium")
        self.assertEqual(result.record.tasks[0].review["reviewer_id"], "reviewer")
        self.assertEqual(result.record.tasks[0].review["verdict"], "APPROVE")
        self.assertIn("reviewer->overseer", result.record.conversations)

    async def test_provider_failure_is_not_reported_as_success(self):
        provider = ScriptedProvider([ProviderError("auth failed")])
        runner = SwarmRunner(make_config(), providers=provider_map(provider))
        plan = TaskPlan.from_data(
            [
                {
                    "id": "t1",
                    "description": "Analyze the failure",
                    "complexity": "low",
                    "required_capabilities": ["analysis"],
                }
            ]
        )

        result = await runner.run("Investigate", cwd=".", plan=plan)

        self.assertEqual(result.record.status, "failed")
        self.assertEqual(result.record.tasks[0].status, "failed")
        self.assertIn("auth failed", result.record.tasks[0].error)
        self.assertEqual(result.record.invocations[0].status, "failed")
        self.assertGreater(result.record.usage["budget_accounted_tokens"], 0)

    async def test_failed_usage_overage_is_reported_as_budget_exhaustion(self):
        provider = ScriptedProvider(
            [
                ProviderError(
                    "failed after expensive call",
                    usage=TokenUsage(input_tokens=2000, output_tokens=10),
                )
            ]
        )
        config = make_config(
            budgets={
                "max_concurrency": 1,
                "provider_retry_limit": 0,
                "max_provider_calls": 2,
                "max_total_tokens": 1500,
            }
        )
        plan = TaskPlan.from_data(
            [
                {
                    "id": "t1",
                    "description": "Analyze",
                    "complexity": "low",
                    "required_capabilities": ["analysis"],
                    "max_output_tokens": 100,
                }
            ]
        )

        result = await SwarmRunner(config, providers=provider_map(provider)).run(
            "Analyze", cwd=".", plan=plan
        )

        self.assertEqual(result.record.status, "budget_exhausted")
        self.assertIn("BudgetExceeded", result.record.tasks[0].error)

    async def test_successful_output_is_preserved_after_reported_usage_overage(self):
        provider = ScriptedProvider(
            [
                ProviderResult(
                    output=outcome(summary="expensive but complete"),
                    usage=TokenUsage(input_tokens=2000, output_tokens=10),
                    provider="scripted",
                    model="fixture-model",
                    duration_seconds=0,
                )
            ]
        )
        config = make_config(
            budgets={
                "max_concurrency": 1,
                "provider_retry_limit": 0,
                "max_provider_calls": 2,
                "max_total_tokens": 1500,
            }
        )
        plan = TaskPlan.from_data(
            [
                {
                    "id": "t1",
                    "description": "Analyze",
                    "complexity": "low",
                    "required_capabilities": ["analysis"],
                    "max_output_tokens": 100,
                }
            ]
        )

        result = await SwarmRunner(config, providers=provider_map(provider)).run(
            "Analyze", cwd=".", plan=plan
        )

        self.assertEqual(result.record.status, "budget_exhausted")
        self.assertEqual(result.record.tasks[0].status, "succeeded")
        self.assertEqual(result.record.tasks[0].output, "expensive but complete")
        self.assertEqual(result.record.invocations[0].status, "succeeded")
        self.assertEqual(
            result.record.usage["budget_overage_reason"],
            "provider reported usage above the token budget",
        )

    async def test_success_without_usage_accounts_reservation_estimate(self):
        provider = MissingUsageProvider([outcome()])
        plan = TaskPlan.from_data(
            [
                {
                    "id": "t1",
                    "description": "Analyze",
                    "complexity": "low",
                    "required_capabilities": ["analysis"],
                    "max_output_tokens": 100,
                }
            ]
        )

        result = await SwarmRunner(make_config(), providers=provider_map(provider)).run(
            "Analyze", cwd=".", plan=plan
        )

        invocation = result.record.invocations[0]
        self.assertEqual(result.record.status, "succeeded")
        self.assertEqual(result.record.tasks[0].status, "succeeded")
        self.assertEqual(invocation.status, "succeeded")
        self.assertEqual(invocation.usage["source"], "unavailable")
        self.assertEqual(invocation.cost_source, "reservation_estimate")
        self.assertGreater(invocation.accounted_cost_usd, 0)
        self.assertEqual(
            result.record.usage["accounted_cost_usd"],
            result.record.usage["budget_accounted_cost_usd"],
        )

    async def test_failed_read_only_attempt_is_accounted_before_retry(self):
        provider = ScriptedProvider(
            [ProviderError("temporary", transient=True), outcome()]
        )
        config = make_config(
            budgets={
                "max_concurrency": 1,
                "provider_retry_limit": 1,
                "max_provider_calls": 4,
                "max_total_tokens": 10000,
            }
        )
        plan = TaskPlan.from_data(
            [
                {
                    "id": "t1",
                    "description": "Analyze",
                    "complexity": "low",
                    "required_capabilities": ["analysis"],
                }
            ]
        )

        result = await SwarmRunner(config, providers=provider_map(provider)).run(
            "Analyze", cwd=".", plan=plan
        )

        self.assertEqual(result.record.status, "succeeded")
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(
            result.record.invocations[0].cost_source, "reservation_estimate"
        )
        self.assertGreater(result.record.invocations[0].accounted_cost_usd, 0)
        self.assertGreater(result.record.usage["unknown_usage_calls"], 0)

    async def test_workspace_writer_never_retries_transient_provider_failure(self):
        provider = ScriptedProvider(
            [ProviderError("temporary", transient=True), outcome()]
        )
        config = make_config(
            budgets={
                "max_concurrency": 2,
                "provider_retry_limit": 1,
                "max_provider_calls": 4,
                "max_total_tokens": 10000,
            }
        )
        plan = TaskPlan.from_data(
            [
                {
                    "id": "write",
                    "description": "Implement change",
                    "complexity": "low",
                    "required_capabilities": ["implementation"],
                    "access": "workspace_write",
                }
            ]
        )

        result = await SwarmRunner(config, providers=provider_map(provider)).run(
            "Implement", cwd=".", plan=plan
        )

        self.assertEqual(result.record.status, "failed")
        self.assertEqual(len(provider.calls), 1)

    async def test_workspace_writers_are_serialized_in_one_checkout(self):
        provider = ConcurrentProvider([outcome(), review(), outcome(), review()])
        config = make_config(verification={"enabled": False})
        plan = TaskPlan.from_data(
            [
                {
                    "id": "write-a",
                    "description": "Implement A",
                    "complexity": "low",
                    "required_capabilities": ["implementation"],
                    "access": "workspace_write",
                },
                {
                    "id": "write-b",
                    "description": "Implement B",
                    "complexity": "low",
                    "required_capabilities": ["implementation"],
                    "access": "workspace_write",
                },
            ]
        )

        result = await SwarmRunner(config, providers=provider_map(provider)).run(
            "Implement both", cwd=".", plan=plan
        )

        self.assertEqual(result.record.status, "succeeded")
        self.assertEqual(provider.max_active, 1)
        self.assertTrue(all(task.review for task in result.record.tasks))

    async def test_low_complexity_workspace_write_is_still_reviewed(self):
        provider = ScriptedProvider([outcome(), review()])
        plan = TaskPlan.from_data(
            [
                {
                    "id": "write",
                    "description": "Implement change",
                    "complexity": "low",
                    "required_capabilities": ["implementation"],
                    "access": "workspace_write",
                }
            ]
        )

        result = await SwarmRunner(make_config(), providers=provider_map(provider)).run(
            "Implement", cwd=".", plan=plan
        )

        self.assertEqual(result.record.status, "succeeded")
        self.assertEqual(result.record.tasks[0].review["verdict"], "APPROVE")

    async def test_provider_call_budget_is_reserved_atomically(self):
        provider = ScriptedProvider([outcome(summary="first task")])
        config = make_config(
            budgets={
                "max_concurrency": 2,
                "provider_retry_limit": 0,
                "max_provider_calls": 1,
                "max_total_tokens": 10000,
            }
        )
        runner = SwarmRunner(config, providers=provider_map(provider))
        plan = TaskPlan.from_data(
            [
                {
                    "id": "t1",
                    "description": "Analyze first",
                    "complexity": "low",
                    "required_capabilities": ["analysis"],
                },
                {
                    "id": "t2",
                    "description": "Analyze second",
                    "complexity": "low",
                    "required_capabilities": ["analysis"],
                },
            ]
        )

        result = await runner.run("Analyze both", cwd=".", plan=plan)

        self.assertEqual(result.record.status, "budget_exhausted")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(
            sorted(task.status for task in result.record.tasks),
            ["failed", "succeeded"],
        )

    async def test_invalid_review_contract_fails_closed(self):
        provider = ScriptedProvider([outcome(), "Looks plausible"])
        runner = SwarmRunner(make_config(), providers=provider_map(provider))
        plan = TaskPlan.from_data(
            [
                {
                    "id": "t1",
                    "description": "Implement the change",
                    "complexity": "high",
                    "required_capabilities": ["implementation"],
                    "access": "workspace_write",
                }
            ]
        )

        result = await runner.run("Implement", cwd=".", plan=plan)

        self.assertEqual(result.record.status, "failed")
        self.assertEqual(result.record.tasks[0].status, "failed")
        self.assertIn("GenerationContractError", result.record.tasks[0].error)
        self.assertEqual(result.record.tasks[0].outcome["status"], "completed")

    async def test_rejected_review_is_preserved(self):
        provider = ScriptedProvider([outcome(), review("REJECT")])
        runner = SwarmRunner(make_config(), providers=provider_map(provider))
        plan = TaskPlan.from_data(
            [
                {
                    "id": "t1",
                    "description": "Implement the change",
                    "complexity": "high",
                    "required_capabilities": ["implementation"],
                    "access": "workspace_write",
                }
            ]
        )

        result = await runner.run("Implement", cwd=".", plan=plan)

        self.assertEqual(result.record.status, "failed")
        self.assertEqual(result.record.tasks[0].status, "rejected")
        self.assertEqual(result.record.tasks[0].review["verdict"], "REJECT")

    async def test_failed_dependency_blocks_downstream_without_a_model_call(self):
        provider = ScriptedProvider([outcome("failed", "first task failed")])
        runner = SwarmRunner(make_config(), providers=provider_map(provider))
        plan = TaskPlan.from_data(
            [
                {
                    "id": "t1",
                    "description": "Analyze first",
                    "complexity": "low",
                    "required_capabilities": ["analysis"],
                },
                {
                    "id": "t2",
                    "description": "Analyze dependent",
                    "complexity": "low",
                    "required_capabilities": ["analysis"],
                    "depends_on": ["t1"],
                },
            ]
        )

        result = await runner.run("Analyze chain", cwd=".", plan=plan)

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(
            [task.status for task in result.record.tasks], ["failed", "blocked"]
        )
        self.assertIn(
            "task.blocked", [event["topic"] for event in result.record.bus_history]
        )
        failed_event = next(
            event
            for event in result.record.bus_history
            if event["topic"] == "task.result"
        )
        blocked_event = next(
            event
            for event in result.record.bus_history
            if event["topic"] == "task.blocked"
        )
        self.assertIn(
            failed_event["message"]["id"],
            blocked_event["message"]["metadata"]["caused_by_ids"],
        )

    async def test_one_failed_dependency_blocks_task_while_another_is_unresolved(self):
        provider = ScriptedProvider(
            [
                outcome("failed", "first failed"),
                outcome(summary="gate passed"),
                outcome(summary="second passed"),
            ]
        )
        runner = SwarmRunner(make_config(), providers=provider_map(provider))
        plan = TaskPlan.from_data(
            [
                {
                    "id": "first",
                    "description": "Analyze first",
                    "complexity": "low",
                    "required_capabilities": ["analysis"],
                },
                {
                    "id": "gate",
                    "description": "Analyze gate",
                    "complexity": "low",
                    "required_capabilities": ["analysis"],
                },
                {
                    "id": "second",
                    "description": "Analyze second",
                    "complexity": "low",
                    "required_capabilities": ["analysis"],
                    "depends_on": ["gate"],
                },
                {
                    "id": "dependent",
                    "description": "Analyze dependent",
                    "complexity": "low",
                    "required_capabilities": ["analysis"],
                    "depends_on": ["first", "second"],
                },
            ]
        )

        result = await runner.run("Analyze graph", cwd=".", plan=plan)

        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(result.record.tasks[3].status, "blocked")
        self.assertIn("first", result.record.tasks[3].error)


if __name__ == "__main__":
    unittest.main()
