"""Routage rapide <-> profond, entierement sur la machine.

Meme principe que l'escalade cloud d'origine, mais entre deux modeles locaux :
le reflexe repond en ~200 ms avec le 4B, la reflexion mobilise le 8B.
Rien ne sort de la machine dans aucun des deux cas.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Intentions reflexes : courtes, sans ambiguite, sans outil.
REFLEX = re.compile(
    r"^\s*(bonjour|salut|hello|merci|ok|d'accord|stop|arr[eê]te|annule|tais-toi|"
    r"quelle heure|ça va|ca va|comment vas-tu|au revoir|bonne nuit|oui|non)\b",
    re.IGNORECASE,
)

# Marqueurs de raisonnement : on mobilise le gros modele.
DEEP = re.compile(
    r"\b(pourquoi|comment|explique|compare|analyse|con[cç]ois|architecture|strat[ée]gie|"
    r"code|d[ée]bogue|refactor|plan|rappelle[- ]toi|souviens|retiens|hier|la semaine|"
    r"budget|calcule|optimise|[ée]cris|r[ée]sume|traduis|liste)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class Route:
    target: str      # "fast" | "deep"
    reason: str

    def as_json(self) -> dict:
        return {"target": self.target, "reason": self.reason}


def decide(text: str, *, needs_tools: bool = False) -> Route:
    if needs_tools:
        return Route("deep", "un outil doit probablement etre appele")
    if DEEP.search(text):
        return Route("deep", "marqueur de raisonnement detecte")
    if REFLEX.match(text) and len(text) < 80:
        return Route("fast", "intention reflexe")
    if len(text.split()) <= 6:
        return Route("fast", "enonce court et simple")
    return Route("deep", "par defaut : on privilegie la qualite")
