"""Scoring de rappel : pertinence x fraicheur x importance.

Sans ce triptyque, une memoire qui grossit se noie dans son propre bruit au
bout de quelques mois. Le modele suit l'esprit des Generative Agents
(Stanford, 2023) : on ne remonte pas ce qui ressemble le plus, on remonte ce
qui compte le plus *maintenant*.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np

from . import embed as E


@dataclass(slots=True)
class Scored:
    id: int
    text: str
    kind: str
    score: float
    relevance: float
    recency: float
    importance: float

    def as_json(self) -> dict:
        return {
            "id": self.id, "text": self.text, "kind": self.kind,
            "score": round(self.score, 4), "relevance": round(self.relevance, 4),
            "recency": round(self.recency, 4), "importance": round(self.importance, 4),
        }


def recency(ts: float, half_life_h: float) -> float:
    """Decroissance exponentielle : 1.0 a l'instant t, 0.5 apres une demi-vie."""
    age_h = max(0.0, (time.time() - ts) / 3600.0)
    return math.exp(-math.log(2) * age_h / max(half_life_h, 1e-6))


def rrf(ranks: dict[int, int], k: int = 60) -> dict[int, float]:
    """Reciprocal Rank Fusion : fusionne deux classements sans normaliser les scores."""
    return {i: 1.0 / (k + r) for i, r in ranks.items()}


def hybrid(
    rows: list,
    query_vec: np.ndarray,
    lexical_ids: list[int],
    dim: int,
    half_life_h: float,
    k: int,
    lexical_floor: set[int] | None = None,
    min_relevance: float = 0.25,
) -> list[Scored]:
    """Fusionne recherche vectorielle et BM25, puis pondere par age et importance."""
    lex_rank = {fid: i for i, fid in enumerate(lexical_ids)}
    lex = rrf(lex_rank)

    vec_pairs = [(r["id"], E.cosine(query_vec, E.unpack(r["vector"], dim))) for r in rows]
    vec_pairs.sort(key=lambda p: p[1], reverse=True)
    vec = rrf({fid: i for i, (fid, _) in enumerate(vec_pairs)})
    cos = dict(vec_pairs)

    out: list[Scored] = []
    for r in rows:
        fid = r["id"]
        rel = vec.get(fid, 0.0) + lex.get(fid, 0.0)
        rec = recency(max(r["ts"], r["last_used"]), half_life_h)
        imp = float(r["importance"])
        out.append(
            Scored(
                id=fid, text=r["text"], kind=r["kind"],
                score=rel * (0.35 + 0.65 * rec) * (0.35 + 0.65 * imp),
                relevance=max(cos.get(fid, 0.0), 0.0), recency=rec, importance=imp,
            )
        )
    out.sort(key=lambda s: s.score, reverse=True)

    # Un souvenir ne remonte que s'il ressemble vraiment a la question, ou si
    # la recherche lexicale l'a trouve. Sinon une base de 4 faits les renvoie
    # tous les 4, et le prompt se remplit de bruit.
    lexical_floor = lexical_floor or set()
    kept = [s for s in out if s.relevance >= min_relevance or s.id in lexical_floor]
    return kept[:k]
