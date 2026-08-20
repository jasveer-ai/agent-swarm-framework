import unittest

import agent_swarm


class PublicAPITests(unittest.TestCase):
    def test_primary_runtime_contracts_are_exported(self):
        self.assertEqual(
            set(agent_swarm.__all__),
            {
                "SwarmConfig",
                "SwarmRunResult",
                "SwarmRunner",
                "TaskPlan",
                "TaskSpec",
                "load_config",
            },
        )


if __name__ == "__main__":
    unittest.main()
