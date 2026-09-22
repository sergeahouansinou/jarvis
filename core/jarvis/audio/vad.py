"""Detection d'activite vocale par energie, avec plancher de bruit adaptatif.

Volontairement sans dependance : c'est la brique la plus facile a remplacer
par Silero plus tard, et la seule qui doit tenir en quelques microsecondes.
La fin de parole est ce qui determine la latence percue -- 700 ms par defaut.
"""
from __future__ import annotations

import numpy as np

from ..config import CFG


class VAD:
    def __init__(self, silence_ms: int | None = None) -> None:
        self.silence_frames = (silence_ms or CFG.silence_ms) // CFG.frame_ms
        self.noise = 0.003            # plancher, reestime en continu
        self.speaking = False
        self.quiet = 0
        self.buffer: list[np.ndarray] = []
        self.preroll: list[np.ndarray] = []   # 300 ms avant le declenchement
        self.preroll_max = 300 // CFG.frame_ms

    @staticmethod
    def energy(frame: np.ndarray) -> float:
        return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))

    def feed(self, frame: np.ndarray) -> np.ndarray | None:
        """Renvoie l'enonce complet quand la parole se termine, sinon None."""
        e = self.energy(frame)
        threshold = max(self.noise * 3.0, 0.008)

        if e < threshold:
            self.noise = 0.98 * self.noise + 0.02 * e   # on n'apprend que le silence

        if not self.speaking:
            self.preroll.append(frame)
            if len(self.preroll) > self.preroll_max:
                self.preroll.pop(0)
            if e >= threshold:
                self.speaking = True
                self.buffer = [*self.preroll, frame]
                self.preroll = []
                self.quiet = 0
            return None

        self.buffer.append(frame)
        self.quiet = 0 if e >= threshold else self.quiet + 1

        too_long = len(self.buffer) * CFG.frame_ms / 1000 > CFG.max_utterance_s
        if self.quiet >= self.silence_frames or too_long:
            audio = np.concatenate(self.buffer)
            self.speaking, self.buffer, self.quiet = False, [], 0
            return audio if len(audio) > CFG.sample_rate * 0.25 else None
        return None

    def reset(self) -> None:
        self.speaking, self.buffer, self.quiet, self.preroll = False, [], 0, []
