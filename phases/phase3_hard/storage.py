from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    path = Path(os.getenv("DOCUMIND_DATA_DIR", str(ROOT / "data")))
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect():
    db = sqlite3.connect(data_dir() / "state.sqlite3", timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS corpus (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL)")
    db.execute("INSERT OR IGNORE INTO corpus VALUES (1, 0)")
    db.execute("CREATE TABLE IF NOT EXISTS mutations (token TEXT PRIMARY KEY, expires REAL NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS cache (id TEXT PRIMARY KEY, scope TEXT NOT NULL, question TEXT NOT NULL, embedding TEXT NOT NULL, answer TEXT NOT NULL, sources TEXT NOT NULL, created REAL NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS queries (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)")
    db.commit()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
