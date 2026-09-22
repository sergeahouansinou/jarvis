"""Schema SQLite des quatre couches de memoire.

  episodes  : journal append-only, immuable, horodate  -> memoire episodique
  facts     : connaissances extraites + vecteur         -> memoire semantique
  entities  : noeuds du graphe (personne, projet, lieu)
  relations : aretes du graphe
Le contexte courant (memoire de travail) est volatile et ne vit qu'en RAM.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS episodes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL    NOT NULL,
    session   TEXT    NOT NULL,
    role      TEXT    NOT NULL,          -- user | jarvis | system | tool
    content   TEXT    NOT NULL,
    meta      TEXT    DEFAULT '{}',
    consolidated INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ep_ts    ON episodes(ts DESC);
CREATE INDEX IF NOT EXISTS idx_ep_todo  ON episodes(consolidated, ts);

CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts
    USING fts5(content, content='episodes', content_rowid='id', tokenize='unicode61');

CREATE TRIGGER IF NOT EXISTS ep_ai AFTER INSERT ON episodes BEGIN
    INSERT INTO episodes_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    text        TEXT    NOT NULL UNIQUE,
    kind        TEXT    NOT NULL DEFAULT 'fact',   -- fact | preference | goal | skill
    importance  REAL    NOT NULL DEFAULT 0.5,      -- 0..1, note par le LLM
    last_used   REAL    NOT NULL DEFAULT 0,
    hits        INTEGER NOT NULL DEFAULT 0,
    source_ep   INTEGER REFERENCES episodes(id) ON DELETE SET NULL,
    vector      BLOB
);
CREATE INDEX IF NOT EXISTS idx_fact_imp ON facts(importance DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
    USING fts5(text, content='facts', content_rowid='id', tokenize='unicode61');

CREATE TRIGGER IF NOT EXISTS fact_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS fact_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TABLE IF NOT EXISTS entities (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL,
    kind    TEXT NOT NULL DEFAULT 'thing',   -- person | project | place | device | thing
    attrs   TEXT NOT NULL DEFAULT '{}',
    ts      REAL NOT NULL,
    UNIQUE(name, kind)
);

CREATE TABLE IF NOT EXISTS relations (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    src     INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    verb    TEXT    NOT NULL,
    dst     INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    weight  REAL    NOT NULL DEFAULT 1.0,
    ts      REAL    NOT NULL,
    UNIQUE(src, verb, dst)
);
CREATE INDEX IF NOT EXISTS idx_rel_src ON relations(src);
CREATE INDEX IF NOT EXISTS idx_rel_dst ON relations(dst);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.commit()
    return con


def now() -> float:
    return time.time()
