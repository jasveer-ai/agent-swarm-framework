from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from typing import AsyncIterator, Iterable


def normalize_workspace_paths(paths: Iterable[str]) -> tuple[str, ...]:
    """Validate caller-owned checkout-relative files or directories."""
    result = []
    for value in paths:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("workspace paths must be nonempty strings")
        value = value.strip()
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or str(path) == "."
            or ".." in path.parts
            or any(character in value for character in "\\\x00*?[]")
        ):
            raise ValueError("workspace paths must be literal checkout-relative paths")
        result.append(str(path))
    return tuple(dict.fromkeys(result))


def paths_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return any(
        a == "*" or b == "*" or a == b
        or a.startswith(b + "/") or b.startswith(a + "/")
        for a in left for b in right
    )


class WorkspaceGate:
    """Writer-exclusive gate for one run and one checkout.

    Default callers retain checkout-wide writer exclusion. Explicitly opted-in
    tasks with declared paths may overlap only when their scopes are disjoint.
    The worker and its review retain the same reservation. Unscoped tasks still
    conflict with all writers; queued conflicting writers have priority.
    """

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._active: dict[object, tuple[str, tuple[str, ...]]] = {}
        self._waiting: dict[object, tuple[str, tuple[str, ...]]] = {}

    @staticmethod
    def _conflicts(left, right) -> bool:
        return (
            "workspace_write" in (left[0], right[0])
            and paths_overlap(left[1], right[1])
        )

    def _can_enter(self, ticket: object, request) -> bool:
        if any(self._conflicts(request, active) for active in self._active.values()):
            return False
        for waiting_ticket, waiting in self._waiting.items():
            if waiting_ticket is ticket:
                if request[0] == "workspace_write":
                    break
                continue
            if waiting[0] == "workspace_write" and self._conflicts(request, waiting):
                return False
        return True

    @asynccontextmanager
    async def hold(
        self, access: str, *, workspace_paths: Iterable[str] = (),
        allow_disjoint_writes: bool = False,
    ) -> AsyncIterator[None]:
        if access not in {"read_only", "workspace_write"}:
            raise ValueError("unknown workspace access")
        declared = normalize_workspace_paths(workspace_paths)
        scopes = declared if allow_disjoint_writes and declared else ("*",)
        request = (access, scopes)
        ticket = object()
        async with self._condition:
            self._waiting[ticket] = request
            try:
                await self._condition.wait_for(lambda: self._can_enter(ticket, request))
                self._active[ticket] = request
            finally:
                self._waiting.pop(ticket, None)
                self._condition.notify_all()
        try:
            yield
        finally:
            async with self._condition:
                self._active.pop(ticket, None)
                self._condition.notify_all()
