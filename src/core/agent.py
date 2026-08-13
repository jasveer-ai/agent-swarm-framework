from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING
import asyncio

if TYPE_CHECKING:
    from src.core.bus import MessageBus

class AgentRole(Enum):
    ORCHESTRATOR = "orchestrator"
    SUB_ORCHESTRATOR = "sub_orchestrator"
    WORKER = "worker"
    ADMIN = "admin"

class AgentStatus(Enum):
    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    ERROR = "error"

@dataclass
class Capability:
    name: str
    description: str
    args_schema: Optional[Dict[str, Any]] = None

@dataclass
class Message:
    id: str
    sender_id: str
    receiver_id: str
    type: str
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)

class BaseAgent:
    def __init__(self, agent_id: str, identity: str, bus: Optional["MessageBus"] = None):
        self.agent_id = agent_id
        self.identity = identity
        self.role = AgentRole.WORKER
        self.status = AgentStatus.IDLE
        self.capabilities: Set[Capability] = set()
        self.context: Dict[str, Any] = {}
        self.bus = bus  # <-- THE FIX: Every agent can now speak on the mesh
        
    async def set_role(self, new_role: AgentRole):
        self.role = new_role
        
    def add_capability(self, capability: Capability):
        self.capabilities.add(capability)
        
    async def handle_message(self, message: Message):
        raise NotImplementedError("Agents must implement handle_message")

    async def execute_task(self, task_id: str, task_details: Dict[str, Any]):
        raise NotImplementedError("Agents must implement execute_task")
