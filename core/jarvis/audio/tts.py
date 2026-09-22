"""Synthese vocale locale, phrase par phrase et interruptible.

Deux voies :
  1. Kokoro (ONNX, local, naturel) si installe -- `uv sync --extra voice`
  2. `say` de macOS sinon : moins beau, mais instantane et deja la.
Le point qui compte n'est aucune des deux : c'est de parler des la PREMIERE
phrase pendant que le modele ecrit encore la suite. C'est ce qui fait passer
la latence percue sous la seconde.
"""
from __future__ import annotations

import asyncio
import shutil

from ..bus import BUS
from ..config import CFG

_kokoro = None
_backend = "say"


async def init() -> str:
    global _kokoro, _backend
    try:
        from kokoro_onnx import Kokoro  # type: ignore

        _kokoro = await asyncio.to_thread(Kokoro, "kokoro-v1.0.onnx", "voices-v1.0.bin")
        _backend = "kokoro"
    except Exception:
        _kokoro = None
        _backend = "say" if shutil.which("say") else "aucun"
    await BUS.emit("tts.ready", backend=_backend)
    return _backend


def backend() -> str:
    return _backend


class Speaker:
    """File d'attente de phrases. `interrupt()` coupe net (barge-in)."""

    def __init__(self, mic=None) -> None:
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.mic = mic
        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task | None = None
        self.speaking = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def say(self, sentence: str) -> None:
        await self.queue.put(sentence)

    async def interrupt(self) -> None:
        while not self.queue.empty():
            self.queue.get_nowait()
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
        await BUS.emit("tts.interrupted")

    async def _loop(self) -> None:
        while True:
            sentence = await self.queue.get()
            if sentence is None:
                return
            await self._utter(sentence)

    async def _utter(self, sentence: str) -> None:
        self.speaking = True
        if self.mic is not None:
            self.mic.muted = True                  # anti-echo : on se coupe le micro
        await BUS.emit("tts.speaking", text=sentence)
        try:
            if _backend == "kokoro":
                await self._kokoro_say(sentence)
            elif _backend == "say":
                self._proc = await asyncio.create_subprocess_exec(
                    "say", "-v", CFG.say_voice, sentence,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                await self._proc.wait()
        except Exception as exc:
            await BUS.emit("tts.error", error=str(exc))
        finally:
            self._proc = None
            self.speaking = False
            await asyncio.sleep(0.12)              # laisse mourir l'echo de la piece
            if self.mic is not None:
                self.mic.muted = False
            await BUS.emit("tts.done", text=sentence)

    async def _kokoro_say(self, sentence: str) -> None:
        import sounddevice as sd

        samples, rate = await asyncio.to_thread(
            _kokoro.create, sentence, voice="ff_siwis", speed=1.05, lang="fr-fr"
        )
        await asyncio.to_thread(sd.play, samples, rate)
        await asyncio.to_thread(sd.wait)
