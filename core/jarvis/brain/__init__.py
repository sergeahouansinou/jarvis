"""Le cerveau : routage, boucle d'agent, appel d'outils -- tout en local.

Un tour de parole suit toujours le meme chemin :
  rappel memoire -> routage -> generation en streaming -> outils -> memorisation

L'appel d'outils n'utilise pas le protocole d'une API distante : le modele
local ecrit une balise <outil>{...}</outil> que l'on intercepte au vol. C'est
independant du modele choisi, et la balise n'est jamais prononcee a voix haute.
"""
from __future__ import annotations

import json
import re
from typing import AsyncIterator

from ..bus import BUS
from ..config import CFG
from . import local
from .router import decide

TOOL_OPEN, TOOL_CLOSE = "<outil>", "</outil>"

SYSTEM = """Tu es Jarvis, l'assistant personnel de l'utilisateur.

Ton: sobre, precis, courtois, un soupcon d'ironie seche. Tu vouvoies.
Tu reponds a l'oral : phrases courtes, pas de listes a puces, pas de markdown,
pas d'emoji, pas de balises. Jamais plus de trois phrases, sauf si on te
demande explicitement de developper.
Si tu ne sais pas, tu le dis. Tu n'inventes jamais un souvenir : ce que tu sais
de l'utilisateur figure dans le bloc memoire, rien d'autre."""

TOOLS_RULE = """

Tu disposes d'outils. Pour en appeler un, ecris EXACTEMENT ceci et rien d'autre :
<outil>{{"name": "nom_outil", "arguments": {{...}}}}</outil>
Tu recevras le resultat, puis tu repondras a l'utilisateur en une phrase ou deux.
N'appelle un outil que s'il est reellement necessaire. Outils disponibles :
{tools}"""

_SENTENCE = re.compile(r"(?<=[.!?…:])\s+|\n+")


class _TagFilter:
    """Laisse passer le texte, retient tout ce qui pourrait devenir une balise."""

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.held = ""

    def feed(self, chunk: str) -> tuple[str, bool]:
        """Renvoie (texte diffusable, balise_ouverte)."""
        self.held += chunk
        if self.tag in self.held:
            return self.held.split(self.tag, 1)[0], True
        # on retient la plus longue fin qui pourrait amorcer la balise
        keep = 0
        for n in range(min(len(self.tag) - 1, len(self.held)), 0, -1):
            if self.held.endswith(self.tag[:n]):
                keep = n
                break
        out, self.held = self.held[: len(self.held) - keep], self.held[len(self.held) - keep :]
        return out, False


class Brain:
    def __init__(self, memory, tools) -> None:
        self.memory = memory
        self.tools = tools

    async def boot(self) -> dict:
        ok_fast = await local.load("fast")
        state = {
            "fast": ok_fast, "deep": local.loaded("deep"),
            "model_fast": CFG.model_fast, "model_deep": CFG.model_deep, "offline": True,
        }
        await BUS.emit("brain.ready", **state)
        return state

    # ------------------------------------------------------------------ public
    async def complete(self, system: str, messages: list[dict], max_tokens: int = 2048, **_) -> str:
        """Appel bloquant pour les taches de fond (consolidation, resumes)."""
        return await local.complete("deep", system, messages, max_tokens)

    async def respond(self, user_text: str, session: str = "default") -> AsyncIterator[str]:
        """Genere la reponse a un tour de parole, phrase par phrase."""
        await self.memory.remember("user", user_text, session=session)

        context = self.memory.context_block(user_text)
        route = decide(user_text, needs_tools=self.tools.might_be_needed(user_text))
        await BUS.emit("brain.route", text=user_text, **route.as_json())

        system = SYSTEM
        if context:
            system += f"\n\n--- memoire ---\n{context}"
        if route.target == "deep" and len(self.tools):
            system += TOOLS_RULE.format(tools=self.tools.describe())

        history = [
            {"role": "user" if t.role == "user" else "assistant", "content": t.content}
            for t in list(self.memory.working)[-8:]
        ] or [{"role": "user", "content": user_text}]

        buffer, full = "", []
        async for piece in self._generate(route.target, system, history):
            buffer += piece
            full.append(piece)
            while (m := _SENTENCE.search(buffer)):
                sentence, buffer = buffer[: m.end()].strip(), buffer[m.end() :]
                if sentence:
                    yield sentence
        if buffer.strip():
            yield buffer.strip()

        reply = "".join(full).strip()
        if reply:
            await self.memory.remember("jarvis", reply, session=session, route=route.target)

    # ----------------------------------------------------------------- interne
    async def _generate(self, role: str, system: str, history: list[dict]) -> AsyncIterator[str]:
        messages = list(history)
        max_tokens = 200 if role == "fast" else 512

        for _ in range(3):  # au plus 3 allers-retours d'outils par tour
            filt = _TagFilter(TOOL_OPEN)
            raw, hit = [], False

            async for chunk in local.stream(role, system, messages, max_tokens):
                raw.append(chunk)
                text, opened = filt.feed(chunk)
                if text:
                    yield text
                if opened:
                    hit = True
                    break

            body = "".join(raw)
            if not hit and TOOL_OPEN not in body:
                if filt.held:
                    yield filt.held
                return

            call = _parse_call(body)
            if call is None:
                return

            name, args = call
            await BUS.emit("tool.call", name=name, input=args)
            out, is_error = await self.tools.run(name, args)
            await BUS.emit("tool.result", name=name, output=out[:500], error=is_error)

            messages = messages + [
                {"role": "assistant", "content": f"{TOOL_OPEN}{json.dumps(call[1])}{TOOL_CLOSE}"},
                {"role": "user", "content": f"Resultat de {name} :\n{out}\n\n"
                                            "Reponds maintenant a l'utilisateur, brievement."},
            ]
            role = "deep"


def _parse_call(body: str) -> tuple[str, dict] | None:
    start = body.find(TOOL_OPEN)
    if start == -1:
        return None
    rest = body[start + len(TOOL_OPEN) :]
    end = rest.find(TOOL_CLOSE)
    blob = (rest[:end] if end != -1 else rest).strip()
    depth, cut = 0, None
    for i, ch in enumerate(blob):          # on s'arrete au JSON complet
        depth += (ch == "{") - (ch == "}")
        if depth == 0 and ch == "}":
            cut = i + 1
            break
    try:
        data = json.loads(blob[:cut] if cut else blob)
    except json.JSONDecodeError:
        return None
    name = data.get("name")
    args = data.get("arguments") or data.get("input") or {}
    return (name, args) if isinstance(name, str) and isinstance(args, dict) else None
