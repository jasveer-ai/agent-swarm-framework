# Agent Swarm Framework (ASF)

A modular, object-oriented framework for orchestrating multi-agent workflows. ASF provides the primitives for building hierarchical, asynchronous, and self-verifying agent systems.

## Core Features

* **Hierarchical Task Decomposition**: Use `Orchestrator` and `Sub-Orchestrator` classes to break complex goals into manageable sub-tasks.
* **Asynchronous Message Mesh**: A high-performance `MessageBus` for inter-agent communication using topic-based and wildcard routing.
* **Verified Execution (Builder/Reviewer)**: Built-in support for the "Bob & Alice" pattern to ensure work is audited before completion.
* **Dynamic Agent Objects**: Agents are Python objects that manage their own identity, role (Worker, Orchestrator, etc.), and capabilities.
* **CLI & Config**: A command-line interface (`swarm`) and a central `.swarm/config.yaml` for managing model providers and agent settings.

## Installation

```bash
# Clone the repo
git clone <repo_url>
cd agent-swarm-framework

# Install the framework and the 'swarm' CLI
pip install -e .
```

## Quick Start

### CLI Usage
Run a predefined workflow directly from your terminal:
```bash
swarm "your high-level goal here"
```

### Python Implementation
Integrate the framework into your own Python scripts:

```python
from src.core.bus import MessageBus
from src.orchestrator.base import Orchestrator

async def main():
    bus = MessageBus()
    orch = Orchestrator("main-orch", "Master", bus)
    await orch.decompose("My complex project goal")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

### Testing the Swarm
Run the built-in simulation to verify the Builder/Reviewer loop:
```bash
python3 tests/demo_bob_alice.py
```

## Configuration

Manage your model providers and agent roles in `.swarm/config.yaml`.

```yaml
orchestrator:
  provider: "openrouter"
  model: "google/gemma-4-31b-it"

worker_default:
  provider: "opencode"
  model: "opencode-go/deepseek-v4-flash"
```

---
*Developed for high-reliability AI workflows.*
