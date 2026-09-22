"""La memoire de Jarvis : quatre couches derriere une seule facade.

    travail   -> en RAM, le tour de parole en cours
    episodique-> tout ce qui s'est dit, immuable
    semantique-> les faits extraits, vectorises, notes
    graphe    -> qui est lie a quoi

On ecrit toujours dans l'episodique en premier (c'est la verite), puis la
consolidation en derive le reste. Jamais l'inverse.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from collections import deque
from dataclasses import dataclass
from typing import Any

from ..config import CFG
from . import embed as E
from . import store
from .recall import Scored, hybrid


@dataclass(slots=True)
class Turn:
    role: str
    content: str


class Memory:
    def __init__(self, path=None, dim: int | None = None) -> None:
        self.dim = dim or CFG.embed_dim
        self.con: sqlite3.Connection = store.connect(path or CFG.db_path)
        self._lock = asyncio.Lock()
        self.working: deque[Turn] = deque(maxlen=24)   # memoire de travail
        self.backend = E.init(self.dim)

    # ---------------------------------------------------------------- episodique
    async def remember(self, role: str, content: str, session: str = "default", **meta: Any) -> int:
        async with self._lock:
            cur = self.con.execute(
                "INSERT INTO episodes(ts, session, role, content, meta) VALUES (?,?,?,?,?)",
                (store.now(), session, role, content, json.dumps(meta, ensure_ascii=False)),
            )
            self.con.commit()
        self.working.append(Turn(role, content))
        return int(cur.lastrowid)

    def timeline(self, limit: int = 50) -> list[dict]:
        rows = self.con.execute(
            "SELECT id, ts, role, content FROM episodes ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def pending(self, limit: int = 200) -> list[dict]:
        rows = self.con.execute(
            "SELECT id, ts, role, content FROM episodes WHERE consolidated = 0 ORDER BY ts LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_consolidated(self, ids: list[int]) -> None:
        if not ids:
            return
        self.con.executemany("UPDATE episodes SET consolidated = 1 WHERE id = ?", [(i,) for i in ids])
        self.con.commit()

    # ---------------------------------------------------------------- semantique
    async def learn(
        self, text: str, kind: str = "fact", importance: float = 0.5, source_ep: int | None = None
    ) -> int | None:
        text = text.strip()
        if not text:
            return None
        vec = E.pack(E.embed(text, self.dim))
        async with self._lock:
            cur = self.con.execute(
                """INSERT INTO facts(ts, text, kind, importance, source_ep, vector)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(text) DO UPDATE SET
                       importance = max(facts.importance, excluded.importance),
                       ts = excluded.ts""",
                (store.now(), text, kind, max(0.0, min(1.0, importance)), source_ep, vec),
            )
            self.con.commit()
        return int(cur.lastrowid)

    def recall(self, query: str, k: int | None = None) -> list[Scored]:
        k = k or CFG.recall_k
        rows = self.con.execute(
            "SELECT id, ts, text, kind, importance, last_used, vector FROM facts"
        ).fetchall()
        if not rows:
            return []
        try:
            lex = [
                r["rowid"] for r in self.con.execute(
                    "SELECT rowid FROM facts_fts WHERE facts_fts MATCH ? ORDER BY rank LIMIT 40",
                    (_fts_query(query),),
                ).fetchall()
            ]
        except sqlite3.OperationalError:
            lex = []
        hits = hybrid(
            rows, E.embed(query, self.dim), lex, self.dim,
            CFG.decay_half_life_h, k, lexical_floor=set(lex),
        )
        if hits:
            self.con.executemany(
                "UPDATE facts SET last_used = ?, hits = hits + 1 WHERE id = ?",
                [(store.now(), h.id) for h in hits],
            )
            self.con.commit()
        return hits

    def forget(self, fact_id: int) -> None:
        self.con.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        self.con.commit()

    # ---------------------------------------------------------------- graphe
    def entity(self, name: str, kind: str = "thing", **attrs: Any) -> int:
        self.con.execute(
            "INSERT OR IGNORE INTO entities(name, kind, attrs, ts) VALUES (?,?,?,?)",
            (name, kind, json.dumps(attrs, ensure_ascii=False), store.now()),
        )
        self.con.commit()
        row = self.con.execute(
            "SELECT id FROM entities WHERE name = ? AND kind = ?", (name, kind)
        ).fetchone()
        return int(row["id"])

    def relate(self, src: str, verb: str, dst: str, src_kind="thing", dst_kind="thing") -> None:
        a, b = self.entity(src, src_kind), self.entity(dst, dst_kind)
        self.con.execute(
            """INSERT INTO relations(src, verb, dst, ts) VALUES (?,?,?,?)
               ON CONFLICT(src, verb, dst) DO UPDATE SET weight = relations.weight + 1.0""",
            (a, verb, b, store.now()),
        )
        self.con.commit()

    def neighbours(self, name: str, depth: int = 1) -> list[dict]:
        seen, frontier, out, edges = {name}, [name], [], set()
        for _ in range(max(1, depth)):
            if not frontier:
                break
            marks = ",".join("?" * len(frontier))
            rows = self.con.execute(
                f"""SELECT s.name AS src, r.verb, d.name AS dst, r.weight
                    FROM relations r
                    JOIN entities s ON s.id = r.src
                    JOIN entities d ON d.id = r.dst
                    WHERE s.name IN ({marks}) OR d.name IN ({marks})""",
                (*frontier, *frontier),
            ).fetchall()
            frontier = []
            for r in rows:
                key = (r["src"], r["verb"], r["dst"])
                if key not in edges:      # une arete est atteignable par ses deux bouts
                    edges.add(key)
                    out.append(dict(r))
                for n in (r["src"], r["dst"]):
                    if n not in seen:
                        seen.add(n)
                        frontier.append(n)
        return out

    # ---------------------------------------------------------------- contexte
    def context_block(self, query: str) -> str:
        """Le bloc injecte dans le prompt : ce que Jarvis 'a en tete' pour repondre."""
        parts = []
        facts = self.recall(query)
        if facts:
            parts.append("Ce que je sais d'utile ici :\n" + "\n".join(f"- {f.text}" for f in facts))
        graph = self.neighbours(query.strip()[:64]) if query.strip() else []
        if graph:
            rels = "\n".join(f"- {g['src']} --{g['verb']}--> {g['dst']}" for g in graph[:10])
            parts.append("Liens connus :\n" + rels)
        return "\n\n".join(parts)

    def stats(self) -> dict:
        q = lambda sql: int(self.con.execute(sql).fetchone()[0])
        return {
            "episodes": q("SELECT count(*) FROM episodes"),
            "facts": q("SELECT count(*) FROM facts"),
            "entities": q("SELECT count(*) FROM entities"),
            "relations": q("SELECT count(*) FROM relations"),
            "pending": q("SELECT count(*) FROM episodes WHERE consolidated = 0"),
            "embed_backend": self.backend,
        }


def _fts_query(text: str) -> str:
    toks = [t for t in "".join(c if c.isalnum() else " " for c in text).split() if len(t) > 2]
    return " OR ".join(toks) if toks else '""'
