"""Capture micro : sounddevice remplit un callback temps reel, on transvase
vers asyncio sans jamais bloquer le thread audio (toute latence ici s'entend).
"""
from __future__ import annotations

import asyncio

import numpy as np

from ..bus import BUS
from ..config import CFG


class Microphone:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=200)
        self._stream = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.muted = False     # coupe l'entree pendant que Jarvis parle (anti-echo)

    def _callback(self, indata, frames, time_info, status) -> None:
        if self.muted or self._loop is None:
            return
        frame = indata[:, 0].copy()
        try:
            self._loop.call_soon_threadsafe(self.queue.put_nowait, frame)
        except (asyncio.QueueFull, RuntimeError):
            pass

    async def start(self) -> bool:
        import sounddevice as sd

        self._loop = asyncio.get_running_loop()
        try:
            self._stream = sd.InputStream(
                samplerate=CFG.sample_rate, channels=1, dtype="float32",
                blocksize=CFG.frame_samples, callback=self._callback,
            )
            self._stream.start()
            name = sd.query_devices(kind="input")["name"]
            await BUS.emit("audio.mic_open", device=name, rate=CFG.sample_rate)
            return True
        except Exception as exc:
            await BUS.emit("audio.mic_failed", error=str(exc))
            return False

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    async def frames(self):
        while True:
            yield await self.queue.get()
