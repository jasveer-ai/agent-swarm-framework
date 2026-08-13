from typing import Any, Dict, Optional
from core.agent import BaseAgent
from core.protocol import Message, MessageType

class Worker(BaseAgent):
    def __init__(self, agent_id: str, role: str, capability: str):
        super().__init__(agent_id, role)
        self.capability = capability

    async def handle_message(self, message: Message):
        """Handles tasks assigned to the worker."""
        if message.message_type == MessageType.TASK:
            await self._process_task(message)
        elif message.message_type == MessageType.VERIFY_REQUEST:
            await self._process_verification(message)

    async def _process_task(self, message: Message):
        task_desc = message.payload.get("description")
        task_id = message.payload.get("task_id")
        
        if not task_desc:
            await self.send(message.sender_id, MessageType.ERROR, {
                "error": "Missing task description"
            })
            return

        print(f"[{self.agent_id}] Executing task: {task_desc}")
        
        # Placeholder for actual execution logic
        result = await self.execute_logic(task_desc)
        
        await self.send(message.sender_id, MessageType.RESULT, {
            "task_id": task_id,
            "result": result
        }, metadata={"original_message_id": message.message_id})

    async def _process_verification(self, message: Message):
        # Implementation for self-verification if needed
        pass

    async def execute_logic(self, task_desc: str) -> Any:
        """Override this to implement actual work."""
        return f"Completed: {task_desc}"
