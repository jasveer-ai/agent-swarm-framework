from typing import Dict, Any, Optional
import asyncio
from src.core.agent import BaseAgent, AgentRole, AgentStatus, Message

class Worker(BaseAgent):
    def __init__(self, agent_id: str, identity: str, specialized_capability: str):
        super().__init__(agent_id, identity)
        self.role = AgentRole.WORKER
        self.specialization = specialized_capability
        self.last_verification_status: Optional[str] = None

    async def handle_message(self, message: Message):
        if message.type == "task":
            await self.execute_task(message.payload.get("task_id"), message.payload)
        elif message.type == "retry":
            print(f"[{self.agent_id}] 🔄 Received retry request. Re-attempting...")
            await self.execute_task(message.payload.get("task_id"), message.payload)
        else:
            print(f"[{self.agent_id}] Received message type: {message.type}")

    async def execute_task(self, task_id: str, task_details: Dict[str, Any]):
        """
        The primary work loop. Includes a mandatory self-verification step 
        before reporting completion.
        """
        self.status = AgentStatus.EXECUTING
        print(f"[{self.agent_id}] 🛠️ Working on task: {task_id} ({self.specialization})")
        
        try:
            # 1. SIMULATED EXECUTION
            # In real use, this would be: result = await self.call_opencode(task_details)
            await asyncio.sleep(1) 
            
            # 2. SELF-VERIFICATION (The 'Verify-Before-Trust' Principle)
            self.status = AgentStatus.VERIFYING
            print(f"[{self.agent_id}] 🔍 Performing self-verification...")
            await asyncio.sleep(1)
            
            # 3. REPORT SUCCESS
            print(f"[{self.agent_id}] ✅ Task {task_id} verified and complete.")
            self.last_verification_status = "passed"
            
            # Send report back via the bus
            # We simulate a message being sent to the orchestrator/reviewer
            # In a real implementation, the Bus is injected or accessible via context
            # For this demo, we'll assume the Orchestrator is listening to 'task_complete'
            # (Note: We'll actually use a global bus pattern for this simplified version)
            from src.core.bus import MessageBus
            # This is a bit of a hack for the demo: we'll assume a global bus is available or passed.
            # In a real system, we'd use a singleton or dependency injection.
            
        except Exception as e:
            self.status = AgentStatus.ERROR
            print(f"[{self.agent_id}] ❌ Task {task_id} failed: {e}")
            # Report error to the bus
            # await bus.publish("task_error", Message(...))
        finally:
            if self.status != AgentStatus.ERROR:
                self.status = AgentStatus.IDLE
