"""L'orchestrateur : c'est lui, le "systeme" de Jarvis.

Il ne contient presque aucune intelligence -- il cable des briques et tient
les regles temps reel :
  - le micro se coupe pendant que Jarvis parle (anti-echo) ;
  - une parole pendant la reponse l'interrompt (barge-in) ;
  - la memoire se consolide en tache de fond, jamais pendant un tour de parole.
"""
from __future__ import annotations

import asyncio
import contextlib
import time

from .audio import stt, tts
from .audio.capture import Microphone
from .audio.vad import VAD
from .audio.wake import Gate, try_load as load_wake, available as wake_available
from .brain import Brain
from .bus import BUS
from .config import CFG
from .memory import Memory
from .memory.consolidate import consolidate
from .tools import REGISTRY
from .tools import builtin


class Jarvis:
    def __init__(self) -> None:
        self.memory = Memory()
        builtin.bind(self.memory)
        self.brain = Brain(self.memory, REGISTRY)
        self.mic = Microphone()
        self.vad = VAD()
        self.gate = Gate()
        self.speaker = tts.Speaker(mic=self.mic)
        self.busy = False
        self._tasks: list[asyncio.Task] = []
        self.started = time.time()

    # ------------------------------------------------------------------ cycle
    async def boot(self, with_audio: bool = True) -> dict:
        await BUS.emit("jarvis.booting")
        state = {"memory": self.memory.stats(), "tools": REGISTRY.names()}

        state["brain"] = await self.brain.boot()
        if with_audio:
            state["tts"] = await tts.init()
            self.speaker.start()
            state["wake"] = load_wake()
            state["stt"] = await stt.warmup()
            state["mic"] = await self.mic.start()

        await BUS.emit("jarvis.ready", **state)
        return state

    def run_background(self) -> None:
        self._tasks.append(asyncio.create_task(self._listen()))
        self._tasks.append(asyncio.create_task(self._sleep_cycle()))

    async def shutdown(self) -> None:
        for t in self._tasks:
            t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self.mic.stop()
        await BUS.emit("jarvis.stopped")

    # ----------------------------------------------------------------- ecoute
    async def _listen(self) -> None:
        async for frame in self.mic.frames():
            if self.speaker.speaking and self.vad.energy(frame) > 0.05:
                await self.speaker.interrupt()      # barge-in : on se tait
                self.vad.reset()
                continue

            utterance = self.vad.feed(frame)
            if utterance is None:
                continue

            text = await stt.transcribe(utterance)
            if not text or len(text) < 2:
                continue

            answer, cleaned = self.gate.accept(text)
            if not answer:
                await BUS.emit("speech.ignored", text=text)
                continue

            await self.handle(cleaned)

    # ------------------------------------------------------------------ tour
    async def handle(self, text: str, session: str = "voice", speak: bool = True) -> str:
        """Un tour de parole complet. Renvoie la reponse assemblee."""
        if self.busy:
            return ""
        self.busy = True
        t0 = time.perf_counter()
        first_ms: float | None = None
        pieces: list[str] = []

        await BUS.emit("turn.start", text=text)
        try:
            async for sentence in self.brain.respond(text, session=session):
                if first_ms is None:
                    first_ms = (time.perf_counter() - t0) * 1000
                    await BUS.emit("turn.first_token", ms=round(first_ms))
                pieces.append(sentence)
                await BUS.emit("jarvis.says", text=sentence)
                if speak:
                    await self.speaker.say(sentence)
        finally:
            self.busy = False
            self.gate.open()
            await BUS.emit(
                "turn.end", ms=round((time.perf_counter() - t0) * 1000),
                first_ms=round(first_ms or 0), sentences=len(pieces),
            )
        return " ".join(pieces)

    # --------------------------------------------------------------- sommeil
    async def _sleep_cycle(self) -> None:
        """La consolidation. On attend que Jarvis soit oisif pour ne rien ralentir."""
        while True:
            await asyncio.sleep(CFG.consolidate_every_s)
            while self.busy or self.speaker.speaking:
                await asyncio.sleep(5)
            try:
                await consolidate(self.memory, self.brain)
            except Exception as exc:
                await BUS.emit("memory.consolidation_failed", error=str(exc))

    def snapshot(self) -> dict:
        return {
            "uptime_s": round(time.time() - self.started),
            "memory": self.memory.stats(),
            "tools": REGISTRY.names(),
            "wake_word": wake_available(),
            "tts": tts.backend(),
            "listening": self.gate.is_open,
            "busy": self.busy,
            "offline": True,
        }
