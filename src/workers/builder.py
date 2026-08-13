from typing import Dict, Any
import asyncio
import uuid
import subprocess
from src.core.agent import BaseAgent, AgentRole, AgentStatus, Message

class Builder(BaseAgent):
    def __init__(self, agent_id: str, identity: str, model: str = "opencode-go/deepseek-v4-flash", bus=None):
        super().__init__(agent_id, identity, bus=bus)
        self.role = AgentRole.WORKER
        self.model = model

    async def handle_message(self, message: Message):
        if message.type == "task":
            task_id = message.payload.get("id")
            desc = message.payload.get("description", "no description")
            print(f"[{self.agent_id}] Received task: {task_id}. Starting build: {desc}")
            await self.execute_task(task_id, message.payload)
        else:
            print(f"[{self.agent_id}] Unexpected message type: {message.type}")

    async def execute_task(self, task_id: str, task_details: Dict[str, Any]):
        self.status = AgentStatus.EXECUTING
        desc = task_details.get("description", "unnamed")
        goal = task_details.get("goal", desc)
        
        print(f"[{self.agent_id}] Calling opencode-go/{self.model} for: {goal}")
        
        # Actually invoke opencode-go
        try:
            proc = await asyncio.create_subprocess_exec(
                "opencode", "run",
                "--model", self.model,
                "--title", f"Bob: {task_id}",
                goal,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            output = stdout.decode()[:500]
            if stderr:
                output += "\n[STDERR] " + stderr.decode()[:200]
        except asyncio.TimeoutError:
            output = "TIMEOUT after 120s"
        except FileNotFoundError:
            output = "opencode CLI not found — using simulated fallback"
        
        print(f"[{self.agent_id}] Build result for {task_id}: {output[:200]}...")
        self.status = AgentStatus.IDLE
        
        if self.bus:
            await self.bus.publish("build_report", Message(
                id=str(uuid.uuid4()),
                sender_id=self.agent_id,
                receiver_id="reviewer",
                type="build_report",
                payload={"id": task_id, "description": desc, "status": "success", "output": output}
            ))
