"""Configuration centrale, lue une seule fois au demarrage.

Jarvis tourne entierement en local : aucune cle API, aucun appel sortant.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


@dataclass(frozen=True)
class Config:
    # --- reseau (boucle locale uniquement) ---
    host: str = os.getenv("JARVIS_HOST", "127.0.0.1")
    port: int = int(os.getenv("JARVIS_PORT", "8787"))

    # --- modeles locaux ---
    model_fast: str = os.getenv("JARVIS_MODEL_FAST", "mlx-community/Qwen3-4B-Instruct-2507-4bit")
    model_deep: str = os.getenv("JARVIS_MODEL_DEEP", "mlx-community/Qwen3-8B-4bit")
    stt_model: str = os.getenv("JARVIS_STT_MODEL", "mlx-community/whisper-large-v3-turbo")
    embed_model: str = os.getenv(
        "JARVIS_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )

    # --- audio ---
    sample_rate: int = 16_000
    frame_ms: int = 32
    wake_words: tuple[str, ...] = ("jarvis",)
    silence_ms: int = 700          # silence qui clot un tour de parole
    max_utterance_s: float = 20.0
    say_voice: str = os.getenv("JARVIS_SAY_VOICE", "Thomas")

    # --- memoire ---
    db_path: Path = field(default_factory=lambda: DATA / "jarvis.db")
    embed_dim: int = 384
    recall_k: int = 8
    decay_half_life_h: float = 72.0   # demi-vie de la fraicheur d'un souvenir
    consolidate_every_s: int = 900    # le "sommeil" toutes les 15 min

    @property
    def frame_samples(self) -> int:
        return self.sample_rate * self.frame_ms // 1000


CFG = Config()
DATA.mkdir(parents=True, exist_ok=True)
