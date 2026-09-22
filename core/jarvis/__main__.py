"""Point d'entree. `jarvis run` demarre tout ; `jarvis chat` reste au clavier."""
from __future__ import annotations

import argparse
import asyncio
import sys

from .bus import BUS, Event
from .config import CFG

QUIET = {"audio.frame", "hud.snapshot"}


def _trace(ev: Event) -> None:
    if ev.topic in QUIET:
        return
    data = {k: v for k, v in ev.data.items() if k not in ("stats",)}
    short = ", ".join(f"{k}={str(v)[:70]}" for k, v in data.items())
    print(f"  · {ev.topic:<24} {short}", file=sys.stderr)


async def cmd_run(args) -> None:
    from .daemon import Jarvis
    from .server import serve

    if args.verbose:
        BUS.subscribe("*", _trace)

    jarvis = Jarvis()
    await jarvis.boot(with_audio=not args.no_audio)
    if not args.no_audio:
        jarvis.run_background()

    print(f"\n  Jarvis est en ligne — hors-ligne, 100 % local.")
    print(f"  HUD : ws://{CFG.host}:{CFG.port}")
    print(f"  Dites « Jarvis, ... » ou Ctrl-C pour quitter.\n")
    try:
        await serve(jarvis)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await jarvis.shutdown()


async def cmd_chat(args) -> None:
    """Mode clavier : meme cerveau, meme memoire, sans micro ni voix."""
    from .daemon import Jarvis

    if args.verbose:
        BUS.subscribe("brain.route", _trace)
        BUS.subscribe("tool.call", _trace)
        BUS.subscribe("tool.result", _trace)

    jarvis = Jarvis()
    await jarvis.boot(with_audio=False)
    print("  Mode texte. Ligne vide pour quitter.\n")
    loop = asyncio.get_running_loop()
    while True:
        line = (await loop.run_in_executor(None, input, "vous  > ")).strip()
        if not line:
            break
        print("jarvis> ", end="", flush=True)
        async for sentence in jarvis.brain.respond(line, session="chat"):
            print(sentence, end=" ", flush=True)
        print("\n")


async def cmd_status(_) -> None:
    from .memory import Memory

    stats = Memory().stats()
    print(f"\n  Memoire de Jarvis — {CFG.db_path}")
    for key, value in stats.items():
        print(f"    {key:<16} {value}")
    print(f"\n  Modeles : {CFG.model_fast} (rapide) / {CFG.model_deep} (profond)")
    print(f"  Transcription : {CFG.stt_model}\n")


async def cmd_consolidate(_) -> None:
    from .brain import Brain
    from .memory import Memory
    from .memory.consolidate import consolidate
    from .tools import REGISTRY

    memory = Memory()
    result = await consolidate(memory, Brain(memory, REGISTRY))
    print(f"  {result['episodes']} episodes relus, {result['facts']} faits retenus.")


async def cmd_recall(args) -> None:
    from .memory import Memory

    for hit in Memory().recall(" ".join(args.query), k=10):
        print(f"  [{hit.score:.3f}] {hit.text}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="Jarvis — assistant local")
    parser.add_argument("-v", "--verbose", action="store_true", help="trace le bus d'evenements")
    sub = parser.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="demarre le systeme complet")
    run.add_argument("--no-audio", action="store_true", help="sans micro ni voix")
    run.set_defaults(fn=cmd_run)

    sub.add_parser("chat", help="conversation au clavier").set_defaults(fn=cmd_chat)
    sub.add_parser("status", help="etat de la memoire").set_defaults(fn=cmd_status)
    sub.add_parser("consolidate", help="force le cycle de consolidation").set_defaults(
        fn=cmd_consolidate
    )
    rec = sub.add_parser("recall", help="interroge la memoire long terme")
    rec.add_argument("query", nargs="+")
    rec.set_defaults(fn=cmd_recall)

    args = parser.parse_args()
    if not getattr(args, "fn", None):
        parser.print_help()
        return
    try:
        asyncio.run(args.fn(args))
    except KeyboardInterrupt:
        print("\n  Au revoir.")


if __name__ == "__main__":
    main()
