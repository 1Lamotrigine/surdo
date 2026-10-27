"""E3: consumer комнаты отдаёт asr_text и utterance клиенту."""

import asyncio

from rooms.consumers import RoomConsumer


def test_asr_text_and_utterance_handlers_send_json():
    sent: list[dict] = []

    async def scenario() -> None:
        consumer = RoomConsumer()

        async def send_json(payload: dict) -> None:
            sent.append(payload)

        consumer.send_json = send_json  # type: ignore[method-assign]
        await consumer.asr_text({"type": "asr.text", "text": "Учебник"})
        await consumer.utterance(
            {
                "type": "utterance",
                "utterance": {"id": 1, "seq": 1, "text": "Учебник", "clips": []},
            }
        )

    asyncio.run(scenario())

    assert sent == [
        {"type": "asr_text", "text": "Учебник"},
        {
            "type": "utterance",
            "utterance": {"id": 1, "seq": 1, "text": "Учебник", "clips": []},
        },
    ]
