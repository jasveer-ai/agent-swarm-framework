from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Dict, List

from agent_swarm.core.protocol import Message


@dataclass
class BusEvent:
    sequence: int
    timestamp: float
    topic: str
    message: Dict[str, Any]
    deliveries: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MessageBus:
    """In-process message mesh with an ordered, JSON-safe audit history."""

    def __init__(self) -> None:
        self.subscribers: Dict[str, List[Callable[[Message], Awaitable[None]]]] = {}
        self.history: List[BusEvent] = []
        self._sequence = 0
        self._lock = asyncio.Lock()

    async def subscribe(
        self, topic: str, callback: Callable[[Message], Awaitable[None]]
    ) -> None:
        self.subscribers.setdefault(topic, []).append(callback)

    async def publish(self, topic: str, message: Message) -> None:
        targets = list(self.subscribers.get(topic, []))
        if topic != "*":
            targets.extend(self.subscribers.get("*", []))
        deliveries = [
            {
                "recipient": getattr(callback, "__qualname__", repr(callback)),
                "status": "pending",
            }
            for callback in targets
        ]
        async with self._lock:
            self._sequence += 1
            event = BusEvent(
                sequence=self._sequence,
                timestamp=time.time(),
                topic=topic,
                message=message.to_dict(),
                deliveries=deliveries,
            )
            self.history.append(event)

        if targets:
            results = await asyncio.gather(
                *(callback(message) for callback in targets),
                return_exceptions=True,
            )
            failures = []
            async with self._lock:
                for delivery, result in zip(event.deliveries, results):
                    if isinstance(result, BaseException):
                        delivery["status"] = "failed"
                        delivery["error_type"] = type(result).__name__
                        failures.append(result)
                    else:
                        delivery["status"] = "delivered"
            if failures:
                raise failures[0]

    def get_history(self, limit: int | None = 100) -> List[Dict[str, Any]]:
        events = self.history if limit is None else self.history[-limit:]
        return [event.to_dict() for event in events]

    def conversations(self) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for event in self.history:
            message = event.message
            key = f"{message['sender_id']}->{message['receiver_id']}"
            grouped.setdefault(key, []).append(event.to_dict())
        return grouped

    def agent_conversations(self) -> Dict[str, List[Dict[str, Any]]]:
        """Project the canonical chronology once for every participating agent."""

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for event in self.history:
            participants = {
                event.message["sender_id"],
                event.message["receiver_id"],
            }
            for participant in participants:
                grouped.setdefault(participant, []).append(event.to_dict())
        return grouped
