# J.A.R.V.I.S.

Assistant personnel **entièrement local**. Aucune clé API, aucun appel réseau,
aucun coût à l'usage. Voix, mémoire persistante, outils, HUD natif.

Conçu pour Apple Silicon : l'inférence passe par MLX, qui exploite Metal et la
mémoire unifiée — c'est ce qui rend le tout-local viable sur 16 Go.

```
micro ─► VAD ─► Whisper ─┐
                          ├─► ORCHESTRATEUR ─► TTS ─► haut-parleur
       HUD / clavier ────┘       ↕ outils
                                 ↕ MÉMOIRE (4 couches)
```

## Ce qui tourne vraiment

| Brique | Implémentation | Repli si absent |
|---|---|---|
| Capture micro | `sounddevice`, callback temps réel | — |
| Détection de parole | énergie + plancher de bruit adaptatif | — |
| Mot-déclencheur | openWakeWord (`--extra wake`) | filtrage du nom après transcription |
| Transcription | `mlx-whisper` large-v3-turbo, Metal | — |
| Cerveau rapide | Qwen3-4B 4-bit (MLX), ~2,5 Go | — |
| Cerveau profond | Qwen3-8B 4-bit (MLX), ~4,5 Go | — |
| Embeddings | `mlx-embeddings` MiniLM multilingue | hachage de n-grammes |
| Synthèse vocale | Kokoro ONNX (`--extra voice`) | `say` de macOS |
| Mémoire | SQLite (WAL) + FTS5 + vecteurs | — |
| HUD | Tauri 2 + WebGL (three.js) | n'importe quel navigateur |

## Démarrage

```bash
cd core && uv venv --python 3.13 && uv pip install -e .
```

```bash
cd core && .venv/bin/jarvis chat
```

Le premier lancement télécharge les modèles (~8 Go au total, une seule fois).
`chat` est le mode clavier : même cerveau, même mémoire, sans micro ni voix —
c'est le moyen le plus rapide de vérifier que tout répond.

Système complet, avec voix et HUD :

```bash
cd core && .venv/bin/jarvis run -v
```

```bash
cd hud && npm install && npm run tauri dev
```

## Commandes

| Commande | Effet |
|---|---|
| `jarvis run` | système complet (micro, voix, serveur du HUD) |
| `jarvis run --no-audio` | noyau + HUD seuls, sans micro |
| `jarvis chat` | conversation au clavier |
| `jarvis status` | état de la mémoire et des modèles |
| `jarvis recall <requête>` | interroge la mémoire long terme |
| `jarvis consolidate` | force un cycle de consolidation |

Dans le HUD : `Entrée` envoie, `Échap` interrompt la parole.

## Architecture

Voir [docs/architecture.md](docs/architecture.md) pour le détail des quatre
couches de mémoire, du budget de latence et des points de montée en qualité.

Le principe structurant : **rien ne connaît le HUD**. Toutes les briques
publient sur un bus d'événements (`core/jarvis/bus.py`) et le HUD n'est qu'un
abonné parmi d'autres. On peut le fermer, le redémarrer ou le remplacer sans
que le noyau s'en aperçoive.

## Vie privée

Tout reste sur la machine. Le serveur écoute sur `127.0.0.1` uniquement, la
base SQLite vit dans `data/`, et aucun modèle n'émet de requête après son
téléchargement initial. Pour tout effacer : `rm data/jarvis.db*`.
