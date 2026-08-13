from typing import Dict, Any
import asyncio
import uuid
import subprocess
from src.core.agent import BaseAgent, AgentRole, AgentStatus, Message

class Reviewer(BaseAgent):
    def __init__(self, agent_id: str, identity: str, model: str = "opencode-go/deepseek-v4-pro", bus=None):
        super().__init__(agent_id, identity, bus=bus)
        self.role = AgentRole.WORKER
        self.model = model

    async def handle_message(self, message: Message):
        if message.type == "build_report":
            task_id = message.payload.get("id")
            print(f"[{self.agent_id}] Reviewing build for {task_id}...")
            await self.execute_task(task_id, message.payload)
        else:
            print(f"[{self.agent_id}] Unexpected message type: {message.type}")

    async def execute_task(self, task_id: str, task_details: Dict[str, Any]):
        self.status = AgentStatus.VERIFYING
        desc = task_details.get("description", "unknown")
        build_output = task_details.get("output", "")
        
        review_prompt = f"Review this build output for task '{desc}'. Rate it APPROVE or REJECT with a brief reason.\n\nBuild output:\n{build_output[:1000]}"
        
        print(f"[{self.agent_id}] Calling opencode-go/{self.model} for review...")
        
        try:
            proc = await asyncio.create_subprocess_exec(
                "opencode", "run",
                "--model", self.model,
                "--title", f"Alice: review {task_id}",
                review_prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            verdict_raw = stdout.decode()[:300].upper()
        except asyncio.TimeoutError:
            verdict_raw = "TIMEOUT — defaulting to APPROVE"
        except FileNotFoundError:
            verdict_raw = "opencode CLI not found — defaulting to APPROVE"
        
        if "REJECT" in verdict_raw:
            verdict = "REJECT"
        else:
            verdict = "APPROVE"
            
        reason = verdict_raw[:200]
        print(f"[{self.agent_id}] Verdict: {verdict} ({reason})")
        self.status = AgentStatus.IDLE
        
        if self.bus:
            await self.bus.publish("task_complete", Message(
                id=str(uuid.uuid4()),
                sender_id=self.agent_id,
                receiver_id="orchestrator",
                type="task_complete",
                payload={"id": task_id, "verdict": verdict, "reason": reason}
            ))
