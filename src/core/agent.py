import asyncio
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
from .protocol import Message, MessageType
from .bus import bus

class BaseAgent(ABC):
    def __init__(self, agent_id: str, role: str):
        self.agent_id = agent_id
        self.role = role
        self.bus = bus
        self.bus.subscribe(self.agent_id, self._on_message_received)
        self.message_history: List[Message] = []
        self.is_running = True

    async def _on_message_received(self, message: Message):
        """Internal handler for messages from the bus."""
        print(f"DEBUG: Agent {self.agent_id} received {message.message_type.value} from {message.sender_id}")
        self.message_history.append(message)
        try:
            await self.handle_message(message)
        except Exception as e:
            print(f"Error in agent {self.agent_id} handling message: {e}")
            # Optionally send an error message to the sender
            if message.sender_id != "broadcast":
                await self.send(message.sender_id, MessageType.ERROR, {
                    "error": str(e),
                    "original_message_id": message.message_id
                })

    @abstractmethod
    async def handle_message(self, message: Message):
        """Process incoming messages. Must be implemented by subclasses."""
        pass

    async def send(self, receiver_id: str, message_type: MessageType, payload: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None):
        """Sends a message via the bus."""
        message = Message(
            sender_id=self.agent_id,
            receiver_id=receiver_id,
            message_type=message_type,
            payload=payload,
            metadata=metadata or {}
        )
        self.bus.publish(message)
        return message

    async def broadcast(self, message_type: MessageType, payload: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None):
        """Broadcasts a message to all agents."""
        return await self.send("broadcast", message_type, payload, metadata)

    async def stop(self):
        """Gracefully stops the agent."""
        self.is_running = False
        print(f"Agent {self.agent_id} ({self.role}) stopping...")
