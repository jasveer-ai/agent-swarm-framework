# 🌀 Agent Swarm Framework (ASF)

A modular, fractal, and object-oriented agent orchestration framework designed for high-reliability AI workflows. ASF moves away from static, hardcoded agent graphs toward a **Dynamic Mesh** architecture where agents are first-class Python objects capable of evolving their roles, capabilities, and hierarchical depth.

## 🧠 Core Philosophy

ASF is built on three foundational pillars:

1.  **Fractal Orchestration**: Complexity is managed by recursion. When a task is too large, an Orchestrator spawm a Sub-Orchestrator. This allows the swarm to scale its reasoning depth dynamically.
2.  **Verify-Before-Trust (VBT)**: No output is considered "complete" until it has passed a specialized Reviewer agent or a programmatic verification tool. This creates a self-correcting loop.
3.  **Dynamic Capability Mesh**: Agents are not locked into roles. A "Worker" can be promoted to a "Sub-Orchestrator" or assigned new specialized capabilities on-the-fly, making the swarm elastic and responsive to the task at hand.

## 🏗️ Architecture

The framework follows a hierarchical but fluid structure:

* **Orchestrator**: The high-level "Brain." Responsible for goal decomposition, task prioritization, and managing the lifecycle of sub-swarms.
* **Sub-Orchestrator**: The "Middle-Management." Manintains coordination for a specific cluster of workers or a specialized functional domain.
* **Worker (Leaf Agent)**: The "Hands." Highly specialized units designed to execute atomic, verifiable tasks (e.g., Code Building, Document Review, Web Search).

### The Communication Mesh
Communication is handled via an **Asynchronous Message Bus**. Agents communicate using structured `Message` objects via topics, supporting:
* **Direct Addressing**: `receiver_id` for targeted communication.
* **Broadcasting**: `topic` based messaging.
* **Mesh Listening**: Wildcard `*` subscriptions to observe the entire swarm's activity.

## 🚀 Getting Started

### Prerequisites
* Python 3.10+
* `asyncio` (standard library)

### Installation
```bash
git clone <repository-url>
cd agent-swarm-framework
# No heavy dependencies required for core, but highly recommended for extensions
```

### Running the Demo
To see the swarm in action (the classic **Bob & Alice** Builder/Reviewer pattern), run the test suite:

```bash
export PYTHONPATH=$PYTHONPATH:.
python3 tests/demo_bob_alice.py
```

## 🛠️ Development Guide

### Creating a New Agent
All agents must inherit from `BaseAgent` in `src/core/agent.py`.

```python
from src.core.agent import BaseAgent, AgentRole, Message

class MySpecialist(BaseAgent):
    def __init__(self, agent_id, identity):
        super().__init__(agent_id, identity)
        self.role = AgentRole.WORKER
        
    async def handle_message(self, message: Message):
        # Your logic here
        pass

    async def execute_task(self, task_id, task_details):
        # Your execution here
        pass
```

### Adding Capabilities
Capabilities are used to declare what an agent *can* do, allowing Orchestrators to match tasks to the right agents.

```python
from src.core.agent import Capability

search_cap = Capability(
    name="web_search", 
    description="Search the internet for real-time information"
)
my_agent.add_capability(search_cap)
```

## 📜 Protocols & Safety

All agents must adhere to the protocols defined in `.ai/os/protocols.md`. 
* **Error Handling**: Agents must catch exceptions and publish `task_error` messages to the bus.
* **Auditability**: Every message is logged to the `MessageBus` history for post-mortem analysis.
