from typing import Any, Dict, List, Optional
from core.agent import BaseAgent
from core.protocol import Message, MessageType
from workers.base import Worker

class SubOrchestrator(BaseAgent):
    def __init__(self, agent_id: str, role: str, parent_orchestrator_id: str):
        super().__init__(agent_id, role)
        self.parent_id = parent_orchestrator_id
        self.workers: List[Worker] = []
        self.tasks: Dict[str, Any] = {}

    def add_worker(self, worker: Worker):
        self.workers.append(worker)

    async def handle_message(self, message: Message):
        if message.message_type == MessageType.TASK:
            await self._handle_task(message)
        elif message.message_type == MessageType.RESULT:
            await self._handle_result(message)

    async def _handle_task(self, message: Message):
        """Sub-orchestrator receives a task and decomposes it further."""
        print(f"[{self.agent_id}] Received task from {message.sender_id}. Decomposing...")
        
        # For the prototype, we just pass the task to one of our workers
        if not self.workers:
            await self.send(message.sender_id, MessageType.ERROR, {
                "error": "No workers available in sub-orchestrator"
            })
            return

        target_worker = self.workers[0]
        await self.send(target_worker.agent_id, MessageType.TASK, message.payload, metadata={"original_message_id": message.message_id})

    async def _handle_result(self, message: Message):
        """Sub-orchestrator receives a result from a worker and reports to parent."""
        print(f"[{self.agent_id}] Received result from {message.sender_id}. Reporting to parent...")
        await self.send(self.parent_id, MessageType.RESULT, message.payload, metadata={"original_message_id": message.message_id})
