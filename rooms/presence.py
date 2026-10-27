"""Presence участников комнаты.

Хранилище — кэш Django (Redis при `REDIS_URL`, иначе локальный кэш процесса).
Для каждой комнаты держим словарь активных соединений:

    {connection_key: {"name": ..., "participant_id": ..., "count": N, "ts": ...}}

У одного участника может быть несколько вкладок, поэтому считаем соединения
(`count`) и считаем его онлайн, пока count > 0. Запись живёт с TTL и продлевается
при `ping`/activity (heartbeat появится на A11).
"""

import json
from dataclasses import dataclass
from time import time

from django.core.cache import cache

# TTL записи; heartbeat будет продлевать её чаще, но даже без него presence
# сам «очистится» после обрыва соединения.
PRESENCE_TTL = 60


@dataclass(frozen=True)
class PresenceEntry:
    key: str
    name: str
    participant_id: int | None
    guest: bool
    count: int

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "participant_id": self.participant_id,
            "guest": self.guest,
            "count": self.count,
        }


def _cache_key(room_id: int) -> str:
    return f"room-presence:{room_id}"


def _load(room_id: int) -> dict[str, dict]:
    raw = cache.get(_cache_key(room_id))
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _store(room_id: int, data: dict[str, dict]) -> None:
    if data:
        cache.set(_cache_key(room_id), json.dumps(data), timeout=PRESENCE_TTL)
    else:
        cache.delete(_cache_key(room_id))


def add_connection(
    room_id: int,
    *,
    key: str,
    name: str,
    participant_id: int | None = None,
    guest: bool = True,
) -> list[PresenceEntry]:
    """Зарегистрировать соединение и вернуть текущий список участников."""
    data = _load(room_id)
    entry = data.get(key) or {
        "name": name,
        "participant_id": participant_id,
        "guest": guest,
        "count": 0,
    }
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["name"] = name
    entry["ts"] = time()
    data[key] = entry
    _store(room_id, data)
    return _entries(data)


def remove_connection(room_id: int, key: str) -> list[PresenceEntry]:
    """Убрать соединение и вернуть оставшихся участников."""
    data = _load(room_id)
    entry = data.get(key)
    if entry is not None:
        count = int(entry.get("count", 0)) - 1
        if count > 0:
            entry["count"] = count
        else:
            data.pop(key, None)
        _store(room_id, data)
    return _entries(data)


def touch(room_id: int, key: str) -> list[PresenceEntry]:
    """Продлить TTL записи (используется heartbeat на A11)."""
    data = _load(room_id)
    entry = data.get(key)
    if entry is not None:
        entry["ts"] = time()
        _store(room_id, data)
    return _entries(data)


def list_participants(room_id: int) -> list[PresenceEntry]:
    return _entries(_load(room_id))


def clear(room_id: int) -> None:
    cache.delete(_cache_key(room_id))


def _entries(data: dict[str, dict]) -> list[PresenceEntry]:
    entries = [
        PresenceEntry(
            key=key,
            name=value.get("name", ""),
            participant_id=value.get("participant_id"),
            guest=bool(value.get("guest", True)),
            count=int(value.get("count", 0)),
        )
        for key, value in data.items()
    ]
    entries.sort(key=lambda item: item.name)
    return entries
