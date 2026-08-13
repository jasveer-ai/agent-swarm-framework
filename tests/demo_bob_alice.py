import asyncio
import sys
import os

# Add src to sys.path to allow imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from orchestrator.base import Orchestrator
from workers.builder import Builder
from workers.reviewer import Reviewer
from core.protocol import MessageType

async def main():
    print("--- Starting Agent Swarm Demo: Bob & Alice Pattern ---")

    # 1. Initialize Orchestrator
    # We use a subclass to implement the mediator logic for the demo
    class MediatorOrchestrator(Orchestrator):
        async def handle_message(self, message):
            if message.message_type == MessageType.RESULT:
                # Check if this is a result from a builder that needs review
                # In our demo, we'll assume any result from Bob needs review
                if message.sender_id == "bob_builder":
                    print(f"[Orchestrator] Received result from {message.sender_id}. Sending to Alice for review...")
                    await self.send(alice.agent_id, MessageType.VERIFY_REQUEST, message.payload, metadata={"original_message_id": message.message_id})
                else:
                    await super().handle_message(message)
            
            elif message.message_type == MessageType.VERIFY_RESPONSE:
                # Alice's decision
                status = message.payload.get("status")
                if status == "approved":
                    print(f"[Orchestrator] Verification SUCCESS! Task is complete.")
                else:
                    print(f"[Orchestrator] Verification FAILED! Asking Bob to fix it...")
                    # Send task back to Bob to "fix"
                    # We use the same task_id from the original result
                    task_id = message.payload.get("task_id")
                    await self.send(bob.agent_id, MessageType.TASK, {
                        "task_id": task_id,
                        "description": "Fix the error in the previous task"
                    })
            else:
                await super().handle_message(message)

    orchestrator = MediatorOrchestrator(
        agent_id="orchestrator_id", 
        role="Orchestrator", 
        model="gpt-4", 
        provider="openai"
    )

    # 2. Initialize Bob (Builder)
    bob = Builder(
        agent_id="bob_builder", 
        role="Builder", 
        capability="coding"
    )

    # 3. Initialize Alice (Reviewer)
    alice = Reviewer(
        agent_id="alice_reviewer", 
        role="Reviewer", 
        capability="quality_assurance"
    )

    # Register components
    orchestrator.add_worker(bob)

    # --- Scenario 1: Successful Task ---
    print("\n--- Scenario 1: Successful Task ---")
    task_id_1 = "task_1"
    # Manually track the task in orchestrator so it knows it's pending
    orchestrator.pending_tasks[task_id_1] = {"task_id": task_id_1, "description": "Write a clean python script"}
    await orchestrator.send(bob.agent_id, MessageType.TASK, {
        "task_id": task_id_1,
        "description": "Write a clean python script"
    })

    await asyncio.sleep(2)

    # --- Scenario 2: Failed Task (Requiring Retry) ---
    print("\n--- Scenario 2: Failed Task (Requiring Retry) ---")
    # Monkeypatch Bob to produce an error initially
    original_execute = bob.execute_logic
    async def error_execute(task_desc):
        return "This output contains an error"
    bob.execute_logic = error_execute

    task_id_2 = "task_2"
    orchestrator.pending_tasks[task_id_2] = {"task_id": task_id_2, "description": "Write a script with an error"}
    await orchestrator.send(bob.agent_id, MessageType.TASK, {
        "task_id": task_id_2,
        "description": "Write a script with an error"
    })

    # Allow time for the retry to happen. 
    # After rejection, Bob will be sent a new TASK.
    # We need to make sure Bob's "retry" actually works.
    # For the demo, we'll patch Bob again after the first failure.
    # But since we don't know exactly when it fails, we'll just let it run.
    
    # To make the retry work in the demo, let's make Bob 
    # switch from error_execute to normal_execute after one call.
    
    call_count = 0
    async def smart_error_execute(task_desc):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "This output contains an error"
        return "Fixed and clean output"
    
    bob.execute_logic = smart_error_execute

    await asyncio.sleep(4)
    
    print("\n--- Demo Finished ---")
    await orchestrator.stop()
    await bob.stop()
    await alice.stop()

if __name__ == "__main__":
    asyncio.run(main())
