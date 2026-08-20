from __future__ import annotations

import ast
import inspect
import textwrap
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, Literal, get_type_hints

from src.core.config import AgentProfile
from src.core.run import RunRecord
from src.core.runtime import GenerationContractError

GenerationStrategy = Literal["predict", "agentic"]


def generation(
    *, strategy: GenerationStrategy
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Mark an ellipsis-bodied async method as provider-driven.

    The method name, signature, docstring, bound arguments, object state, and
    return annotation form the runtime contract. Normal method bodies remain
    deterministic Python.
    """

    def decorate(
        method: Callable[..., Awaitable[Any]],
    ) -> Callable[..., Awaitable[Any]]:
        if not inspect.iscoroutinefunction(method):
            raise TypeError("Generation methods must be async")
        try:
            parsed = ast.parse(textwrap.dedent(inspect.getsource(method)))
        except (OSError, TypeError, IndentationError, SyntaxError) as error:
            raise TypeError(
                f"Cannot verify generation method source for {method.__qualname__}"
            ) from error
        function = next(
            (
                node
                for node in ast.walk(parsed)
                if isinstance(node, ast.AsyncFunctionDef)
            ),
            None,
        )
        body = list(function.body) if function is not None else []
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        if not (
            len(body) == 1
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and body[0].value.value is Ellipsis
        ):
            raise TypeError(
                f"Generation method {method.__qualname__} must have an ellipsis body"
            )
        signature = inspect.signature(method)
        if signature.return_annotation in {inspect.Signature.empty, Any, "Any"}:
            raise TypeError(
                f"Generation method {method.__qualname__} needs a typed return annotation"
            )

        @wraps(method)
        async def generated(self: "ObjectAgent", *args: Any, **kwargs: Any) -> Any:
            if self.profile.strategy != strategy:
                raise ValueError(
                    f"Agent {self.profile.agent_id!r} uses strategy "
                    f"{self.profile.strategy!r}, but {method.__name__} requires {strategy!r}"
                )
            bound = signature.bind(self, *args, **kwargs)
            bound.apply_defaults()
            arguments = {
                name: value for name, value in bound.arguments.items() if name != "self"
            }
            return_type = get_type_hints(method).get("return", Any)
            if return_type is Any:
                raise GenerationContractError(
                    f"Generation method {method.__qualname__} resolved to Any"
                )
            return await self._generation_runtime.generate(
                profile=self.profile,
                agent=self,
                method_name=method.__name__,
                signature=str(signature),
                instructions=inspect.getdoc(method) or "",
                arguments=arguments,
                return_type=return_type,
                strategy=strategy,
                task_id=self.task_id,
                cwd=self.cwd,
                record=self.run_record,
            )

        generated.__generation_strategy__ = strategy  # type: ignore[attr-defined]
        generated.__generation_method__ = True  # type: ignore[attr-defined]
        return generated

    return decorate


class ObjectAgent:
    """A typed Python object whose normal methods are deterministic capabilities."""

    profile: AgentProfile
    identity: str
    capabilities: tuple[str, ...]
    access: str
    quality_tier: str
    task_id: str
    cwd: str
    run_record: RunRecord
    estimated_input_tokens: int
    max_output_tokens: int

    def __init__(
        self,
        *,
        profile: AgentProfile,
        generation_runtime: Any,
        task_id: str,
        cwd: str,
        run_record: RunRecord,
        estimated_input_tokens: int = 0,
        max_output_tokens: int = 0,
    ) -> None:
        self.profile = profile
        self.identity = profile.identity
        self.capabilities = profile.capabilities
        self.access = profile.access
        self.quality_tier = profile.quality_tier
        self.task_id = task_id
        self.cwd = cwd
        self.run_record = run_record
        self.estimated_input_tokens = estimated_input_tokens
        self.max_output_tokens = max_output_tokens
        self._generation_runtime = generation_runtime

    def public_state(self) -> Dict[str, Any]:
        """Return bounded, non-runtime state visible to generation methods."""

        return {
            "identity": self.identity,
            "capabilities": list(self.capabilities),
            "access": self.access,
            "quality_tier": self.quality_tier,
            "task_id": self.task_id,
            "workspace": self.cwd,
            "output_token_budget": (
                min(self.max_output_tokens, self.profile.max_output_tokens)
                if self.max_output_tokens
                else self.profile.max_output_tokens
            ),
        }

    def supports(self, capability: str) -> bool:
        """Deterministically check whether this object declares a capability."""

        return capability in self.capabilities
