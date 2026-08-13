from enum import Enum
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
import uuid
import time
import json

class MessageType(Enum):
    TASK = "task"
    RESULT = "result"
    SUB_TASK = "sub_task"
    VERIFY_REQUEST = "verify_request"
    VERIFY_RESPONSE = "verify_response"
    ERROR = "error"
    SIGNAL = "signal"
    PROMPT = "prompt"

@dataclass
class Message:
    sender_id: str
    receiver_id: str
    message_type: MessageType
    payload: Dict[str, Any]
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "message_type": self.message_type.value,
            "payload": self.payload,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        })

    @classmethod
    def from_json(cls, json_str: str) -> 'Message':
        data = json.loads(json_str)
        return cls(
            sender_id=data["sender_id"],
            receiver_id=data["receiver_id"],
            message_type=MessageType(data["message_type"]),
            payload=data["payload"],
            message_id=data["message_id"],
            timestamp=data["timestamp"],
            metadata=data["metadata"]
        )

@dataclass
class Task:
    task_id: str
    description: str
    status: str = "pending"
    assigned_to: Optional[str] = None
    result: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "description": self.description,
            "status": self.status,
            "assigned_to": self.assigned_to,
            "result": self.result,
            "metadata": self.metadata
        }
