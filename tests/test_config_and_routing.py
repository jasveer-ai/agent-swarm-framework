import math
import unittest

from pydantic import ValidationError

from agent_swarm.core.config import (
    ConfigurationError,
    ProviderConfig,
    RoutingRule,
    SwarmConfig,
)
from agent_swarm.core.routing import NoEligibleWorker, WorkerSelector
from agent_swarm.core.run import TaskOutcome, TaskPlan, TaskSpec


def config_data():
    return {
        "providers": {
            "fake_read": {
                "command": "fake",
                "args": [],
                "enforced_access": "read_only",
            },
            "fake_write": {
                "command": "fake",
                "args": [],
                "enforced_access": "workspace_write",
            },
        },
        "overseer": {
            "provider": "fake_read",
            "model": "overseer",
            "role": "overseer",
            "strategy": "predict",
            "access": "read_only",
            "quality_tier": "high",
        },
        "workers": {
            "expensive": {
                "provider": "fake_write",
                "model": "large",
                "role": "worker",
                "capabilities": ["implementation", "testing"],
                "strategy": "agentic",
                "access": "workspace_write",
                "quality_tier": "high",
                "cost_rank": 20,
                "validation_retries": 0,
            },
            "economy": {
                "provider": "fake_write",
                "model": "small",
                "role": "worker",
                "capabilities": ["implementation", "testing"],
                "strategy": "agentic",
                "access": "workspace_write",
                "quality_tier": "economy",
                "cost_rank": 5,
                "validation_retries": 0,
            },
            "reviewer": {
                "provider": "fake_read",
                "model": "review",
                "role": "reviewer",
                "capabilities": ["review"],
                "strategy": "predict",
                "access": "read_only",
                "quality_tier": "high",
                "cost_rank": 1,
            },
        },
        "routing": {
            "rules": [
                {"keywords": ["build", "fix"], "capabilities": ["implementation"]}
            ]
        },
        "budgets": {"max_total_tokens": 10000},
    }


