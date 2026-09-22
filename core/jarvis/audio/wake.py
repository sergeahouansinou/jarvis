"""Ecoute du nom "Jarvis".

Si openWakeWord est installe, il gate le pipeline pour une empreinte CPU
quasi nulle. Sinon on retombe sur une strategie honnete et sans dependance :
on transcrit localement chaque enonce et on ne reagit que s'il commence par
le nom -- ou si l'on est deja dans une fenetre de conversation ouverte.
"""
from __future__ import annotations

import re
import time

from ..config import CFG

_oww = None
_available = False

# "jarvis", "jarviss", "djarvisse"... Whisper hesite beaucoup sur ce mot.
NAME = re.compile(r"^\W*(d?j[ae]rv[iy]s+e?|jarvice|jervis)\b[\s,.:!?-]*", re.IGNORECASE)


def try_load() -> bool:
    global _oww, _available
    try:
        from openwakeword.model import Model  # type: ignore

        _oww = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        _available = True
    except Exception:
        _oww, _available = None, False
    return _available


def available() -> bool:
    return _available


def detect(frame) -> bool:
    if not _available:
        return False
    import numpy as np

    scores = _oww.predict((frame * 32767).astype(np.int16))
    return any(s > 0.5 for s in scores.values())


class Gate:
    """Fenetre de conversation : une fois reveille, Jarvis reste a l'ecoute."""

    def __init__(self, window_s: float = 25.0) -> None:
        self.window_s = window_s
        self.until = 0.0

    def open(self) -> None:
        self.until = time.time() + self.window_s

    @property
    def is_open(self) -> bool:
        return time.time() < self.until

    def close(self) -> None:
        self.until = 0.0

    def accept(self, text: str) -> tuple[bool, str]:
        """Renvoie (on repond ?, texte nettoye du nom)."""
        stripped = NAME.sub("", text).strip()
        if stripped != text.strip():
            self.open()
            return bool(stripped), stripped
        if self.is_open:
            self.open()
            return True, text.strip()
        return False, text.strip()
