from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class MessageType(str, Enum):
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
    """Canonical, serializable message exchanged by agents on the bus."""

    sender_id: str
    receiver_id: str
    type: str
    payload: Dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    run_id: Optional[str] = None
    task_id: Optional[str] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.correlation_id is None and self.run_id is not None:
            self.correlation_id = self.run_id

    @property
    def message_id(self) -> str:
        return self.id

    @property
    def message_type(self) -> MessageType | str:
        try:
            return MessageType(self.type)
        except ValueError:
            return self.type

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> "Message":
        return cls(**json.loads(json_str))


@dataclass
class Task:
    task_id: str
    description: str
    status: str = "pending"
    assigned_to: Optional[str] = None
    result: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
