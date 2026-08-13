from typing import Dict, Any
import asyncio
from src.core.agent import BaseAgent, AgentRole, AgentStatus, Message

class Builder(BaseAgent):
    def __init__(self, agent_id: str, identity: str, model: str = "gpt-4o"):
        super().__init__(agent_id, identity)
        self.role = AgentRole.WORKER
        self.model = model

    async def handle_message(self, message: Message):
        if message.type == "task":
            print(f"[{self.agent_id}] Received task: {message.payload.get('task_id')}. Starting build...")
            await self.execute_task(message.payload.get("task_id"), message.payload)
        else:
            print(f"[{self.agent_id}] Received unexpected message type: {message.type}")

    async def execute_task(self, task_id: str, task_details: Dict[str, Any]):
        self.status = AgentStatus.EXECUTING
        print(f"[{self.agent_id}] Building: {task_details.get('description', 'unnamed task')}...")
        
        # Simulate work
        await asyncio.sleep(2) 
        
        # Simulate a successful build with some output
        build_result = {
            "status": "success",
            "output": f"Completed build for {task_id}",
            "artifact_path": f"/tmp/build_{task_id}.txt"
        }
        
        # Send report back to the bus
        # Note: In a real implementation, we'd find the sender of the task
        print(f"[{self.agent_id}] Build complete.")
        self.status = AgentStatus.IDLE
        # In the real implementation, the Orchestrator would be listening on the bus
