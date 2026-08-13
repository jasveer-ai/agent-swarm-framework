from typing import Any, Dict, Optional
from workers.base import Worker
from core.protocol import Message, MessageType

class Builder(Worker):
    """
    A specialized worker that acts as a Builder (Bob) in the Bob/Alice pattern.
    """
    def __init__(self, agent_id: str, role: str, capability: str):
        super().__init__(agent_id, role, capability)
        self.pending_verifications: Dict[str, Dict[str, Any]] = {}

    async def handle_message(self, message: Message):
        if message.message_type == MessageType.VERIFY_RESPONSE:
            await self._handle_verification_response(message)
        else:
            await super().handle_message(message)

    async def _handle_verification_response(self, message: Message):
        task_id = message.payload.get("task_id")
        status = message.payload.get("status")
        
        if status == "approved":
            print(f"[{self.agent_id}] Task {task_id} was APPROVED by reviewer.")
        else:
            print(f"[{self.agent_id}] Task {task_id} was REJECTED by reviewer. Retrying...")
            if task_id:
                await self._retry_task(task_id)

    async def _retry_task(self, task_id: str):
        # Mock retry
        print(f"[{self.agent_id}] Retrying task {task_id} with corrected content...")
        await self.send("orchestrator_id", MessageType.RESULT, {
            "task_id": task_id,
            "result": "Corrected content that passes verification"
        })
        # Note: In a real system, this would be more complex.
        # For this demo, we'll just trigger another result.
        # But wait, the orchestrator needs to know this is a result of a retry.
        # For simplicity, let's just assume the orchestration loop handles it.
        pass
