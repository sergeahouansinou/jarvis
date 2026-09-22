"""Inference locale via MLX : Metal + memoire unifiee, rien ne sort de la machine.

Deux modeles coexistent, charges paresseusement :
  fast -- 4B quantifie, ~2,5 Go : le reflexe, premier token en ~200 ms
  deep -- 8B quantifie, ~4,5 Go : les outils, la memoire, la consolidation
Sur 16 Go de memoire unifiee les deux tiennent ensemble avec Whisper.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from ..bus import BUS
from ..config import CFG

_pool: dict[str, tuple] = {}
_names = {"fast": CFG.model_fast, "deep": CFG.model_deep}
_lock = asyncio.Lock()


def loaded(role: str) -> bool:
    return role in _pool


async def load(role: str) -> bool:
    """Charge un modele. Renvoie False si MLX ou le modele est indisponible."""
    if role in _pool:
        return True
    async with _lock:
        if role in _pool:
            return True
        name = _names[role]
        await BUS.emit("brain.loading", role=role, model=name)

        def _load():
            from mlx_lm import load as mlx_load

            return mlx_load(name)

        try:
            _pool[role] = await asyncio.to_thread(_load)
            await BUS.emit("brain.loaded", role=role, model=name)
            return True
        except Exception as exc:
            await BUS.emit("brain.load_failed", role=role, model=name, error=str(exc))
            return False


async def stream(
    role: str, system: str, messages: list[dict], max_tokens: int = 256
) -> AsyncIterator[str]:
    """Genere token par token, sans bloquer la boucle asyncio."""
    if not await load(role):
        return
    from mlx_lm import stream_generate
    from mlx_lm.sample_utils import make_sampler

    model, tokenizer = _pool[role]
    chat = [{"role": "system", "content": system}, *messages]
    prompt = tokenizer.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    sampler = make_sampler(temp=0.7, top_p=0.95)

    def worker() -> None:
        try:
            for step in stream_generate(
                model, tokenizer, prompt, max_tokens=max_tokens, sampler=sampler
            ):
                loop.call_soon_threadsafe(queue.put_nowait, step.text)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, f"\n[erreur modele: {exc}]")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, worker)
    while (chunk := await queue.get()) is not None:
        yield chunk


async def complete(role: str, system: str, messages: list[dict], max_tokens: int = 1024) -> str:
    return "".join([c async for c in stream(role, system, messages, max_tokens)])


def unload(role: str) -> None:
    """Libere la memoire unifiee -- utile avant une tache lourde."""
    _pool.pop(role, None)
