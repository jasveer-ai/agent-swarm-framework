import asyncio
import unittest

from agent_swarm.core.concurrency import WorkspaceGate, normalize_workspace_paths
from agent_swarm.core.config import BudgetConfig, ConfigurationError
from agent_swarm.core.run import TaskSpec


class WorkspaceScopeTests(unittest.IsolatedAsyncioTestCase):
    async def assert_overlap(self, first, second, *, scoped, expected):
        gate = WorkspaceGate()
        first_entered, second_entered, release = (
            asyncio.Event(), asyncio.Event(), asyncio.Event()
        )

        async def worker(path, entered):
            async with gate.hold(
                "workspace_write", workspace_paths=(path,),
                allow_disjoint_writes=scoped,
            ):
                entered.set()
                await release.wait()

        a = asyncio.create_task(worker(first, first_entered))
        await first_entered.wait()
        b = asyncio.create_task(worker(second, second_entered))
        await asyncio.sleep(0)
        try:
            self.assertEqual(second_entered.is_set(), expected)
        finally:
            release.set()
            await asyncio.gather(a, b)

    async def test_default_still_serializes_disjoint_writers(self):
        await self.assert_overlap("Sources/A", "Sources/B", scoped=False, expected=False)

    async def test_explicit_disjoint_writers_overlap(self):
        await self.assert_overlap("Sources/A", "Sources/B", scoped=True, expected=True)

    async def test_parent_scope_excludes_child_writer(self):
        await self.assert_overlap("Sources/A", "Sources/A/View.swift", scoped=True, expected=False)

    async def test_similar_directory_names_do_not_conflict(self):
        await self.assert_overlap("Sources/A", "Sources/AB", scoped=True, expected=True)

    async def test_unscoped_reader_waits_for_scoped_writer(self):
        gate = WorkspaceGate()
        entered = asyncio.Event()

        async def read():
            async with gate.hold("read_only"):
                entered.set()

        async with gate.hold("workspace_write", workspace_paths=("A",), allow_disjoint_writes=True):
            reader = asyncio.create_task(read())
            await asyncio.sleep(0)
            self.assertFalse(entered.is_set())
        await reader
        self.assertTrue(entered.is_set())

    async def test_cancelled_waiter_does_not_block_readers(self):
        gate = WorkspaceGate()

        async def write():
            async with gate.hold("workspace_write"):
                pass

        async with gate.hold("read_only"):
            writer = asyncio.create_task(write())
            await asyncio.sleep(0)
            writer.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await writer
            async def read_once():
                async with gate.hold("read_only"):
                    pass
            await asyncio.wait_for(read_once(), timeout=1)

    async def test_exception_releases_scope(self):
        gate = WorkspaceGate()
        with self.assertRaises(RuntimeError):
            async with gate.hold("workspace_write", workspace_paths=("A",), allow_disjoint_writes=True):
                raise RuntimeError("worker failure")
        async def write_once():
            async with gate.hold("workspace_write", workspace_paths=("A",), allow_disjoint_writes=True):
                pass
        await asyncio.wait_for(write_once(), timeout=1)

    def test_invalid_or_ambiguous_paths_fail_before_dispatch(self):
        for path in (".", "../other", "/absolute", "Sources/*", "A\\B", ""):
            with self.subTest(path=path), self.assertRaises(ValueError):
                TaskSpec(id="task", description="Implement", workspace_paths=(path,))

    def test_scope_normalization_and_boolean_opt_in(self):
        self.assertEqual(normalize_workspace_paths(("Sources/A/", "Sources/A")), ("Sources/A",))
        self.assertFalse(BudgetConfig.from_dict({}).allow_disjoint_workspace_writes)
        self.assertTrue(BudgetConfig.from_dict({"allow_disjoint_workspace_writes": True}).allow_disjoint_workspace_writes)
        with self.assertRaises(ConfigurationError):
            BudgetConfig.from_dict({"allow_disjoint_workspace_writes": "false"})
