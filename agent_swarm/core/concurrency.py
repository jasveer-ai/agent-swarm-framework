from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class WorkspaceGate:
    """Writer-exclusive gate for one run and one checkout.

    Read-only tasks may overlap. A workspace writer excludes every other task,
    including read-only reviewers, until its worker/review lifecycle completes.
    Waiting writers take priority so a steady stream of readers cannot starve a
    pending mutation.
    """

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @asynccontextmanager
    async def hold(self, access: str) -> AsyncIterator[None]:
        if access == "workspace_write":
            async with self._condition:
                self._waiting_writers += 1
                try:
                    await self._condition.wait_for(
                        lambda: not self._writer and self._readers == 0
                    )
                finally:
                    self._waiting_writers -= 1
                self._writer = True
            try:
                yield
            finally:
                async with self._condition:
                    self._writer = False
                    self._condition.notify_all()
            return

        async with self._condition:
            await self._condition.wait_for(
                lambda: not self._writer and self._waiting_writers == 0
            )
            self._readers += 1
        try:
            yield
        finally:
            async with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()
