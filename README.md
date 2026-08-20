# 🐝 Agent Swarm Framework

A typed, provider-configurable Python runtime for auditable agent swarms with a
caller-controlled overseer, capability-aware routing, explicit access
boundaries, and a complete message-bus record.

> **Status:** alpha. The typed core and hermetic suite are usable, but the
> provider CLI remains part of the trusted computing base and per-call CLI
> token or dollar ceilings are not hard limits.

The bee is the project mark: one swarm, specialized workers, and an observable
handoff trail. See [Architecture](docs/architecture.md),
[Contributing](CONTRIBUTING.md), [Security](SECURITY.md), and [License](LICENSE).

## Architectural stance

This project implements a focused subset of the object-oriented agent model in
[*NVIDIA-labs OO Agents: Native Python Object-Oriented
Agents*](https://arxiv.org/abs/2607.20709):

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
   ordered bus events, and derived conversation views.

Codex and OpenCode are example CLI adapters. They are provider configurations,
not hard-coded agent types. Additional providers implement the small
`ModelProvider` protocol.

## Generic specialist extension

For a narrow application-specific integration, construct a typed `WorkSignal`,
register generic `AgentProfile` specialists, and route it with an explicit
allow-list `ApprovalPolicy`. `SpecialistRouter` first checks the action and
access boundary, then selects the lowest `cost_rank` specialist that has every
required capability and the exact access boundary. Missing specialists and
policy denials raise terminal errors before a provider call.

```python
from agent_swarm.core.config import load_config
from agent_swarm.core.specialists import (
    ApprovalPolicy,
    SpecialistRegistry,
    SpecialistRouter,
    WorkSignal,
)

config = load_config(".swarm/config.yaml")
router = SpecialistRouter(
    SpecialistRegistry(config.workers),
    ApprovalPolicy(allowed_actions=("inspect",)),
)
specialist, brief = router.route(
    WorkSignal(
        id="inspect-1",
        summary="Inspect a bounded task",
        requested_action="inspect",
        required_capabilities=("analysis",),
        access="read_only",
    )
)
```

`WorkSignal`, `EvidenceArtifact`, and `DecisionBrief` are Pydantic contracts,
so callers can persist or exchange JSON without adopting a product-specific
agent model. The existing `SwarmRunner` continues to execute typed `TaskPlan`
work; its worker selector reuses the registry's exact capability/access filter.

Webhook ingress, durable queues, deployment packaging, and externally hosted
specialists remain future integration work. They are intentionally outside this
in-process framework boundary.

## Install

```bash
cd agent-swarm-framework
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Run these commands from the parent directory of a source checkout. The hosting
page provides its canonical HTTPS or SSH clone URL.

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

from agent_swarm import SwarmRunner, TaskPlan, load_config


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

[`examples/bob_alice.py`](examples/bob_alice.py) is a zero-cost scripted
builder/reviewer conversation with a complete bus transcript.

Omit the plan for autonomous decomposition:

```bash
swarm "Investigate the failure" --json
```

## Local ephemeral runs

Use a managed worktree when a local worker may change files but the caller only
needs a complete, portable artifact set:

```bash
swarm "Implement and verify the scoped change" \
  --plan-file /path/to/plan.json \
  --local-artifacts-dir /path/outside-the-repository/swarm-runs
```

This mode requires the source checkout to be clean. It creates a detached
temporary worktree at the current `HEAD`, runs every worker and reviewer there,
then writes one run-ID directory containing:

- `run.json`, the aggregate typed run record;
- `run.events.ndjson`, the canonical chronological message-bus history;
- `workspace.patch`, a binary Git patch containing all tracked and non-ignored
  untracked workspace changes;
- `manifest.json`, which binds the run, base commit, workspace status, artifact
  names, and SHA-256 digests.

The manifest is written last and marks the artifact directory complete. Only
after all four artifacts have been written atomically does the CLI remove the
managed worktree. Rejected, blocked, and modeled failed runs follow the same
artifact-first cleanup. If execution, artifact persistence, or cleanup fails
unexpectedly, the CLI keeps the recoverable run state and prints its exact path
instead of deleting unpreserved work.

Ignored build products, caches, virtual environments, and credentials are
deliberately excluded from `workspace.patch`; they are disposable execution
state, not source artifacts. Keep the artifact directory outside the source
repository and treat it as sensitive because plans, messages, and patches can
contain task data.

Managed Git commands and provider subprocesses also discard inherited
repository- and difftool-scoping variables such as `GIT_DIR`, `GIT_WORK_TREE`,
and `GIT_DIFF_*`. This prevents a CLI started by a hook, editor diff, or another
checkout from silently binding workers to the wrong repository. Explicit SSH
authentication configuration remains available to providers.

## Configuration

The full example is in `.swarm/config.yaml`.

Inspect a configuration without starting a provider or making a model call:

```bash
swarm config show
swarm config show --config /path/to/config.yaml --json
```

`config show` loads and validates the YAML before rendering the normalized
provider, agent, routing, budget, verification, output-history, and
bus-handoff configuration. It resolves executable paths passively by default.
Use `--probe-versions` only when needed: it runs each distinct resolved provider
executable directly with `--version`, using a short timeout. The normal
`swarm <goal> [options]` invocation remains unchanged.

The probe confirms only the executable version. It cannot prove that an account
is entitled to a configured model or that the installed CLI supports that model;
validate model IDs with the provider before launching a broad audit.

The sample profiles map high-assurance work to `gpt-5.6-sol`, standard work to
`gpt-5.6-terra`, and economy work to `gpt-5.6-luna`. These are explicit,
reviewable defaults rather than moving aliases; revalidate them when provider
guidance or the installed CLI changes.

```yaml
providers:
  codex_readonly:
    command: codex
    args: [exec, --ephemeral, --ignore-user-config, --json, --sandbox, read-only, -C, "{cwd}", -m, "{model}", "-"]
    prompt_mode: stdin
    output_format: codex-jsonl
    enforced_access: read_only

  codex_workspace:
    command: codex
    args: [exec, --ephemeral, --ignore-user-config, --json, --sandbox, workspace-write, -C, "{cwd}", -m, "{model}", "-"]
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
  max_concurrency: 1
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
task. `cost_rank` is a caller-defined preference, not a live price. Call count,
token reservations, retries, timeouts, concurrency, and cost are recorded by
agent and provider/model. Provider-reported and configured-rate estimates remain
separate; failed attempts are conservatively charged against their reservation
when exact usage is unavailable. The same reservation-cost provenance is
retained for successful calls that omit usage telemetry.

Set `max_estimated_cost_usd` above zero only after adding versioned pricing for
every provider used by the run. An unpriced provider is rejected under a strict
USD limit instead of being treated as free. CLI adapters can enforce admission
between calls, but cannot guarantee a hard per-request dollar or token ceiling.
`max_output_tokens` is therefore an admission reservation and prompt budget for
CLI providers, not a provider-enforced cap; reported overage is detected only
after a call completes. A completed output is preserved when that happens, while
the overall run is marked `budget_exhausted` and later admissions are refused.
The example starts with `max_concurrency: 1` so an uncalibrated provider cannot
start several unexpectedly expensive calls before the first usage report lands.

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

The example Codex adapters also pass `--ignore-user-config` so nested runs do
not inherit host user configuration. This makes their invocation configuration
deterministic, but it is not a substitute for the explicit CLI sandbox or any
external operating-system, network, or credential boundary.

The CLI adapter captures process output in memory, then truncates and redacts
diagnostics before persistence; the capture itself is not yet streaming or
memory-bounded. Timeout and cancellation terminate and reap the provider process
group so tool descendants do not continue editing in the background. Provider
reasoning events are not persisted.

The canonical bus history contains only explicit inter-agent envelopes.
Messages carry run correlation and request/response causation IDs; dependency
fan-in and terminal run aggregation also retain every causal message ID.
Subscriber delivery outcomes are recorded without persisting callback error
text. Normalized usage belongs to the aggregate run record rather than the bus
event schema.

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

Nothing is persisted by default. Export either or both explicit artifacts:

```bash
swarm "Inspect the repository" \
  --plan-file /path/to/plan.json \
  --output /path/run.json \
  --events-output /path/run.events.ndjson
```

- `run.json` is one aggregate snapshot with tasks, selections, invocations,
  usage, optional embedded history, and conversation projections.
- `run.events.ndjson` is a post-run export of the canonical chronological event
  sequence, with one complete bus envelope per line for replay and ingestion.

Both exports use atomic replacement. Task inputs and explicit agent messages
are intentionally preserved verbatim for auditability, so do not place secrets
in plans or persist artifacts containing sensitive task data.

For mutation-capable local runs, prefer `--local-artifacts-dir`. It adds the
workspace patch and manifest and owns the temporary worktree lifecycle described
in [Local ephemeral runs](#local-ephemeral-runs).

## Tests

The default suite uses scripted providers and makes no paid model calls:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/ruff check agent_swarm examples tests swarm.py
.venv/bin/python tests/smoke_test.py
.venv/bin/python tests/integration_swarm_test.py  # skips unless explicitly enabled
```

The suite covers object/generation contracts, typed validation retries,
caller-driven oversight, autonomous planning, dependency blocking, enforced
access and quality filtering, conservative failed-attempt accounting, atomic
budgets, writer serialization and no-retry policy, mandatory write review,
process-group cancellation, secret redaction, CLI JSONL parsing, causality,
delivery outcomes, atomic aggregate/NDJSON artifacts, and complete bus history.
It also proves that managed local runs preserve tracked, binary, empty, and
untracked changes before removing their worktree, while artifact or framework
failures retain a recovery path.
