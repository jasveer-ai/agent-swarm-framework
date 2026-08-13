from typing import Dict, List, Callable, Any, Awaitable
import asyncio
import uuid

class MessageBus:
    def __init__(self):
        self.subscribers: Dict[str, List[Callable[[Any], Awaitable[None]]]] = {}
        self.history: List[Any] = []

    async def subscribe(self, topic: str, callback: Callable[[Any], Awaitable[None]]):
        """Subscribe to a specific topic or a wildcard '*' for a mesh approach."""
        if topic not in self.subscribers:
            self.subscribers[topic] = []
        self.subscribers[topic].append(callback)

    async def publish(self, topic: str, message: Any):
        """Publish a message to a topic, or broadcast to all if topic is '*'"""
        self.history.append({"topic": topic, "message": message})
        
        # Direct topic subscribers
        targets = self.subscribers.get(topic, [])
        
        # Wildcard/Mesh subscribers
        if topic != "*":
            targets.extend(self.subscribers.get("*", []))
            
        if targets:
            tasks = [callback(message) for callback in targets]
            await asyncio.gather(*tasks)

    def get_history(self, limit: int = 100):
        return self.history[-limit:]
