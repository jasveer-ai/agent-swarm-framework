# Agent Swarm Framework (ASF)

A typed, provider-configurable Python runtime for auditable agent swarms with caller-controlled oversight.

## Read order

1. `README.md` — framework overview, architecture, quick start
2. `docs/architecture.md` — component boundaries, run lifecycle, artifact model
3. `pyproject.toml` — package metadata, dependencies, CLI entrypoint
4. `CONTRIBUTING.md` — development practices, test structure, review standards

## V3 Contracts (current, as of 2026-08-21)

### Package structure
- `agent_swarm/agents/` — `ObjectAgent`, `@generation` decorator, specialist agents (Planner, Reviewer, Worker)
- `agent_swarm/core/` — `MessageBus`, `SwarmRunner`, `AgentRuntime`, `UsageLedger`, config, routing, worktree
- `agent_swarm/providers/` — `ModelProvider` protocol, CLI adapter implementations
- `agent_swarm/orchestrator/` — orchestration base classes
- `agent_swarm/workers/` — worker base classes (Builder, Reviewer)
- `agent_swarm/sub_orchestrator/` — sub-orchestrator base
- `agent_swarm/cli.py` — `swarm` CLI entrypoint

### Key type contracts
- **Message** — `sender_id`, `receiver_id`, `type` (MessageType enum), `payload`, `id`, `run_id`, `task_id`, `correlation_id`, `causation_id`
- **Task** — `task_id`, `description`, `status`, `assigned_to`, `result`
- **TaskPlan** — Pydantic-validated plan with acyclic dependency graph
- **AgentProfile** — identity, capabilities, access boundary, quality_tier, cost_rank, strategy, provider, model
- **ObjectAgent** — typed Python object; deterministic method bodies are capabilities; `@generation` methods are provider-driven
- **SwarmRunResult** — aggregate run record with task records, routing, usage, bus history

### CLI usage
```bash
swarm "your high-level goal" [--config .swarm/config.yaml] [--plan-file plan.json] [--json] [--output run.json]
```

### Provider configs (Codex-based)
- `codex_readonly` — sandbox read-only, economy→high assurance tiers
- `codex_workspace` — sandbox workspace-write, economy→high tiers
- `opencode_worker` — OpenCode CLI for builds/review

## No credentials in this repo
Provider CLI credentials live in the user's shell env. This repo contains only the adapter command configurations under `.swarm/config.yaml`.

## Policy
This repo may only tighten safety constraints, never loosen them. See `.swarm/config.yaml` for budget limits and review policy.