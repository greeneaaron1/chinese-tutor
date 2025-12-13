from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Iterable, List, Optional

from .paths import get_db_path

logger = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY,
            started_at TEXT,
            ended_at TEXT,
            transcript_text TEXT,
            metadata_json TEXT
        );

        CREATE TABLE IF NOT EXISTS vocab (
            id INTEGER PRIMARY KEY,
            created_at TEXT,
            source_session_id INTEGER,
            english TEXT,
            chinese TEXT,
            pinyin TEXT,
            example TEXT,
            seen_count INTEGER DEFAULT 0,
            last_seen_at TEXT,
            last_result TEXT,
            FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_vocab_english ON vocab(english);
        CREATE INDEX IF NOT EXISTS idx_vocab_created_at ON vocab(created_at);
        CREATE INDEX IF NOT EXISTS idx_vocab_last_seen_at ON vocab(last_seen_at);
        """
    )
    conn.commit()


def record_session(
    started_at: datetime,
    ended_at: datetime,
    transcript_text: str,
    metadata: Optional[dict] = None,
) -> int:
    conn = _connect()
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False) if metadata else None
    with conn:
        cur = conn.execute(
            """
            INSERT INTO sessions (started_at, ended_at, transcript_text, metadata_json)
            VALUES (?, ?, ?, ?)
            """,
            (started_at.isoformat(), ended_at.isoformat(), transcript_text, metadata_json),
        )
        session_id = cur.lastrowid
    conn.close()
    return session_id


def insert_vocab_items(
    items: Iterable[dict],
    source_session_id: Optional[int],
) -> List[int]:
    now = datetime.now().isoformat()
    conn = _connect()
    ids: List[int] = []
    seen_pairs = set()
    with conn:
        for item in items:
            key = (item.get("english") or "", item.get("chinese") or "")
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            cur = conn.execute(
                """
                INSERT INTO vocab (
                    created_at, source_session_id, english, chinese, pinyin, example
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    source_session_id,
                    item.get("english", "") or "",
                    item.get("chinese", "") or "",
                    item.get("pinyin", "") or "",
                    item.get("example", "") or "",
                ),
            )
            ids.append(cur.lastrowid)
    conn.close()
    return ids


def list_sessions(limit: int = 10) -> List[sqlite3.Row]:
    conn = _connect()
    cur = conn.execute(
        """
        SELECT id, started_at, ended_at, substr(transcript_text, 1, 120) AS snippet
        FROM sessions
        ORDER BY datetime(started_at) DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def list_vocab(limit: int = 20) -> List[sqlite3.Row]:
    conn = _connect()
    cur = conn.execute(
        """
        SELECT id, english, chinese, pinyin, example, seen_count, last_result, last_seen_at, created_at
        FROM vocab
        ORDER BY datetime(created_at) DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_vocab_for_review(limit: int = 5) -> List[sqlite3.Row]:
    conn = _connect()
    cur = conn.execute(
        """
        SELECT id, english, chinese, pinyin, example, seen_count, last_result, last_seen_at
        FROM vocab
        ORDER BY
            CASE WHEN last_result = 'fail' THEN 0 ELSE 1 END,
            CASE WHEN last_seen_at IS NULL THEN 0 ELSE 1 END,
            datetime(last_seen_at) ASC,
            datetime(created_at) ASC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def update_vocab_result(vocab_id: int, result: str) -> None:
    now = datetime.now().isoformat()
    conn = _connect()
    with conn:
        conn.execute(
            """
            UPDATE vocab
            SET seen_count = seen_count + 1,
                last_seen_at = ?,
                last_result = ?
            WHERE id = ?
            """,
            (now, result, vocab_id),
        )
    conn.close()
