from typing import Dict, Any
import asyncio
from src.core.agent import BaseAgent, AgentRole, AgentStatus, Message

class Reviewer(BaseAgent):
    def __init__(self, agent_id: str, identity: str, model: str = "gpt-4o"):
        super().__init__(agent_id, identity)
        self.role = AgentRole.WORKER
        self.model = model

    async def handle_message(self, message: Message):
        if message.type == "build_report":
            print(f"[{self.agent_id}] Reviewing build report for {message.payload.get('task_id')}...")
            await self.execute_task(message.payload.get("task_id"), message.payload)
        else:
            print(f"[{self.agent_id}] Received unexpected message type: {message.type}")

    async def execute_task(self, task_id: str, task_details: Dict[str, Any]):
        self.status = AgentStatus.EXECUTING
        print(f"[{self.agent_id}] Reviewing: {task_details.get('description', 'unnamed task')}...")
        
        # Simulate review logic
        await asyncio.sleep(2)
        
        # For the demo, let's say we approve everything unless the task is "fail_me"
        verdict = "APPROVE"
        if task_details.get("description") == "fail_me":
            verdict = "REJECT"
            reason = "The build failed simulated validation."
        else:
            reason = "Code matches specification and passes linting."

        print(f"[{self.agent_id}] Review complete. Verdict: {verdict}")
        self.status = AgentStatus.IDLE
        # Send verdict back
