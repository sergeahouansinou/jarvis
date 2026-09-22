"""Vectorisation du texte.

Deux implementations, choisies au demarrage :
  1. un vrai modele d'embedding local (MLX / sentence-transformers) s'il est la ;
  2. sinon un repli deterministe par hachage de n-grammes -- sans dependance,
     honnete sur le lexical, faible sur le sens. C'est un point de montee en
     qualite identifie, pas une solution definitive.
"""
from __future__ import annotations

import hashlib
import re

import numpy as np

_WORD = re.compile(r"\w+", re.UNICODE)
_model = None
_backend = "hash"
_kind = "hash"


def backend() -> str:
    return _backend


def _try_load(dim: int) -> None:
    """Charge le modele d'embedding local.

    Trois voies, par ordre de preference : MLX (leger, Metal), PyTorch
    (lourd mais universel), puis repli par hachage sans aucune dependance.
    """
    global _model, _backend, _kind
    from ..config import CFG

    try:
        from mlx_embeddings import load as mlx_load  # type: ignore

        _model = mlx_load(CFG.embed_model)
        _kind, _backend = "mlx", CFG.embed_model.split("/")[-1] + " (mlx)"
        return
    except Exception:
        pass

    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        _model = SentenceTransformer(CFG.embed_model)
        _kind, _backend = "st", CFG.embed_model.split("/")[-1] + " (torch)"
        return
    except Exception:
        pass

    _model, _kind, _backend = None, "hash", "hash (repli)"


def _hash_embed(text: str, dim: int) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    words = _WORD.findall(text.lower())
    grams = words + [" ".join(words[i : i + 2]) for i in range(len(words) - 1)]
    for g in grams:
        h = hashlib.blake2b(g.encode(), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % dim
        sign = 1.0 if h[4] & 1 else -1.0
        vec[idx] += sign
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm else vec


def embed(text: str, dim: int = 384) -> np.ndarray:
    if _model is None:
        return _hash_embed(text, dim)

    if _kind == "mlx":
        model, tokenizer = _model
        out = model(**tokenizer.batch_encode_plus([text], return_tensors="mlx", padding=True))
        v = np.asarray(out.text_embeds[0], dtype=np.float32)
    else:
        v = np.asarray(_model.encode(text), dtype=np.float32)

    n = float(np.linalg.norm(v))
    return v / n if n else v


def init(dim: int = 384) -> str:
    _try_load(dim)
    return _backend


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def pack(v: np.ndarray) -> bytes:
    return v.astype(np.float32).tobytes()


def unpack(b: bytes | None, dim: int) -> np.ndarray:
    if not b:
        return np.zeros(dim, dtype=np.float32)
    return np.frombuffer(b, dtype=np.float32)
