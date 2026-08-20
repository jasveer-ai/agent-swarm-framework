from __future__ import annotations

import asyncio
import os
from typing import Dict, Mapping, Optional
from weakref import WeakKeyDictionary

from src.agents.planner import PlanningAgent
from src.agents.reviewer import ReviewerAgent
from src.agents.worker import WorkerAgent
from src.core.bus import MessageBus
from src.core.concurrency import WorkspaceGate
from src.core.config import AgentProfile, SwarmConfig
from src.core.protocol import Message
from src.core.routing import NoEligibleWorker, WorkerSelector
from src.core.run import (
    ReviewDecision,
    RunRecord,
    SwarmRunResult,
    TaskOutcome,
    TaskPlan,
    TaskRecord,
    TaskSpec,
)
from src.core.runtime import AgentRuntime, BudgetExceeded, GenerationContractError
from src.providers.base import ModelProvider, ProviderError, redact_diagnostic
from src.providers.cli import build_providers


class SwarmRunner:
    """Deterministic composition root for typed, provider-backed agent objects."""

    _workspace_gates: WeakKeyDictionary = WeakKeyDictionary()

    def __init__(
        self,
        config: SwarmConfig,
        *,
        providers: Optional[Mapping[str, ModelProvider]] = None,
    ) -> None:
        self.config = config
        self.providers = dict(providers or build_providers(config.providers))

    async def run(
        self,
        goal: str,
        *,
        cwd: str,
        plan: Optional[TaskPlan] = None,
    ) -> SwarmRunResult:
        bus = MessageBus()
        record = RunRecord(goal=goal)
        runtime = AgentRuntime(
            self.providers,
            self.config.providers,
            self.config.budgets,
        )
        selector = WorkerSelector(self.config.workers, self.config.routing_rules)
        loop = asyncio.get_running_loop()
        gates_for_loop = self._workspace_gates.setdefault(loop, {})
        workspace_gate = gates_for_loop.setdefault(
            os.path.realpath(cwd),
            WorkspaceGate(),
        )
        overseer = self.config.overseer

        request_message = Message(
            sender_id="caller",
            receiver_id=overseer.agent_id,
            type="run.request",
            payload={"goal": goal, "plan_supplied": plan is not None},
            run_id=record.run_id,
        )
        await bus.publish(
            "run.request",
            request_message,
        )
        plan_message_id = request_message.id
        completion_causation_id = request_message.id

        status = "failed"
        final_output = "The run did not start."
        try:
            if plan is None:
                async with workspace_gate.hold("read_only"):
                    plan, plan_message_id = await self._create_plan(
                        goal,
                        cwd,
                        overseer,
                        runtime,
                        record,
                        bus,
                        causation_id=request_message.id,
                    )
            else:
                plan_message = Message(
                    sender_id=overseer.agent_id,
                    receiver_id="swarm",
                    type="plan.created",
                    payload=plan.to_dict(),
                    run_id=record.run_id,
                    causation_id=request_message.id,
                    metadata={
                        "plan_source": plan.source,
                        "provider_call_skipped": True,
                    },
                )
                await bus.publish(
                    "plan.created",
                    plan_message,
                )
                plan_message_id = plan_message.id
            record.plan_source = plan.source
            record.plan = plan.to_dict()
            record.tasks = await self._execute_plan(
                plan,
                goal=goal,
                cwd=cwd,
                overseer=overseer,
                selector=selector,
                runtime=runtime,
                record=record,
                bus=bus,
                workspace_gate=workspace_gate,
                plan_message_id=plan_message_id,
            )
            status = self._run_status(record.tasks)
            final_output = self._format_outputs(record.tasks)
            terminal_message_ids = [
                task.terminal_message_id
                for task in record.tasks
                if task.terminal_message_id is not None
            ]
            aggregation_message = Message(
                sender_id="swarm",
                receiver_id=overseer.agent_id,
                type="run.aggregated",
                payload={
                    "status": status,
                    "tasks": [
                        {"task_id": task.task_id, "status": task.status}
                        for task in record.tasks
                    ],
                },
                run_id=record.run_id,
                causation_id=plan_message_id,
                metadata={"caused_by_ids": terminal_message_ids},
            )
            await bus.publish("run.aggregated", aggregation_message)
            completion_causation_id = aggregation_message.id
        except (
            ProviderError,
            BudgetExceeded,
            GenerationContractError,
            ValueError,
        ) as error:
            status = (
                "budget_exhausted" if isinstance(error, BudgetExceeded) else "failed"
            )
            final_output = f"{type(error).__name__}: {redact_diagnostic(str(error))}"

        record.usage = runtime.ledger.summary()
        record.finish(status)
        completion_message = Message(
            sender_id=overseer.agent_id,
            receiver_id="caller",
            type="run.completed",
            payload={"status": status, "final_output": final_output},
            run_id=record.run_id,
            causation_id=completion_causation_id,
        )
        await bus.publish(
            "run.completed",
            completion_message,
        )
        if self.config.output.include_bus_history:
            record.bus_history = bus.get_history(limit=None)
        if self.config.output.include_conversations:
            record.conversations = bus.conversations()
            record.agent_conversations = bus.agent_conversations()
        return SwarmRunResult(final_output=final_output, record=record)

    async def _create_plan(
        self,
        goal: str,
        cwd: str,
        overseer: AgentProfile,
        runtime: AgentRuntime,
        record: RunRecord,
        bus: MessageBus,
        causation_id: str,
    ) -> tuple[TaskPlan, str]:
        capabilities = tuple(
            sorted(
                {
                    capability
                    for worker in self.config.workers
                    if worker.role == "worker"
                    for capability in worker.capabilities
                }
            )
        )
        planner = PlanningAgent(
            profile=overseer,
            generation_runtime=runtime,
            task_id="__planning__",
            cwd=cwd,
            run_record=record,
        )
        plan = await planner.create_plan(goal, capabilities)
        plan = plan.model_copy(update={"source": "provider_overseer"})
        plan_message = Message(
            sender_id=overseer.agent_id,
            receiver_id="swarm",
            type="plan.created",
            payload=plan.to_dict(),
            run_id=record.run_id,
            causation_id=causation_id,
            metadata={
                "plan_source": plan.source,
                "provider": overseer.provider,
                "model": overseer.model,
            },
        )
        await bus.publish(
            "plan.created",
            plan_message,
        )
        return plan, plan_message.id

    async def _execute_plan(
        self,
        plan: TaskPlan,
        *,
        goal: str,
        cwd: str,
        overseer: AgentProfile,
        selector: WorkerSelector,
        runtime: AgentRuntime,
        record: RunRecord,
        bus: MessageBus,
        workspace_gate: WorkspaceGate,
        plan_message_id: str,
    ) -> list[TaskRecord]:
        pending: Dict[str, TaskSpec] = {task.task_id: task for task in plan.tasks}
        completed: Dict[str, TaskRecord] = {}

        while pending:
            blocked = [
                task
                for task in pending.values()
                if any(
                    dependency in completed
                    and completed[dependency].status != "succeeded"
                    for dependency in task.depends_on
                )
            ]
            for task in blocked:
                failed_dependencies = [
                    dependency
                    for dependency in task.depends_on
                    if dependency in completed
                    and completed[dependency].status != "succeeded"
                ]
                task_record = TaskRecord(
                    task_id=task.task_id,
                    description=task.description,
                    agent_id="unassigned",
                    status="blocked",
                    error=("Dependency failure: " + ", ".join(failed_dependencies)),
                )
                dependency_cause_ids = [
                    completed[dependency].terminal_message_id
                    for dependency in failed_dependencies
                    if completed[dependency].terminal_message_id is not None
                ]
                blocked_message = Message(
                    sender_id=overseer.agent_id,
                    receiver_id="caller",
                    type="task.blocked",
                    payload={
                        "task": task.to_dict(),
                        "failed_dependencies": failed_dependencies,
                    },
                    run_id=record.run_id,
                    task_id=task.task_id,
                    causation_id=(
                        dependency_cause_ids[0]
                        if dependency_cause_ids
                        else plan_message_id
                    ),
                    metadata={"caused_by_ids": dependency_cause_ids},
                )
                await bus.publish("task.blocked", blocked_message)
                task_record.terminal_message_id = blocked_message.id
                completed[task.task_id] = task_record
                del pending[task.task_id]

            if blocked:
                continue

            ready = [
                task
                for task in pending.values()
                if all(dependency in completed for dependency in task.depends_on)
            ]
            if not ready:
                if pending:
                    raise ValueError("validated task plan could not make progress")
                break

            task_records = await asyncio.gather(
                *(
                    self._execute_task_with_gate(
                        task,
                        goal=goal,
                        cwd=cwd,
                        overseer=overseer,
                        selector=selector,
                        runtime=runtime,
                        record=record,
                        bus=bus,
                        workspace_gate=workspace_gate,
                        plan_message_id=plan_message_id,
                    )
                    for task in ready
                )
            )
            for task_record in task_records:
                completed[task_record.task_id] = task_record
                del pending[task_record.task_id]

        return [completed[task.task_id] for task in plan.tasks]

    async def _execute_task_with_gate(
        self,
        task: TaskSpec,
        *,
        goal: str,
        cwd: str,
        overseer: AgentProfile,
        selector: WorkerSelector,
        runtime: AgentRuntime,
        record: RunRecord,
        bus: MessageBus,
        workspace_gate: WorkspaceGate,
        plan_message_id: str,
    ) -> TaskRecord:
        async with workspace_gate.hold(task.access):
            return await self._execute_task(
                task,
                goal=goal,
                cwd=cwd,
                overseer=overseer,
                selector=selector,
                runtime=runtime,
                record=record,
                bus=bus,
                plan_message_id=plan_message_id,
            )

    async def _execute_task(
        self,
        task: TaskSpec,
        *,
        goal: str,
        cwd: str,
        overseer: AgentProfile,
        selector: WorkerSelector,
        runtime: AgentRuntime,
        record: RunRecord,
        bus: MessageBus,
        plan_message_id: str,
    ) -> TaskRecord:
        worker: Optional[AgentProfile] = None
        outcome: Optional[TaskOutcome] = None
        trace = {"latest_message_id": plan_message_id}
        try:
            worker, selection = selector.select(task)
            record.selections.append(selection)
            assignment_message = Message(
                sender_id=overseer.agent_id,
                receiver_id=worker.agent_id,
                type="task.assigned",
                payload={
                    "goal": goal,
                    "task": task.to_dict(),
                    "selection": {
                        "eligible_agents": selection.eligible_agents,
                        "reason": selection.reason,
                    },
                },
                run_id=record.run_id,
                task_id=task.task_id,
                causation_id=plan_message_id,
                metadata={"provider": worker.provider, "model": worker.model},
            )
            await bus.publish(
                "task.assigned",
                assignment_message,
            )
            trace["latest_message_id"] = assignment_message.id
            agent = WorkerAgent(
                profile=worker,
                generation_runtime=runtime,
                task_id=task.task_id,
                cwd=cwd,
                run_record=record,
                estimated_input_tokens=task.estimated_input_tokens,
                max_output_tokens=task.max_output_tokens,
            )
            agent.validate_assignment(task)
            outcome = await agent.execute_task(goal, task)
            outcome_payload = outcome.model_dump(mode="json")
            result_message = Message(
                sender_id=worker.agent_id,
                receiver_id=overseer.agent_id,
                type="task.result",
                payload=outcome_payload,
                run_id=record.run_id,
                task_id=task.task_id,
                causation_id=assignment_message.id,
                metadata={"provider": worker.provider, "model": worker.model},
            )
            await bus.publish(
                "task.result",
                result_message,
            )
            trace["latest_message_id"] = result_message.id

            status = {
                "completed": "succeeded",
                "blocked": "blocked",
                "failed": "failed",
            }[outcome.status]
            review = None
            if status == "succeeded" and (
                task.access == "workspace_write"
                or (
                    self.config.verification.enabled
                    and task.complexity in self.config.verification.complexities
                )
            ):
                review = await self._review_task(
                    task,
                    outcome,
                    cwd,
                    overseer,
                    worker,
                    selector,
                    runtime,
                    record,
                    bus,
                    causation_id=result_message.id,
                    trace=trace,
                )
                if review["verdict"] != "APPROVE":
                    status = "rejected"
            return TaskRecord(
                task_id=task.task_id,
                description=task.description,
                agent_id=worker.agent_id,
                status=status,
                output=outcome.summary,
                outcome=outcome_payload,
                review=review,
                terminal_message_id=trace["latest_message_id"],
            )
        except (
            NoEligibleWorker,
            ProviderError,
            BudgetExceeded,
            GenerationContractError,
            ValueError,
        ) as error:
            agent_id = worker.agent_id if worker else "unassigned"
            safe_error = f"{type(error).__name__}: {redact_diagnostic(str(error))}"
            failed_message = Message(
                sender_id=agent_id,
                receiver_id=overseer.agent_id,
                type="task.failed",
                payload={"error": safe_error},
                run_id=record.run_id,
                task_id=task.task_id,
                causation_id=trace["latest_message_id"],
            )
            await bus.publish("task.failed", failed_message)
            return TaskRecord(
                task_id=task.task_id,
                description=task.description,
                agent_id=agent_id,
                status="failed",
                output=outcome.summary if outcome else "",
                outcome=outcome.model_dump(mode="json") if outcome else None,
                error=safe_error,
                terminal_message_id=failed_message.id,
            )

    async def _review_task(
        self,
        task: TaskSpec,
        outcome: TaskOutcome,
        cwd: str,
        overseer: AgentProfile,
        worker: AgentProfile,
        selector: WorkerSelector,
        runtime: AgentRuntime,
        record: RunRecord,
        bus: MessageBus,
        causation_id: str,
        trace: Dict[str, str],
    ) -> dict:
        review_task = TaskSpec(
            id=f"{task.task_id}:review",
            description=f"Review the result for {task.description}",
            required_capabilities=("review",),
            complexity=task.complexity,
            access="read_only",
            minimum_quality=task.minimum_quality,
        )
        reviewer, selection = selector.select(
            review_task,
            role="reviewer",
            exclude_agent_ids=(worker.agent_id,),
        )
        record.selections.append(selection)
        review_request = Message(
            sender_id=overseer.agent_id,
            receiver_id=reviewer.agent_id,
            type="review.request",
            payload={
                "task": task.to_dict(),
                "outcome": outcome.model_dump(mode="json"),
            },
            run_id=record.run_id,
            task_id=task.task_id,
            causation_id=causation_id,
            metadata={"provider": reviewer.provider, "model": reviewer.model},
        )
        await bus.publish(
            "review.request",
            review_request,
        )
        trace["latest_message_id"] = review_request.id
        agent = ReviewerAgent(
            profile=reviewer,
            generation_runtime=runtime,
            task_id=review_task.task_id,
            cwd=cwd,
            run_record=record,
        )
        decision: ReviewDecision = await agent.review_task(task, outcome)
        review = {
            "reviewer_id": reviewer.agent_id,
            **decision.model_dump(mode="json"),
        }
        review_result = Message(
            sender_id=reviewer.agent_id,
            receiver_id=overseer.agent_id,
            type="review.result",
            payload=review,
            run_id=record.run_id,
            task_id=task.task_id,
            causation_id=review_request.id,
            metadata={"provider": reviewer.provider, "model": reviewer.model},
        )
        await bus.publish(
            "review.result",
            review_result,
        )
        trace["latest_message_id"] = review_result.id
        return review

    @staticmethod
    def _run_status(tasks: list[TaskRecord]) -> str:
        if any(
            task.error and task.error.startswith("BudgetExceeded:") for task in tasks
        ):
            return "budget_exhausted"
        succeeded = sum(task.status == "succeeded" for task in tasks)
        if succeeded == len(tasks):
            return "succeeded"
        if succeeded:
            return "partial"
        return "failed"

    @staticmethod
    def _format_outputs(tasks: list[TaskRecord]) -> str:
        sections = []
        for task in tasks:
            content = task.output or task.error or "No output"
            sections.append(
                f"[{task.status}] {task.task_id} ({task.agent_id})\n{content}"
            )
        return "\n\n".join(sections)
