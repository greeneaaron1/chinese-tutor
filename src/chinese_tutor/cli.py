from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Callable

from dotenv import load_dotenv

from . import extract, storage
from .elevenlabs_client import run_conversation

LOG_FORMAT = "%(message)s"
logger = logging.getLogger(__name__)


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=LOG_FORMAT)


def cmd_chat(args: argparse.Namespace) -> None:
    agent_id = os.environ.get("AGENT_ID")
    api_key = os.environ.get("ELEVENLABS_API_KEY")

    if not agent_id:
        logger.error("AGENT_ID is required. Set it in the environment or .env file.")
        sys.exit(1)

    logger.info("Starting chat. Press Ctrl+C to stop.")
    try:
        result = run_conversation(agent_id=agent_id, api_key=api_key)
    except Exception as exc:  # noqa: BLE001
        logger.error("Conversation failed: %s", exc)
        sys.exit(1)

    session_id = storage.record_session(
        started_at=result.started_at,
        ended_at=result.ended_at,
        transcript_text=result.transcript_text,
        metadata=result.metadata,
    )
    logger.info("Saved session %s", session_id)

    vocab_items = extract.extract_unknown_words(
        agent_text=result.agent_text,
        user_text=result.user_text,
    )
    if vocab_items:
        ids = storage.insert_vocab_items(vocab_items, source_session_id=session_id)
        logger.info("Captured %s vocab items", len(ids))
    else:
        logger.info("No vocab candidates detected.")


def _format_vocab_row(row) -> str:
    parts = []
    if row["chinese"]:
        parts.append(row["chinese"])
    if row["pinyin"]:
        parts.append(f"({row['pinyin']})")
    if row["english"]:
        parts.append(f"- {row['english']}")
    if row["example"]:
        parts.append(f"例句: {row['example']}")
    return " ".join(parts) or "(blank)"


def cmd_list(args: argparse.Namespace) -> None:
    rows = storage.list_vocab(limit=args.limit)
    if not rows:
        print("No vocabulary captured yet. Run `chat` first.")
        return
    print("Vocabulary (newest first):")
    for row in rows:
        print(f"- {_format_vocab_row(row)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="chinese-tutor CLI")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    chat = sub.add_parser("chat", help="Start a voice chat with the agent")
    chat.set_defaults(func=cmd_chat)

    listing = sub.add_parser("list", help="List captured vocabulary")
    listing.add_argument("--limit", type=int, default=10, help="Number of items to list")
    listing.set_defaults(func=cmd_list)
    return parser


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    func: Callable[[argparse.Namespace], None] = args.func
    func(args)


if __name__ == "__main__":
    main()
