# ASF — NOOA Alignment Plan

## Audit: What We Have vs. NOOA (arXiv:2607.20709)

### ✅ Already implemented (PDF analysis was wrong — source was inaccessible)
| Capability | Status | Location |
|-----------|--------|----------|
| Agent-as-Python-object (ObjectAgent) | ✅ Done | `agent_swarm/agents/base.py` |
| @generation decorator (ellipsis body) | ✅ Done | `agent_swarm/agents/base.py` |
| Predict/Agentic strategies | ✅ Done | `@generation(strategy="predict"|"agentic")` |
| Typed I/O contracts w/ Pydantic validation | ✅ Done | `core/runtime.py` — `_validate_return()` |
| Bounded/preview state (public_state) | ✅ Done | `agents/base.py` + `_bounded_json()` |
| Provider abstraction | ✅ Done | `providers/base.py` + `providers/cli.py` |
| Multi-agent orchestration | ✅ Done | `orchestrator/`, `sub_orchestrator/`, `swarm_runner.py` |
| Config validation & inspection | ✅ Done | `core/config.py`, `core/config_inspection.py` |
| Git worktree isolation | ✅ Done | `core/worktree.py` |

### 🚧 Missing (actionable gaps)
| Capability | Priority | Epic | Notes |
|-----------|----------|------|-------|
| Long-term memory subsystem | High | #1 | 7-tool memory API + ACT-R ranking |
| CodeAct REPL (in-process Python) | High | #2 | execute_python within generation |
| Per-method strategy/provider override | Medium | #3 | decorator-level config |
| ContextManager / EventManager API | Medium | #5 | agent-queryable context blocks |
| Standardized benchmark evaluation | Medium | #4 | SWE-bench, TerminalBench, ARC-AGI |
| CI & coverage improvements | Low | #6 | 80% target, mypy strict |

### 🏛️ Design divergence (NOT gaps — intentional choices)
| Aspect | NOOA approach | ASF approach | Rationale |
|--------|-------------|-------------|-----------|
| Pass-by-reference | Live Python refs with bounded preview | Message-bus serialization | ASF is swarm-oriented; agents are separate processes, not in-memory objects |
| Agent identity | Single agent with many methods | Many role-specific agent classes | ASF optimizes for role isolation and audit trails |
| Execution isolation | In-process REPL sandbox | Git worktree + CLI sandbox | ASF targets real-world code execution, not REPL |
| Coordination | Emergent from code execution | Orchestrator-driven | ASF needs deterministic, auditable task graphs |

## GitHub Issues
https://github.com/jasveer-ai/agent-swarm-framework/issues

| # | Title | Epic | Priority |
|---|-------|------|----------|
| 1 | Long-term Memory Subsystem | memory | High |
| 2 | CodeAct-Style REPL Execution | codeact | High |
| 3 | Provider Pass-Through & Strategy Dispatch | contracts | Medium |
| 4 | Benchmarking & Evaluation Suite | benchmarking | Medium |
| 5 | ContextManager & EventManager APIs | contracts | Medium |
| 6 | CI, Coverage & Developer Experience | infra | Low |

## Labels
- `epic:memory`, `epic:codeact`, `epic:contracts`, `epic:benchmarking`, `epic:infra`
- `priority:high`, `priority:medium`, `priority:low`