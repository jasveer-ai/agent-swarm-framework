import asyncio
import sys
import os
import uuid

# Ensure framework is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.bus import MessageBus
from src.core.agent import Message, AgentRole, AgentStatus
from src.orchestrator.base import Orchestrator
from src.workers.builder import Builder
from src.workers.reviewer import Reviewer

class MockOrchestrator(Orchestrator):
    """A lightweight orchestrator for smoke testing"""
    async def decompose(self, goal: str):
        print(f"[SmokeTest] Decomposing: {goal}")
        return [{"id": "test-1", "description": goal, "complexity": "low"}]

    async def handle_message(self, message: Message):
        if message.type == "task_complete":
            print(f"[SmokeTest] ✅ SUCCESS: Task {message.payload['task_id']} finalized by Orchestrator.")
        else:
            await super().handle_message(message)

async def run_smoke_test():
    print("--- 🧪 STARTING AGENT SWARM SMOKE TEST ---")
    bus = MessageBus()
    
    # Initialize minimal agents
    orch = MockOrchestrator("orch-smoke", "Smoke-Orch", bus)
    bob = Builder("bob-smoke", "Smoke-Builder")
    alice = Reviewer("alice-smoke", "Smoke-Reviewer")

    # Setup Mesh Subscriptions
    await bus.subscribe("new_task", bob.handle_message)
    await bus.subscribe("build_report", alice.handle_message)
    await bus.subscribe("task_complete", orch.handle_message)

    # Define Goal
    goal = "Test Swarm Lifecycle"
    task_id = "task-smoke-123"

    # 1. Trigger Task
    print(f"[Step 1] Dispatching task {task_id}...")
    await bus.publish("new_task", Message(
        id=str(uuid.uuid4()),
        sender_id="system",
        receiver_id="workers",
        type="task",
        payload={"task_id": task_id, "description": goal, "complexity": "low"}
    ))

    # 2. Simulate the relay (Since this is a smoke test, we simulate the message handoffs)
    # In a real swarm, the agents handle the publish calls themselves.
    await asyncio.sleep(1)
    
    print(f"[Step 2] Simulating Bob's completion...")
    await bus.publish("build_report", Message(
        id=str(uuid.uuid4()),
        sender_id="bob-smoke",
        receiver_id="alice-smoke",
        type="build_report",
        payload={"task_id": task_id, "description": goal, "status": "success"}
    ))

    await asyncio.sleep(1)

    print(f"[Step 3] Simulating Alice's approval...")
    await bus.publish("task_complete", Message(
        id=str(uuid.uuid4()),
        sender_id="alice-smoke",
        receiver_id="orch-smoke",
        type="task_complete",
        payload={"task_id": task_id}
    ))

    await asyncio.sleep(1)
    print("--- 🏁 SMOKE TEST COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(run_smoke_test())
