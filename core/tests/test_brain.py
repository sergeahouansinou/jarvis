"""Tests du chemin critique : interception de balise, appel d'outil, decoupe
en phrases. On substitue un faux modele pour ne dependre d'aucun telechargement.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.brain import _TagFilter, _parse_call, TOOL_OPEN, TOOL_CLOSE


def test_tag_filter_laisse_passer_le_texte():
    f = _TagFilter(TOOL_OPEN)
    out, hit = f.feed("Bonjour, il est midi.")
    assert out == "Bonjour, il est midi." and not hit


def test_tag_filter_retient_un_prefixe_ambigu():
    """« <ou » pourrait devenir « <outil> » : on ne doit rien diffuser encore."""
    f = _TagFilter(TOOL_OPEN)
    out, hit = f.feed("Je regarde <ou")
    assert out == "Je regarde " and not hit
    out, hit = f.feed("til>{\"name\": \"get_time\"}")
    assert hit and out == ""


def test_tag_filter_ne_coupe_pas_un_chevron_anodin():
    f = _TagFilter(TOOL_OPEN)
    out, _ = f.feed("5 < 7 donc oui.")
    assert out == "5 < 7 donc oui."


def test_parse_call_tolere_le_bavardage_apres_la_balise():
    body = f'{TOOL_OPEN}{{"name": "get_time", "arguments": {{}}}}{TOOL_CLOSE} et voila'
    assert _parse_call(body) == ("get_time", {})


def test_parse_call_sans_balise_fermante():
    """Le modele s'arrete parfois avant de fermer : on doit quand meme lire."""
    body = f'{TOOL_OPEN}{{"name": "search_memory", "arguments": {{"query": "flutter"}}}}'
    assert _parse_call(body) == ("search_memory", {"query": "flutter"})


def test_parse_call_json_invalide_renvoie_none():
    assert _parse_call(f'{TOOL_OPEN}pas du json{TOOL_CLOSE}') is None


def test_parse_call_accepte_input_comme_alias():
    body = f'{TOOL_OPEN}{{"name": "get_time", "input": {{}}}}{TOOL_CLOSE}'
    assert _parse_call(body) == ("get_time", {})


# --------------------------------------------------------------- integration

async def _scenario():
    """Un tour complet : le modele appelle un outil, puis repond."""
    from jarvis import brain as brain_mod
    from jarvis.memory import Memory
    from jarvis.tools import REGISTRY, builtin

    scripted = [
        # 1er appel : le modele decide d'utiliser un outil
        ['Un instant. ', '<out', 'il>{"name": "get_time", ', '"arguments": {}}', '</outil>'],
        # 2e appel : il formule la reponse a partir du resultat
        ["Il est ", "midi pile. ", "Autre chose ?"],
    ]
    calls = {"n": 0}

    async def fake_stream(role, system, messages, max_tokens=256):
        chunks = scripted[min(calls["n"], len(scripted) - 1)]
        calls["n"] += 1
        for c in chunks:
            yield c

    async def fake_load(role):
        return True

    brain_mod.local.stream = fake_stream
    brain_mod.local.load = fake_load

    memory = Memory(path=Path("/tmp/jarvis-test.db"))
    builtin.bind(memory)
    b = brain_mod.Brain(memory, REGISTRY)

    sentences = [s async for s in b.respond("quelle heure est-il donc maintenant ?")]
    return sentences, calls["n"]


def test_boucle_outil_complete():
    sentences, rounds = asyncio.run(_scenario())
    joined = " ".join(sentences)

    assert rounds == 2, "le modele doit etre rappele apres le resultat de l'outil"
    assert "<outil>" not in joined, "la balise ne doit jamais etre prononcee"
    assert "get_time" not in joined
    assert "Un instant." in joined
    assert "Il est midi pile." in joined
    assert len(sentences) >= 2, "la reponse doit sortir phrase par phrase"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"  ECHEC {fn.__name__} : {exc}")
    print(f"\n  {len(fns) - failures}/{len(fns)} tests passes")
    sys.exit(1 if failures else 0)
