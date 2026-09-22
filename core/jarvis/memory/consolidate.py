"""La consolidation : le sommeil de Jarvis.

Periodiquement, on relit les episodes non traites, on en extrait les faits
durables, on note leur importance et on met a jour le graphe. C'est ce qui
transforme une transcription qui gonfle indefiniment en une connaissance qui
tient. Sans cette etape, la memoire n'est qu'un log.
"""
from __future__ import annotations

import json

from ..bus import BUS

PROMPT = """Tu analyses un extrait de journal de conversation entre un utilisateur et son assistant.
Extrais UNIQUEMENT ce qui merite d'etre retenu sur le long terme : preferences stables,
faits durables sur l'utilisateur, objectifs, decisions, entites et leurs liens.
Ignore le bavardage, les questions ponctuelles et tout ce qui est deja evident.

Reponds en JSON strict, sans texte autour :
{
  "facts": [{"text": "...", "kind": "fact|preference|goal|skill", "importance": 0.0-1.0}],
  "entities": [{"name": "...", "kind": "person|project|place|device|thing"}],
  "relations": [{"src": "...", "verb": "...", "dst": "..."}]
}
S'il n'y a rien a retenir, renvoie des listes vides."""


async def consolidate(memory, brain, batch: int = 80) -> dict:
    episodes = memory.pending(batch)
    if not episodes:
        return {"episodes": 0, "facts": 0}

    transcript = "\n".join(f"[{e['role']}] {e['content']}" for e in episodes)
    await BUS.emit("memory.consolidating", episodes=len(episodes))

    raw = await brain.complete(
        system=PROMPT,
        messages=[{"role": "user", "content": transcript[:8_000]}],
        max_tokens=1500,
    )

    data = _parse(raw)
    learned = 0
    for f in data.get("facts", []):
        if isinstance(f, dict) and f.get("text"):
            await memory.learn(
                f["text"], kind=f.get("kind", "fact"), importance=float(f.get("importance", 0.5))
            )
            learned += 1
    for e in data.get("entities", []):
        if isinstance(e, dict) and e.get("name"):
            memory.entity(e["name"], e.get("kind", "thing"))
    for r in data.get("relations", []):
        if isinstance(r, dict) and r.get("src") and r.get("dst"):
            memory.relate(r["src"], r.get("verb", "lie_a"), r["dst"])

    memory.mark_consolidated([e["id"] for e in episodes])
    result = {"episodes": len(episodes), "facts": learned}
    await BUS.emit("memory.consolidated", **result, stats=memory.stats())
    return result


def _parse(raw: str) -> dict:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].removeprefix("json").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}
