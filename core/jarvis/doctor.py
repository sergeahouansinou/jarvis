"""`jarvis doctor` : verifie ce qui doit etre vrai avant de parler.

Un assistant local echoue rarement bruyamment -- il echoue en restant muet.
Ce diagnostic transforme chaque cause probable en une ligne lisible.
"""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

from .config import CFG

OK, WARN, BAD = "  ok  ", " tiède", " échec"


def _has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _hf_cache_size() -> float:
    cache = Path.home() / ".cache" / "huggingface"
    if not cache.exists():
        return 0.0
    return sum(f.stat().st_size for f in cache.rglob("*") if f.is_file()) / 1e9


def run() -> int:
    lines: list[tuple[str, str, str]] = []

    # --- inference ---
    for mod, label in (("mlx", "MLX (Metal)"), ("mlx_lm", "modeles de langage"),
                       ("mlx_whisper", "transcription Whisper")):
        lines.append((OK if _has(mod) else BAD, label,
                      "installe" if _has(mod) else f"manquant : uv pip install {mod}"))

    # --- embeddings ---
    if _has("mlx_embeddings"):
        lines.append((OK, "embeddings", "mlx-embeddings"))
    elif _has("sentence_transformers"):
        lines.append((OK, "embeddings", "sentence-transformers (torch)"))
    else:
        lines.append((WARN, "embeddings", "repli par hachage — le rappel semantique sera faible"))

    # --- audio ---
    if _has("sounddevice"):
        try:
            import sounddevice as sd

            device = sd.query_devices(kind="input")["name"]
            lines.append((OK, "micro", device))
        except Exception as exc:
            lines.append((BAD, "micro", f"aucune entree : {exc}"))
    else:
        lines.append((BAD, "micro", "sounddevice manquant"))

    lines.append((OK, "mot-declencheur", "openWakeWord") if _has("openwakeword")
                 else (WARN, "mot-declencheur", "absent — filtrage du nom apres transcription"))

    if _has("kokoro_onnx"):
        lines.append((OK, "voix", "Kokoro (neuronale)"))
    elif shutil.which("say"):
        lines.append((WARN, "voix", "`say` de macOS — fonctionne, mais s'entend"))
    else:
        lines.append((BAD, "voix", "aucune synthese disponible"))

    # --- stockage ---
    free = shutil.disk_usage("/").free / 1e9
    cached = _hf_cache_size()
    needed = max(0.0, 8.5 - cached)
    level = OK if free > needed + 5 else (WARN if free > needed else BAD)
    lines.append((level, "espace disque",
                  f"{free:.0f} Go libres · modeles en cache {cached:.1f} Go · "
                  f"{needed:.1f} Go restant a telecharger"))

    # --- memoire ---
    if CFG.db_path.exists():
        from .memory import Memory

        s = Memory().stats()
        lines.append((OK, "memoire", f"{s['episodes']} episodes · {s['facts']} faits · "
                                     f"{s['pending']} a consolider"))
    else:
        lines.append((WARN, "memoire", "base vide — elle se creera au premier echange"))

    print(f"\n  Diagnostic de Jarvis\n  {'─' * 62}")
    for status, label, detail in lines:
        print(f"  [{status}] {label:<18} {detail}")
    print(f"  {'─' * 62}")
    print(f"  rapide : {CFG.model_fast}")
    print(f"  profond: {CFG.model_deep}")
    print(f"  base   : {CFG.db_path}\n")

    return 1 if any(s == BAD for s, _, _ in lines) else 0
