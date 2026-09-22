"""Serveur WebSocket local : la fenetre du HUD sur le systeme.

Il ne fait que deux choses : rediffuser le bus d'evenements a tout client
connecte, et accepter quelques commandes. Aucune brique ne connait le HUD,
c'est le bus qui les decouple -- on peut le fermer sans rien casser.
Ecoute sur 127.0.0.1 uniquement : rien n'est expose au reseau.
"""
from __future__ import annotations

import asyncio
import json

import websockets

from .bus import BUS
from .config import CFG


async def serve(jarvis) -> None:
    async def handler(ws) -> None:
        await BUS.emit("hud.connected")
        queue = BUS.stream()
        await ws.send(json.dumps({"topic": "hud.snapshot", **jarvis.snapshot()}))
        for ev in BUS.replay():
            await ws.send(json.dumps(ev.as_json(), default=str))

        async def pump() -> None:
            while True:
                ev = await queue.get()
                await ws.send(json.dumps(ev.as_json(), default=str))

        pump_task = asyncio.create_task(pump())
        try:
            async for raw in ws:
                await _command(jarvis, ws, raw)
        except websockets.ConnectionClosed:
            pass
        finally:
            pump_task.cancel()
            BUS.drop(queue)
            await BUS.emit("hud.disconnected")

    async with websockets.serve(handler, CFG.host, CFG.port, ping_interval=20):
        await BUS.emit("hud.listening", url=f"ws://{CFG.host}:{CFG.port}")
        await asyncio.Future()


async def _command(jarvis, ws, raw: str) -> None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return
    cmd = msg.get("cmd")

    if cmd == "say":                      # message texte depuis le HUD
        text = (msg.get("text") or "").strip()
        if text:
            asyncio.create_task(jarvis.handle(text, session="hud", speak=msg.get("speak", True)))
    elif cmd == "interrupt":
        await jarvis.speaker.interrupt()
    elif cmd == "listen":
        jarvis.gate.open()
        await BUS.emit("gate.opened")
    elif cmd == "sleep":
        jarvis.gate.close()
        await BUS.emit("gate.closed")
    elif cmd == "consolidate":
        from .memory.consolidate import consolidate

        asyncio.create_task(consolidate(jarvis.memory, jarvis.brain))
    elif cmd == "recall":
        hits = jarvis.memory.recall(msg.get("query", ""), k=12)
        await ws.send(json.dumps({"topic": "memory.recall", "hits": [h.as_json() for h in hits]}))
    elif cmd == "timeline":
        await ws.send(json.dumps({"topic": "memory.timeline",
                                  "items": jarvis.memory.timeline(int(msg.get("limit", 40)))}))
    elif cmd == "snapshot":
        await ws.send(json.dumps({"topic": "hud.snapshot", **jarvis.snapshot()}))
