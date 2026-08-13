from typing import List, Dict, Any, Optional
import asyncio
import uuid
import subprocess
from src.core.agent import BaseAgent, AgentRole, AgentStatus, Message
from src.core.bus import MessageBus

class Orchestrator(BaseAgent):
    def __init__(self, agent_id: str, identity: str, bus: MessageBus, model: str = "opencode-go/deepseek-v4-pro"):
        super().__init__(agent_id, identity, bus=bus)
        self.role = AgentRole.ORCHESTRATOR
        self.bus = bus
        self.model = model
        self.active_tasks: Dict[str, Dict[str, Any]] = {}
        self.task_history: List[Dict[str, Any]] = []

    async def decompose(self, goal: str) -> List[Dict[str, Any]]:
        """
        Uses opencode-go to decompose a high-level goal into atomic tasks.
        Falls back to simple decomposition if opencode is unavailable.
        """
        print(f"[{self.agent_id}] DECOMPOSING via {self.model}: {goal}")
        
        prompt = (
            f"You are an AI orchestrator. Break down this high-level goal into exactly 3-5 "
            f"concrete, actionable sub-tasks that can be executed sequentially. "
            f"Return ONLY a JSON array of objects with fields: id (use short strings like t1, t2), "
            f"description (one sentence), complexity (low/medium/high), goal (the original goal text).\n\n"
            f"Goal: {goal}\n\n"
            f"Output format example:\n"
            f'[{{"id":"t1","description":"Analyze existing codebase structure","complexity":"low","goal":"{goal}"}}]'
        )
        
        try:
            proc = await asyncio.create_subprocess_exec(
                "opencode", "run",
                "--model", self.model,
                "--title", f"Orchestrator: decompose",
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            raw = stdout.decode()
            
            # Try to extract JSON from the output
            import json
            start = raw.find('[')
            end = raw.rfind(']') + 1
            if start >= 0 and end > start:
                tasks = json.loads(raw[start:end])
                print(f"[{self.agent_id}] Decomposed into {len(tasks)} tasks via opencode")
                return tasks
        except Exception as e:
            print(f"[{self.agent_id}] opencode decomposition failed: {e}. Using fallback.")
        
        # Fallback
        return [
            {"id": str(uuid.uuid4())[:8], "description": f"Initial phase: {goal}", "complexity": "medium", "goal": goal},
            {"id": str(uuid.uuid4())[:8], "description": f"Verification phase: {goal}", "complexity": "low", "goal": goal}
        ]

    async def handle_message(self, message: Message):
        if message.type == "task_complete":
            await self._handle_task_completion(message)

    async def dispatch_task(self, task: Dict[str, Any]):
        task_id = task["id"]
        complexity = task.get("complexity", "low")
        if complexity == "high":
            print(f"[{self.agent_id}] Spawning Sub-Orchestrator for {task_id}")
        else:
            await self.bus.publish("new_task", Message(
                id=str(uuid.uuid4()),
                sender_id=self.agent_id,
                receiver_id="workers",
                type="task",
                payload=task
            ))

    async def _handle_task_completion(self, message: Message):
        task_id = message.payload.get("id")
        verdict = message.payload.get("verdict", "UNKNOWN")
        print(f"[{self.agent_id}] Task {task_id} completed ({verdict}).")
        self.task_history.append({"task_id": task_id, "verdict": verdict})
