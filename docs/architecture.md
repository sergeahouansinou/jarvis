# Architecture

## Le principe

Jarvis n'est pas « un LLM avec un micro ». Le modèle de langage est la pièce
la plus remplaçable du système. Ce qui fait Jarvis, c'est **la boucle temps
réel** et **la mémoire** — les deux choses qu'un appel d'API ne fournit pas.

Tout le reste découle de deux décisions :

1. **Un bus d'événements au centre.** Aucune brique n'en connaît une autre.
   L'audio publie, le cerveau publie, la mémoire publie ; le HUD écoute. On
   ajoute une sortie (journal, notification, domotique) sans toucher au noyau.
2. **Le streaming partout.** Rien n'attend la fin de l'étape précédente. La
   synthèse vocale commence à parler dès la première phrase, pendant que le
   modèle écrit encore la suivante. C'est la seule façon de descendre sous la
   seconde de latence perçue.

## Budget de latence

Cible : moins de 800 ms entre la fin de votre phrase et le premier son.

| Étage              | Cible       | Ce qui le détermine                                                  |
| ------------------- | ----------- | --------------------------------------------------------------------- |
| Fin de parole (VAD) | 100–200 ms | `silence_ms` dans la config — le levier le plus direct             |
| Transcription       | 100–250 ms | taille du modèle Whisper, durée de l'énoncé                       |
| Premier token       | 150–400 ms | taille du modèle, longueur du prompt (donc de la mémoire injectée) |
| Premier audio       | 80–150 ms  | `say` est quasi instantané, Kokoro ~120 ms                         |

Le HUD affiche le temps réel du premier token à chaque tour. Si la latence
dérive, c'est presque toujours le bloc mémoire injecté qui a grossi.

## Les quatre couches de mémoire

C'est le cœur du système. Une couche seule ne suffit pas : un journal brut
devient illisible, des vecteurs seuls perdent la chronologie, un graphe seul
ne retient pas les nuances.

### 1. Mémoire de travail — `Memory.working`

Les derniers tours de parole, en RAM, volatile. Rien à persister.

### 2. Mémoire épisodique — table `episodes`

Journal **append-only** de tout ce qui s'est dit, horodaté. Immuable : c'est la
vérité de référence. Indexé en FTS5 pour la recherche lexicale.

On écrit toujours ici en premier. Tout le reste en est dérivé, jamais l'inverse.

### 3. Mémoire sémantique — table `facts`

Des faits extraits des épisodes, vectorisés, notés en importance. Un fait est
autonome : « L'utilisateur développe en Flutter » et non « il m'a dit ça hier ».

### 4. Mémoire graphe — tables `entities` / `relations`

Les entités et leurs liens. C'est ce qui permet de répondre à « qui travaillait
avec moi sur ce projet », auquel ni les vecteurs ni le texte plein ne savent
répondre.

## Les deux mécanismes qu'on oublie toujours

### La consolidation — `memory/consolidate.py`

Toutes les 15 minutes, quand Jarvis est oisif, le modèle profond relit les
épisodes non traités, en extrait les faits durables, note leur importance et
met à jour le graphe. C'est le **sommeil** du système.

Sans cette étape, la mémoire n'est qu'un log qui gonfle. Avec elle, elle se
densifie : 200 tours de conversation deviennent 15 faits utiles.

### Le scoring de rappel — `memory/recall.py`

```
score = pertinence × (0,35 + 0,65 × fraîcheur) × (0,35 + 0,65 × importance)
```

- **pertinence** : fusion RRF entre recherche vectorielle et BM25 ;
- **fraîcheur** : décroissance exponentielle, demi-vie 72 h ;
- **importance** : notée par le modèle à la consolidation.

Un plancher de pertinence écarte les souvenirs hors sujet : sans lui, une base
de quatre faits les renvoie tous les quatre et le prompt se remplit de bruit.

L'approche suit l'esprit des *Generative Agents* (Stanford, 2023) : on ne
remonte pas ce qui ressemble le plus, on remonte ce qui compte le plus
**maintenant**.

## Routage rapide / profond

Le réflexe reste sur le 4B (~200 ms), la réflexion mobilise le 8B. Les règles
sont dans `brain/router.py` et chaque décision est publiée sur le bus — si le
routage se trompe souvent, le HUD le montre et la regex se corrige en une ligne.

## Appel d'outils sans API

Les API distantes offrent un protocole d'appel d'outils ; un modèle local, non.
Jarvis utilise donc un protocole explicite : le modèle écrit
`<outil>{"name": ..., "arguments": {...}}</outil>`, et `_TagFilter` intercepte
la balise **pendant** le streaming — elle n'est jamais prononcée à voix haute.

C'est indépendant du modèle choisi : changer de LLM ne casse rien.

## Points de montée en qualité

Par ordre de retour sur effort :

1. **VAD Silero** à la place de la détection par énergie. Le gain est
   immédiat en environnement bruyant — c'est la brique la plus isolée du
   système, elle se remplace en une trentaine de lignes.
2. **Kokoro** à la place de `say`. La voix de macOS fonctionne mais s'entend.
3. **Modèle profond plus gros** si vous avez plus de 16 Go : Qwen3-14B 4-bit
   change nettement la qualité du raisonnement et de la consolidation.
4. **Noyau audio en Rust.** Seulement quand le reste sera stable : la capture,
   le ring buffer et le VAD sont le seul chemin où Python coûte vraiment
   quelque chose. Commencer par là fait perdre des mois.
