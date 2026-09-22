"""Bus d'evenements asyncio : tout le systeme communique par ici.

Un seul point de passage pour l'audio, le cerveau, la memoire et le HUD.
C'est ce qui permet de brancher le HUD sans qu'aucune brique ne le connaisse.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable


@dataclass(slots=True)
class Event:
    topic: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def as_json(self) -> dict[str, Any]:
        return {"topic": self.topic, "ts": self.ts, **self.data}


Handler = Callable[[Event], Awaitable[None] | None]


class Bus:
    """Pub/sub en memoire, avec journal circulaire pour rejouer l'etat au HUD."""

    def __init__(self, history: int = 200) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._queues: list[asyncio.Queue[Event]] = []
        self._log: deque[Event] = deque(maxlen=history)

    def on(self, *topics: str) -> Callable[[Handler], Handler]:
        def deco(fn: Handler) -> Handler:
            for t in topics:
                self._subs[t].append(fn)
            return fn

        return deco

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    async def emit(self, topic: str, **data: Any) -> Event:
        ev = Event(topic, data)
        self._log.append(ev)

        for pattern in (topic, topic.split(".", 1)[0] + ".*", "*"):
            for fn in tuple(self._subs.get(pattern, ())):
                try:
                    res = fn(ev)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as exc:  # une brique qui tombe ne tue pas le bus
                    print(f"[bus] handler {pattern} a echoue: {exc!r}")

        for q in tuple(self._queues):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass
        return ev

    def stream(self, maxsize: int = 512) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._queues.append(q)
        return q

    def drop(self, q: asyncio.Queue[Event]) -> None:
        if q in self._queues:
            self._queues.remove(q)

    def replay(self) -> Iterable[Event]:
        return tuple(self._log)


BUS = Bus()
