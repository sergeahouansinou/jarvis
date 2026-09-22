"""Transcription locale via Whisper (MLX / Metal).

Le modele tourne dans un thread : une transcription de 3 s prend ~150 ms sur
Apple Silicon, mais elle est bloquante -- hors de question de figer la boucle.
"""
from __future__ import annotations

import asyncio
import time

import numpy as np

from ..bus import BUS
from ..config import CFG

_ready: bool | None = None


async def warmup() -> bool:
    """Premiere transcription a vide : charge et compile le modele."""
    global _ready
    if _ready is not None:
        return _ready
    silence = np.zeros(CFG.sample_rate, dtype=np.float32)
    await BUS.emit("stt.loading", model=CFG.stt_model)
    _ready = (await transcribe(silence, quiet=True)) is not None
    await BUS.emit("stt.ready" if _ready else "stt.failed", model=CFG.stt_model)
    return _ready


async def transcribe(audio: np.ndarray, quiet: bool = False) -> str | None:
    t0 = time.perf_counter()

    def _run() -> str:
        import mlx_whisper

        out = mlx_whisper.transcribe(
            audio.astype(np.float32),
            path_or_hf_repo=CFG.stt_model,
            language="fr",
            condition_on_previous_text=False,
        )
        return (out.get("text") or "").strip()

    try:
        text = await asyncio.to_thread(_run)
    except Exception as exc:
        if not quiet:
            await BUS.emit("stt.error", error=str(exc))
        return None

    if not quiet:
        await BUS.emit(
            "stt.text", text=text,
            ms=round((time.perf_counter() - t0) * 1000),
            audio_s=round(len(audio) / CFG.sample_rate, 2),
        )
    return text
