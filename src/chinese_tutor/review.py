from __future__ import annotations

import logging
from typing import Iterable

from . import storage

logger = logging.getLogger(__name__)


def _format_vocab_row(row) -> str:
    parts = []
    if row["chinese"]:
        parts.append(row["chinese"])
    if row["pinyin"]:
        parts.append(f"({row['pinyin']})")
    if row["english"]:
        parts.append(f"- {row['english']}")
    return " ".join(parts) or "(blank)"


def review_loop(limit: int = 5) -> None:
    items = storage.get_vocab_for_review(limit=limit)
    if not items:
        logger.info("No vocab to review. Finish a chat first.")
        return

    logger.info("Starting quick review for %s items. Type 'q' to stop.", len(items))
    for row in items:
        print()
        print(f"[{row['id']}] {_format_vocab_row(row)}")
        if row["example"]:
            print(f"例句: {row['example']}")
        answer = input("Did you recall it? (p=pass / f=fail / q=quit): ").strip().lower()
        if answer == "q":
            break
        result = "pass" if answer in ("p", "pass", "y") else "fail"
        storage.update_vocab_result(row["id"], result)
        logger.info("Marked %s as %s", row["id"], result)


def list_vocab(limit: int = 20) -> Iterable[str]:
    rows = storage.list_vocab(limit=limit)
    for row in rows:
        yield f"{row['id']}: {_format_vocab_row(row)} | seen {row['seen_count']} | last={row['last_result'] or '-'}"
