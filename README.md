# Agent Swarm Framework

A typed, provider-configurable Python runtime for running agent swarms with a
caller-controlled overseer, capability-aware routing, bounded cost, and a full
explicit message-bus record.

## Architectural stance

This project implements a focused subset of the object-oriented agent model in
[*Object-Oriented Agents: A Software Engineering Paradigm for Agentic
Systems*](https://arxiv.org/abs/2607.20709):

- an agent is a normal Python object;
- fields hold identity, capabilities, access, and task state;
- normal method bodies are deterministic capabilities;
- async ellipsis methods marked with `@generation` are provider-driven;
- the class docstring, method name, signature, docstring, bound arguments, and
  return annotation form the generation contract;
- Pydantic validates every generated plan, task outcome, and review decision.

The framework deliberately does **not** depend on NVIDIA's
[`labs-OO-Agents`](https://github.com/NVIDIA-NeMo/labs-OO-Agents) runtime. The
paper is the stable architectural reference; useful upstream implementation
ideas can be adopted selectively behind local interfaces without coupling the
swarm to an alpha research runtime or its release cadence.

This is a smaller implementation, not a compatibility layer or a claim of
feature parity with NOOA.

```python
class WorkerAgent(ObjectAgent):
    def validate_assignment(self, task: TaskSpec) -> None:
        """Deterministic capability guard; no provider call."""
        missing = set(task.required_capabilities) - set(self.capabilities)
        if missing:
            raise ValueError(f"Missing capabilities: {sorted(missing)}")

    @generation(strategy="agentic")
    async def execute_task(self, goal: str, task: TaskSpec) -> TaskOutcome:
        """Execute one task and return an evidence-backed typed outcome."""
        ...
```

The decorator sends the arguments separately from the docstring and validates
the response against the annotated return schema. Hidden reasoning is never
copied into the swarm bus.

## Runtime model

The deterministic `SwarmRunner` owns orchestration:

1. Accept a caller-supplied `TaskPlan`, or ask the configured `PlanningAgent`
   for a typed plan.
2. Validate unique task IDs and an acyclic dependency graph.
3. Filter workers by role, capability, access boundary, and minimum quality.
4. Select the lowest `cost_rank` among the eligible profiles.
5. Instantiate a fresh `WorkerAgent` per task for isolated state and usage
   attribution.
6. Run read-only tasks concurrently, while serializing writers and their reviews
   against one checkout; block downstream tasks when a dependency fails.
7. Route configured task complexities and every workspace-write result through
   a typed, fail-closed `ReviewerAgent`.
8. Return task records, routing choices, provider attempts, normalized usage,
   ordered bus history, and conversation views.

Codex and OpenCode are example CLI adapters. They are provider configurations,
not hard-coded agent types. Additional providers implement the small
`ModelProvider` protocol.

## Install

```bash
git clone <repository-url>
cd agent-swarm-framework
python3 -m venv .venv
.venv/bin/pip install -e .
```

Provider CLIs continue to use their supported authentication. Never put
credentials in `.swarm/config.yaml`.

## Keep the current Codex session as overseer

The current Codex session can build the plan itself and hand it to the runtime:

```json
{
  "tasks": [
    {
      "id": "inspect",
      "description": "Inspect the failure and identify the owning code path",
      "required_capabilities": ["analysis"],
      "complexity": "low",
      "access": "read_only",
      "minimum_quality": "economy",
      "depends_on": [],
      "estimated_input_tokens": 2000,
      "max_output_tokens": 2000
    }
  ]
}
```

```bash
swarm "Investigate the failure" --plan-file /path/to/plan.json --json
```

`--plan-file` and `--plan-json` skip the configured planner provider. This
keeps the current Codex session as the actual top-level overseer and avoids a
second planning call. The returned run record is designed for the caller to
synthesize directly, so there is no automatic final overseer call either.

From Python:

```python
import asyncio

from src.core.config import load_config
from src.core.run import TaskPlan
from src.swarm_runner import SwarmRunner


async def main():
    plan = TaskPlan.from_data(
        [
            {
                "id": "inspect",
                "description": "Inspect the failure",
                "required_capabilities": ["analysis"],
                "complexity": "low",
            }
        ],
        source="current_codex",
    )
    result = await SwarmRunner(load_config(".swarm/config.yaml")).run(
        "Investigate the failure",
        cwd=".",
        plan=plan,
    )
    print(result.final_output)
    print(result.record.conversations)


asyncio.run(main())
```

Omit the plan for autonomous decomposition:

```bash
swarm "Investigate the failure" --json
```

## Configuration

The full example is in `.swarm/config.yaml`.

```yaml
providers:
  codex_readonly:
    command: codex
    args: [exec, --ephemeral, --json, --sandbox, read-only, -C, "{cwd}", -m, "{model}", "-"]
    prompt_mode: stdin
    output_format: codex-jsonl
    enforced_access: read_only

  codex_workspace:
    command: codex
    args: [exec, --ephemeral, --json, --sandbox, workspace-write, -C, "{cwd}", -m, "{model}", "-"]
    prompt_mode: stdin
    output_format: codex-jsonl
    enforced_access: workspace_write

overseer:
  role: overseer
  provider: codex_readonly
  model: gpt-5.6-sol
  strategy: predict
  access: read_only
  quality_tier: high

workers:
  codex_economy_builder:
    role: worker
    provider: codex_workspace
    model: gpt-5.6-luna
    capabilities: [documentation, implementation, testing]
    strategy: agentic
    access: workspace_write
    quality_tier: economy
    cost_rank: 10
    validation_retries: 0

budgets:
  max_concurrency: 2
  provider_retry_limit: 1
  max_provider_calls: 12
  max_total_tokens: 120000
  max_estimated_cost_usd: 0
```

Provider arguments are passed directly to `asyncio.create_subprocess_exec`;
the framework does not invoke a shell. Prompts must use standard input;
argument-mode prompts and prompt placeholders in configured arguments are
rejected so task content is not exposed through process arguments.

### Routing and cost

Routing applies safety and fitness constraints before price preference:

1. required role and capabilities;
2. exact required access (`read_only` or `workspace_write`) so a read-only task
   is not routed to a write-capable agent;
3. required quality (`economy`, `standard`, or `high`), defaulting from task
   complexity;
4. lowest `cost_rank`, with agent ID as a stable tie-break.

The profile access must exactly match `provider.enforced_access`. An
`unrestricted` provider cannot be bound to an agent profile, which keeps the
included OpenCode adapter inactive until an external sandbox or permission
policy enforces its boundary.

This prevents a cheap but incapable or over-privileged model from receiving a
task. Call count, token reservations, retries, timeouts, concurrency, and cost
are recorded by agent and provider/model. Provider-reported and configured-rate
estimates remain separate; failed attempts are conservatively charged against
their reservation when exact usage is unavailable. The same reservation-cost
provenance is retained for successful calls that omit usage telemetry.

Set `max_estimated_cost_usd` above zero only after adding versioned pricing for
every provider used by the run. An unpriced provider is rejected under a strict
USD limit instead of being treated as free. CLI adapters can enforce admission
between calls, but cannot guarantee a hard per-request dollar or token ceiling.
`max_output_tokens` is therefore an admission reservation and prompt budget for
CLI providers, not a provider-enforced cap; reported overage is detected only
after a call completes.

Read-only providers may retry transient failures and malformed typed responses
within the configured limits. Workspace writers never retry provider failures,
must set `validation_retries: 0`, and are serialized per real checkout path
across concurrent runs in the same Python event loop to avoid repeating or
overlapping mutations. Autonomous provider-backed planning acquires the same
checkout's read lease. Every successful workspace write is reviewed even when
optional read-only verification is disabled. Separate framework processes still
require external worktree or lock isolation.

### Security boundary

`codex exec --sandbox` provides an explicit read-only or workspace-write
filesystem boundary. A bounded Codex provider must configure exactly one
matching sandbox and cannot use sandbox bypasses, sandbox overrides, or extra
writable directories. OpenCode CLI permissions come from OpenCode
configuration; this framework marks the stock adapter `unrestricted` and does
not route work to it. Use a sandboxed provider or external execution boundary
before binding it.

The CLI adapter captures process output in memory, then truncates and redacts
diagnostics before persistence; the capture itself is not yet streaming or
memory-bounded. Timeout and cancellation terminate and reap the provider process
group so tool descendants do not continue editing in the background. Provider
reasoning events are not persisted.

The canonical history contains only explicit inter-agent envelopes and
normalized usage. Messages carry run correlation and request/response causation
IDs; dependency fan-in and terminal run aggregation also retain every causal
message ID. Subscriber delivery outcomes are recorded without persisting
callback error text.

## Run record

`SwarmRunResult` contains:

- terminal run and task status;
- caller or provider plan source;
- structured task outcomes and review decisions;
- every eligible routing candidate and selection reason;
- every provider attempt and usage/cost provenance;
- totals by agent and provider/model;
- ordered messages with run/task correlation, causation, and delivery status;
- conversations grouped both as `sender->receiver` and chronologically per
  participating agent.

Nothing is persisted by default. Pass `--output /path/run.json` to save the
full record explicitly. Task inputs and explicit agent messages are intentionally
preserved verbatim for auditability, so do not place secrets in plans or persist
a run record that contains sensitive task data.

## Tests

The default suite uses scripted providers and makes no paid model calls:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/python tests/smoke_test.py
.venv/bin/python tests/integration_swarm_test.py  # skips unless explicitly enabled
```

The suite covers object/generation contracts, typed validation retries,
caller-driven oversight, autonomous planning, dependency blocking, enforced
access and quality filtering, conservative failed-attempt accounting, atomic
budgets, writer serialization and no-retry policy, mandatory write review,
process-group cancellation, secret redaction, CLI JSONL parsing, causality,
delivery outcomes, and complete bus history.
