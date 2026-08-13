import asyncio
from typing import Dict, List, Callable, Any, Union, Coroutine
from .protocol import Message

# A callback can be a regular function or an async function
AsyncCallback = Callable[[Message], Coroutine[Any, Any, None]]
SyncCallback = Callable[[Message], None]
Callback = Union[SyncCallback, AsyncCallback]

class MessageBus:
    """
    A simple in-memory message bus for inter-agent communication.
    """
    def __init__(self):
        self.subscribers: Dict[str, List[Callback]] = {}

    def subscribe(self, agent_id: str, callback: Callback):
        if agent_id not in self.subscribers:
            self.subscribers[agent_id] = []
        self.subscribers[agent_id].append(callback)

    def publish(self, message: Message):
        """
        Publishes a message. Note: This is a synchronous call that 
        schedules async tasks for subscribers.
        """
        # Route to specific receiver
        if message.receiver_id in self.subscribers:
            for callback in self.subscribers[message.receiver_id]:
                self._dispatch(callback, message)
        
        # Also route to broadcast
        if message.receiver_id == "broadcast":
            for agent_id, callbacks in self.subscribers.items():
                if agent_id != message.sender_id:
                    for callback in callbacks:
                        self._dispatch(callback, message)

    def _dispatch(self, callback: Callback, message: Message):
        import inspect
        if inspect.iscoroutinefunction(callback):
            # Schedule the coroutine on the current event loop
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(callback(message))
            except RuntimeError:
                # No running loop, this is tricky in a pure sync environment
                # but in our framework, agents run in a loop.
                pass
        else:
            callback(message)

# Global bus instance for the framework
bus = MessageBus()
