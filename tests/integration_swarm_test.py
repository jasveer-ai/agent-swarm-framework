import asyncio
import sys
import os
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.bus import MessageBus
from src.core.agent import Message
from src.orchestrator.base import Orchestrator
from src.workers.builder import Builder
from src.workers.reviewer import Reviewer

async def run_live_test():
    print("\n" + "="*60)
    print("LIVE SWARM TEST — Real opencode-go models")
    print("="*60 + "\n")
    
    bus = MessageBus()
    
    orch = Orchestrator("master-orch", "Orchestrator", bus)
    bob = Builder("bob-1", "Bob (Builder)", model="opencode-go/deepseek-v4-flash", bus=bus)
    alice = Reviewer("alice-1", "Alice (Reviewer)", model="opencode-go/deepseek-v4-pro", bus=bus)
    
    await bus.subscribe("new_task", bob.handle_message)
    await bus.subscribe("build_report", alice.handle_message)
    await bus.subscribe("task_complete", orch.handle_message)
    
    # A real, measurable goal that opencode can act on
    goal = "Create a file named swarm_proof.txt in the current directory containing the text 'Agent Swarm is operational'"
    
    tasks = await orch.decompose(goal)
    # Inject the actual goal into tasks so opencode knows what to do
    for t in tasks:
        t["goal"] = goal
    
    print(f"Decomposed into {len(tasks)} tasks.\n")
    
    for task in tasks:
        await bus.publish("new_task", Message(
            id=str(uuid.uuid4()),
            sender_id=orch.agent_id,
            receiver_id="workers",
            type="task",
            payload=task
        ))
    
    print("Waiting for full cycle (Build -> Review -> Complete)...\n")
    for i in range(90):  # 90 seconds timeout
        await asyncio.sleep(1)
        if len(orch.task_history) >= len(tasks):
            break
    
    print("\n" + "="*60)
    print(f"RESULTS: {len(orch.task_history)}/{len(tasks)} tasks completed")
    for entry in orch.task_history:
        print(f"  Task {entry['task_id']}: {entry['verdict']}")
    print("="*60)
    
    # Check if opencode actually created the file
    if os.path.exists("swarm_proof.txt"):
        with open("swarm_proof.txt") as f:
            content = f.read()
        print(f"\nFILE CHECK: swarm_proof.txt exists ({len(content)} bytes)")
        print(f"Content: {content[:200]}")
    else:
        print("\nFILE CHECK: swarm_proof.txt NOT created (opencode may have failed)")
    
    return len(orch.task_history) >= len(tasks)

if __name__ == "__main__":
    success = asyncio.run(run_live_test())
    sys.exit(0 if success else 1)
