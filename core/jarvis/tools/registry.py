"""Registre d'outils : ce que Jarvis peut *faire*, pas seulement dire.

Un outil = une fonction + un schema JSON. Le schema part tel quel a Claude ;
l'execution reste locale. Tout passe par le bus, donc le HUD voit chaque appel.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable
    danger: bool = False          # exige une confirmation explicite
    hints: tuple[str, ...] = ()   # mots qui suggerent cet outil (pour le routage)


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self.allow_dangerous = False

    def add(self, name: str, description: str, schema: dict, *,
            danger: bool = False, hints: tuple[str, ...] = ()) -> Callable:
        def deco(fn: Callable) -> Callable:
            self._tools[name] = Tool(name, description, schema, fn, danger, hints)
            return fn

        return deco

    def schemas(self) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "input_schema": t.schema}
            for t in self._tools.values()
            if not t.danger or self.allow_dangerous
        ]

    def describe(self) -> str:
        """Description compacte des outils, injectee dans le prompt local."""
        lines = []
        for t in self._tools.values():
            if t.danger and not self.allow_dangerous:
                continue
            props = t.schema.get("properties", {})
            args = ", ".join(
                f"{k}: {v.get('type', 'string')}" for k, v in props.items()
            ) or "aucun argument"
            lines.append(f"- {t.name}({args}) : {t.description}")
        return "\n".join(lines)

    def might_be_needed(self, text: str) -> bool:
        low = text.lower()
        return any(h in low for h in (h for t in self._tools.values() for h in t.hints))

    async def run(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        tool = self._tools.get(name)
        if tool is None:
            return f"Outil inconnu : {name}", True
        if tool.danger and not self.allow_dangerous:
            return "Cet outil est desactive (action sensible).", True
        try:
            res = tool.fn(**args)
            if inspect.isawaitable(res):
                res = await res
            return (res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)), False
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}", True

    def __len__(self) -> int:
        return len(self._tools)

    def names(self) -> list[str]:
        return list(self._tools)


REGISTRY = Registry()
