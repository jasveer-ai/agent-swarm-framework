import asyncio
import uuid
from typing import Any, Dict, List, Optional
from core.agent import BaseAgent
from core.protocol import Message, MessageType
from workers.base import Worker

class Orchestrator(BaseAgent):
    def __init__(self, agent_id: str, role: str, model: str, provider: str):
        super().__init__(agent_id, role)
        self.model = model
        self.provider = provider
        self.pending_tasks: Dict[str, Any] = {}
        self.workers: List[Worker] = []

    def add_worker(self, worker: Worker):
        self.workers.append(worker)

    async def handle_message(self, message: Message):
        if message.message_type == MessageType.RESULT:
            await self._handle_result(message)
        elif message.message_type == MessageType.VERIFY_RESPONSE:
            await self._handle_verification_response(message)
        else:
            # For now, just log other messages
            pass

    async def _handle_result(self, message: Message):
        task_id = message.payload.get("task_id")
        result = message.payload.get("result")
        
        print(f"DEBUG: task_id={task_id}, pending_tasks={list(self.pending_tasks.keys())}")
        
        if task_id in self.pending_tasks:
            print(f"[{self.agent_id}] Task {task_id} completed with result: {result}")
            del self.pending_tasks[task_id]
        else:
            print(f"[{self.agent_id}] Received unexpected result for task {task_id}")

    async def _handle_verification_response(self, message: Message):
        # Handle verification result
        pass

    async def plan_and_execute(self, goal: str):
        """The main entry point for an orchestrator."""
        print(f"[{self.agent_id}] Planning for goal: {goal}")
        
        # 1. Decompose (Mocking LLM decomposition)
        tasks = await self.decompose(goal)
        
        # 2. Dispatch
        await self.dispatch(tasks)

    async def decompose(self, goal: str) -> List[Dict[str, Any]]:
        """Breaks a high-level goal into discrete tasks."""
        # Mock decomposition
        print(f"[{self.agent_id}] Decomposing goal...")
        return [
            {"task_id": str(uuid.uuid4()), "description": f"Step 1 of {goal}"},
            {"task_id": str(uuid.uuid4()), "description": f"Step 2 of {goal}"},
        ]

    async def dispatch(self, tasks: List[Dict[str, Any]]):
        """Spawns workers for tasks."""
        for task_data in tasks:
            task_id = task_data["task_id"]
            desc = task_data["description"]
            
            self.pending_tasks[task_id] = task_data
            
            # Simple round-robin or availability-based dispatch
            # For now, just pick the first worker
            if not self.workers:
                print(f"[{self.agent_id}] No workers available to dispatch tasks!")
                return

            target_worker = self.workers[0] # Mocked
            
            print(f"[{self.agent_id}] Dispatching task {task_id} to {target_worker.agent_id}")
            await self.send(target_worker.agent_id, MessageType.TASK, {
                "task_id": task_id,
                "description": desc
            })
