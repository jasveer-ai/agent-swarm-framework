import unittest

from agent_swarm.core.config import AgentProfile
from agent_swarm.core.specialists import (
    ApprovalPolicy,
    NoEligibleSpecialist,
    PolicyDenied,
    SpecialistRegistry,
    SpecialistRouter,
    WorkSignal,
)


def specialist(agent_id, *, capabilities, access="read_only", cost_rank=10):
    return AgentProfile(
        agent_id=agent_id,
        identity=agent_id,
        role="worker",
        provider="fixture",
        model="fixture-model",
        capabilities=tuple(capabilities),
        strategy="agentic",
        access=access,
        cost_rank=cost_rank,
    )


class SpecialistRoutingTests(unittest.TestCase):
    def setUp(self):
        self.registry = SpecialistRegistry(
            (
                specialist("expensive", capabilities=("analysis",), cost_rank=20),
                specialist("economy", capabilities=("analysis",), cost_rank=5),
                specialist(
                    "writer",
                    capabilities=("analysis", "implementation"),
                    access="workspace_write",
                    cost_rank=1,
                ),
            )
        )
        self.policy = ApprovalPolicy(allowed_actions=("inspect", "modify"))

    def test_selects_registered_specialist_with_required_capabilities(self):
        selected, brief = SpecialistRouter(self.registry, self.policy).route(
            WorkSignal(
                id="inspect-1",
                summary="Inspect the result",
                requested_action="inspect",
                required_capabilities=("analysis",),
            )
        )

        self.assertEqual(selected.agent_id, "economy")
        self.assertEqual(brief.status, "approved")
        self.assertEqual(brief.selected_specialist_id, "economy")

    def test_routing_uses_lowest_cost_then_stable_agent_id(self):
        self.registry.register(
            specialist("also_economy", capabilities=("analysis",), cost_rank=5)
        )

        selected, _ = SpecialistRouter(self.registry, self.policy).route(
            WorkSignal(
                id="inspect-2",
                summary="Inspect the result",
                requested_action="inspect",
                required_capabilities=("analysis",),
            )
        )

        self.assertEqual(selected.agent_id, "also_economy")

    def test_no_eligible_specialist_fails_closed(self):
        with self.assertRaises(NoEligibleSpecialist):
            SpecialistRouter(self.registry, self.policy).route(
                WorkSignal(
                    id="missing-1",
                    summary="Need an unavailable capability",
                    requested_action="inspect",
                    required_capabilities=("security",),
                )
            )

    def test_access_policy_denial_fails_closed(self):
        policy = ApprovalPolicy(
            allowed_actions=("modify",), allowed_access=("read_only",)
        )
        with self.assertRaisesRegex(PolicyDenied, "Access 'workspace_write'"):
            SpecialistRouter(self.registry, policy).route(
                WorkSignal(
                    id="modify-1",
                    summary="Apply a change",
                    requested_action="modify",
                    required_capabilities=("implementation",),
                    access="workspace_write",
                )
            )

    def test_disallowed_action_fails_closed(self):
        with self.assertRaisesRegex(PolicyDenied, "Action 'modify'"):
            SpecialistRouter(self.registry, ApprovalPolicy()).route(
                WorkSignal(
                    id="modify-2",
                    summary="Apply a change",
                    requested_action="modify",
                    required_capabilities=("implementation",),
                    access="workspace_write",
                )
            )

    def test_contracts_round_trip_as_json(self):
        selected, brief = SpecialistRouter(self.registry, self.policy).route(
            WorkSignal(
                id="inspect-3",
                summary="Inspect the result",
                requested_action="inspect",
                required_capabilities=("analysis",),
            )
        )

        self.assertEqual(selected.agent_id, "economy")
        parsed_signal = WorkSignal.model_validate_json(
            WorkSignal(
                id="inspect-3",
                summary="Inspect the result",
                requested_action="inspect",
            ).model_dump_json(by_alias=True)
        )
        parsed_brief = type(brief).model_validate_json(
            brief.model_dump_json(by_alias=True)
        )
        parsed_policy = ApprovalPolicy.model_validate_json(
            self.policy.model_dump_json()
        )
        self.assertEqual(parsed_signal.signal_id, "inspect-3")
        self.assertEqual(parsed_brief.evidence[0].kind, "specialist_selection")
        self.assertEqual(parsed_policy.allowed_actions, ("inspect", "modify"))


if __name__ == "__main__":
    unittest.main()
