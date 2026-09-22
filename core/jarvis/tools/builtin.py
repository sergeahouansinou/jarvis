"""Les outils de base. Lecture seule par defaut ; l'action reste opt-in."""
from __future__ import annotations

import asyncio
import datetime as dt
import platform
import shutil

from .registry import REGISTRY

_memory = None


def bind(memory) -> None:
    """Les outils memoire ont besoin de l'instance : on l'injecte au demarrage."""
    global _memory
    _memory = memory


@REGISTRY.add(
    "get_time",
    "Donne la date et l'heure locales actuelles.",
    {"type": "object", "properties": {}, "required": []},
    hints=("heure", "date", "jour", "aujourd'hui"),
)
def get_time() -> str:
    now = dt.datetime.now().astimezone()
    return now.strftime("%A %d %B %Y, %H:%M (%Z)")


@REGISTRY.add(
    "remember_fact",
    "Enregistre durablement un fait, une preference ou un objectif de l'utilisateur.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Le fait, formule de maniere autonome."},
            "kind": {"type": "string", "enum": ["fact", "preference", "goal", "skill"]},
            "importance": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["text"],
    },
    hints=("retiens", "souviens", "note que", "rappelle-toi"),
)
async def remember_fact(text: str, kind: str = "fact", importance: float = 0.6) -> str:
    await _memory.learn(text, kind=kind, importance=importance)
    return f"Retenu : {text}"


@REGISTRY.add(
    "search_memory",
    "Cherche dans la memoire long terme (faits, preferences, objectifs passes).",
    {
        "type": "object",
        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["query"],
    },
    hints=("hier", "la derniere fois", "on avait dit", "mes notes"),
)
def search_memory(query: str, limit: int = 6) -> str:
    hits = _memory.recall(query, k=limit)
    if not hits:
        return "Rien en memoire sur ce sujet."
    return "\n".join(f"- {h.text} (score {h.score:.2f})" for h in hits)


@REGISTRY.add(
    "relate_entities",
    "Enregistre un lien entre deux entites dans le graphe de memoire.",
    {
        "type": "object",
        "properties": {
            "src": {"type": "string"}, "verb": {"type": "string"}, "dst": {"type": "string"},
        },
        "required": ["src", "verb", "dst"],
    },
)
def relate_entities(src: str, verb: str, dst: str) -> str:
    _memory.relate(src, verb, dst)
    return f"{src} --{verb}--> {dst}"


@REGISTRY.add(
    "system_status",
    "Etat de la machine et de la memoire de Jarvis.",
    {"type": "object", "properties": {}, "required": []},
    hints=("systeme", "etat", "statut", "machine"),
)
def system_status() -> str:
    disk = shutil.disk_usage("/")
    stats = _memory.stats()
    return (
        f"{platform.system()} {platform.release()} ({platform.machine()}), "
        f"disque libre {disk.free / 1e9:.0f} Go. "
        f"Memoire : {stats['episodes']} episodes, {stats['facts']} faits, "
        f"{stats['entities']} entites, {stats['pending']} en attente de consolidation."
    )


@REGISTRY.add(
    "open_app",
    "Ouvre une application macOS par son nom.",
    {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    danger=True,
    hints=("ouvre", "lance", "demarre"),
)
async def open_app(name: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "open", "-a", name, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, err = await proc.communicate()
    return f"{name} ouvert." if proc.returncode == 0 else f"Echec : {err.decode().strip()}"
