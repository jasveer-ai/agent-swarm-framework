from typing import Any, Dict, Optional
from workers.base import Worker
from core.protocol import Message, MessageType

class Reviewer(Worker):
    """
    A specialized worker that acts as a Reviewer (Alice) in the Bob/Alice pattern.
    """
    def __init__(self, agent_id: str, role: str, capability: str):
        super().__init__(agent_id, role, capability)

    async def handle_message(self, message: Message):
        if message.message_type == MessageType.RESULT:
            # If the reviewer gets a direct result, it might be for its own task
            await self._review_result(message, message.payload)
        elif message.message_type == MessageType.VERIFY_REQUEST:
            await self._process_verification(message)
        else:
            await super().handle_message(message)

    async def _process_verification(self, message: Message):
        """Handles a verification request."""
        print(f"[{self.agent_id}] Processing verification request...")
        
        # The orchestrator sends the result in the payload
        result_payload = message.payload
        await self._review_result(message, result_payload)

    async def _review_result(self, message: Message, result_payload: Dict[str, Any]):
        """Reviews the result provided in the payload."""
        result = result_payload.get("result")
        task_id = result_payload.get("task_id")
        
        print(f"[{self.agent_id}] Reviewing result for task {task_id}: {result}")
        
        # Logic for verification
        is_valid = self._verify_content(result)
        
        if is_valid:
            print(f"[{self.agent_id}] Verification SUCCESS.")
            await self.send(message.sender_id, MessageType.VERIFY_RESPONSE, {
                "task_id": task_id,
                "status": "approved",
                "details": "Content matches requirements."
            }, metadata={"original_message_id": message.message_id})
        else:
            print(f"[{self.agent_id}] Verification FAILED.")
            await self.send(message.sender_id, MessageType.VERIFY_RESPONSE, {
                "task_id": task_id,
                "status": "rejected",
                "details": "Content does not meet quality standards."
            }, metadata={"original_message_id": message.message_id})

    def _verify_content(self, content: Any) -> bool:
        """
        The actual verification logic. 
        In a real implementation, this would use an LLM to judge the content.
        """
        # Mock verification: if content contains "error", reject it.
        if isinstance(content, str) and "error" in content.lower():
            return False
        return True