class ConfigAndRoutingTests(unittest.TestCase):
    def test_selects_lowest_cost_after_capability_access_and_quality_filters(self):
        config = SwarmConfig.from_dict(config_data())
        selector = WorkerSelector(config.workers, config.routing_rules)

        selected, decision = selector.select(
            TaskSpec(
                id="t1",
                description="Fix the parser",
                complexity="low",
                access="workspace_write",
            )
        )

        self.assertEqual(selected.agent_id, "economy")
        self.assertEqual(decision.required_capabilities, ["implementation"])
        self.assertEqual(
            [candidate["agent_id"] for candidate in decision.eligible_agents],
            ["economy", "expensive"],
        )

    def test_high_complexity_excludes_economy_profile(self):
        config = SwarmConfig.from_dict(config_data())
        selected, _ = WorkerSelector(config.workers, config.routing_rules).select(
            TaskSpec(
                id="t1",
                description="Fix critical path",
                complexity="high",
                access="workspace_write",
            )
        )
        self.assertEqual(selected.agent_id, "expensive")

    def test_read_only_profile_cannot_receive_implementation(self):
        config = SwarmConfig.from_dict(config_data())
        with self.assertRaises(NoEligibleWorker):
            WorkerSelector(config.workers, config.routing_rules).select(
                TaskSpec(id="t1", description="Fix parser", complexity="low")
            )

    def test_reviewer_uses_explicit_capability_contract(self):
        config = SwarmConfig.from_dict(config_data())
        selector = WorkerSelector(config.workers, config.routing_rules)

        selected, decision = selector.select(
            TaskSpec(
                id="t1:review",
                description=(
                    "Review workspace-write implementation, testing, documentation, "
                    "and analysis results"
                ),
                required_capabilities=("review",),
                complexity="low",
                access="read_only",
            ),
            role="reviewer",
        )

        self.assertEqual(selected.agent_id, "reviewer")
        self.assertEqual(decision.required_capabilities, ["review"])

    def test_rejects_unknown_provider_reference(self):
        data = config_data()
        data["overseer"]["provider"] = "missing"
        with self.assertRaisesRegex(ConfigurationError, "Unknown provider"):
            SwarmConfig.from_dict(data)

    def test_rejects_profile_that_claims_a_different_access_than_provider(self):
        data = config_data()
        data["workers"]["economy"]["provider"] = "fake_read"
        with self.assertRaisesRegex(ConfigurationError, "provider-enforced boundary"):
            SwarmConfig.from_dict(data)

    def test_rejects_validation_retries_for_workspace_writer(self):
        data = config_data()
        data["workers"]["economy"]["validation_retries"] = 1
        with self.assertRaisesRegex(ConfigurationError, "validation_retries to 0"):
            SwarmConfig.from_dict(data)

    def test_plan_rejects_cycles(self):
        with self.assertRaisesRegex(ValidationError, "dependency cycle"):
            TaskPlan.from_data(
                [
                    {"id": "a", "description": "A", "depends_on": ["b"]},
                    {"id": "b", "description": "B", "depends_on": ["a"]},
                ]
            )

    def test_completed_outcome_requires_evidence(self):
        with self.assertRaisesRegex(ValidationError, "require at least one evidence"):
            TaskOutcome(status="completed", summary="done")

    def test_completed_outcome_rejects_blank_evidence(self):
        with self.assertRaisesRegex(ValidationError, "must not be blank"):
            TaskOutcome(status="completed", summary="done", evidence=("   ",))

    def test_routing_keywords_do_not_match_inside_other_words(self):
        selector = WorkerSelector(
            SwarmConfig.from_dict(config_data()).workers,
            (RoutingRule(keywords=("code",), capabilities=("implementation",)),),
        )

        capabilities = selector.required_capabilities(
            TaskSpec(
                id="inspect-codex",
                description="Inspect Codex provider compatibility",
                required_capabilities=("analysis",),
            )
        )

        self.assertEqual(capabilities, {"analysis"})

    def test_routing_keywords_match_standalone_terms(self):
        selector = WorkerSelector(
            SwarmConfig.from_dict(config_data()).workers,
            (RoutingRule(keywords=("code",), capabilities=("implementation",)),),
        )

        capabilities = selector.required_capabilities(
            TaskSpec(id="change", description="Inspect the code path")
        )

        self.assertEqual(capabilities, {"implementation"})

    def test_bounded_codex_rejects_duplicate_or_bypassed_sandbox(self):
        base = {
            "command": "codex",
            "enforced_access": "read_only",
        }
        with self.assertRaisesRegex(ConfigurationError, "exactly one"):
            ProviderConfig.from_dict(
                "codex",
                {
                    **base,
                    "args": [
                        "exec",
                        "--ignore-user-config",
                        "--sandbox",
                        "read-only",
                        "--sandbox",
                        "danger-full-access",
                    ],
                },
            )
        with self.assertRaisesRegex(ConfigurationError, "bypass"):
            ProviderConfig.from_dict(
                "codex",
                {
                    **base,
                    "args": [
                        "exec",
                        "--ignore-user-config",
                        "--sandbox",
                        "read-only",
                        "--dangerously-bypass-approvals-and-sandbox",
                    ],
                },
            )

    def test_provider_requires_stdin_and_finite_numeric_limits(self):
        with self.assertRaisesRegex(ConfigurationError, "standard input"):
            ProviderConfig.from_dict(
                "fixture",
                {
                    "command": "fixture",
                    "args": ["{prompt}"],
                    "enforced_access": "unrestricted",
                },
            )
        with self.assertRaisesRegex(ConfigurationError, "finite"):
            ProviderConfig.from_dict(
                "fixture",
                {
                    "command": "fixture",
                    "pricing": {
                        "input_per_million_usd": math.nan,
                        "output_per_million_usd": 1,
                    },
                },
            )
        data = config_data()
        data["budgets"] = {
            "max_total_tokens": 10000,
            "max_estimated_cost_usd": math.inf,
        }
        with self.assertRaisesRegex(ConfigurationError, "finite"):
            SwarmConfig.from_dict(data)


if __name__ == "__main__":
    unittest.main()
