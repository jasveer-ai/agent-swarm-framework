from typing import Dict, Any
from src.core.agent import BaseAgent, AgentRole, AgentStatus, Message

class Worker(BaseAgent):
    def __init__(self, agent_id: str, identity: str, specialized_capability: str):
        super().__init__(agent_id, identity)
        self.role = AgentRole.WORKER
        self.specialization = specialized_capability

    async def execute_task(self, task_id: str, task_details: Dict[str, Any]):
        """The primary work loop for a worker agent."""
        print(f"[{self.agent_id}] Worker starting task: {task_id} ({self.specialization})")
        self.status = AgentStatus.EXECUTING
        
        try:
            # Logic for task execution goes here
            # This is where the LLM call or tool usage happens
            pass
        except Exception as e:
            self.status = AgentStatus.ERROR
            print(f"[{self.agent_id}] Task {task_id} failed: {e}")
        finally:
            if self.status != AgentStatus.ERROR:
                self.status = AgentStatus.IDLE
