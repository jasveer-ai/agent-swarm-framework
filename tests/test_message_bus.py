import unittest

from agent_swarm.core.bus import MessageBus
from agent_swarm.core.protocol import Message


class MessageBusTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_records_delivery_outcomes_without_persisting_error_text(
        self,
    ):
        bus = MessageBus()

        async def delivered(_message):
            return None

        async def failed(_message):
            raise RuntimeError("token=must-not-be-persisted")

        await bus.subscribe("topic", delivered)
        await bus.subscribe("topic", failed)
        message = Message(
            sender_id="one",
            receiver_id="two",
            type="fixture",
            payload={},
            run_id="run-1",
        )

        with self.assertRaises(RuntimeError):
            await bus.publish("topic", message)

        event = bus.get_history(limit=None)[0]
        self.assertEqual(
            [delivery["status"] for delivery in event["deliveries"]],
            ["delivered", "failed"],
        )
        self.assertEqual(event["deliveries"][1]["error_type"], "RuntimeError")
        self.assertNotIn("must-not-be-persisted", str(event))
        self.assertEqual(message.correlation_id, "run-1")

    async def test_agent_conversations_keep_chronology_for_each_participant(self):
        bus = MessageBus()
        await bus.publish(
            "request",
            Message("one", "two", "request", {}, run_id="run"),
        )
        await bus.publish(
            "response",
            Message("two", "one", "response", {}, run_id="run"),
        )

        conversations = bus.agent_conversations()
        self.assertEqual([event["sequence"] for event in conversations["one"]], [1, 2])
        self.assertEqual([event["sequence"] for event in conversations["two"]], [1, 2])


if __name__ == "__main__":
    unittest.main()
