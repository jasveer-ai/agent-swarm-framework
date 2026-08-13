import asyncio
import uuid
from src.core.agent import Message, AgentRole, AgentStatus
from src.core.bus import MessageBus
from src.orchestrator.base import Orchestrator
from src.workers.builder import Builder
from src.workers.reviewer import Reviewer

async def main():
    print("--- 🚀 Starting Agent Swarm Demo (Bob/Alice Pattern) ---")
    bus = MessageBus()

    # 1. Initialize Agents
    orchestrator = Orchestrator("orch-01", "Master Orchestrator", bus)
    bob = Builder("bob-01", "Bob (Builder)", model="deepseek-v4-flash")
    alice = Reviewer("alice-01", "Alice (Reviewer)", model="deepseek-v4-pro")

    # 2. Register Subscribers (Mesh Setup)
    # Orchestrator listens for completions
    await bus.subscribe("task_complete", orchestrator.handle_message)
    # Alice listens for build reports to start reviews
    await bus.subscribe("build_report", alice.handle_message)
    # Bob listens for tasks
    await bus.subscribe("new_task", bob.handle_message)

    # 3. Simulate a Task Workflow
    task_id = str(uuid.uuid4())[:8]
    task_payload = {
        "task_id": task_id,
        "description": "Implement Admin Dashboard Cards",
        "complexity": "medium"
    }

    print(f"\n[STEP 1] Orchestrator dispatching task: {task_id}")
    await bus.publish("new_task", Message(
        id=str(uuid.uuid4()),
        sender_id=orchestrator.agent_id,
        receiver_id=bob.agent_id,
        type="task",
        payload=task_payload
    ))

    # Simulate Bob completing the task and sending it to Alice
    # In a real swarm, Bob would do this internally after his execute_task
    await asyncio.sleep(1)
    print(f"\n[STEP 2] Bob finishing build. Sending report to Alice...")
    await bus.publish("build_report", Message(
        id=str(uuid.uuid4()),
        sender_id=bob.agent_id,
        receiver_id=alice.agent_id,
        type="build_report",
        payload={
            "task_id": task_id,
            "description": task_payload["description"],
            "status": "success"
        }
    ))

    # Simulate Alice finishing the review
    await asyncio.sleep(2)
    print(f"\n[STEP 3] Alice finishing review. Sending final approval to Orchestrator...")
    await bus.publish("task_complete", Message(
        id=str(uuid.uuid4()),
        sender_id=alice.agent_id,
        receiver_id=orchestrator.agent_id,
        type="task_complete",
        payload={"task_id": task_id, "verdict": "APPROVE"}
    ))

    await asyncio.sleep(1)
    print("\n--- ✅ Swarm Demo Finished Successfully ---")

if __name__ == "__main__":
    asyncio.run(main())
