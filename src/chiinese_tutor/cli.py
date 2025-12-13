from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Callable

from dotenv import load_dotenv

from . import extract, storage
from .elevenlabs_client import run_conversation
from .review import list_vocab, review_loop

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


def cmd_review(args: argparse.Namespace) -> None:
    review_loop(limit=args.limit)


def cmd_list(args: argparse.Namespace) -> None:
    print("Recent sessions:")
    for row in storage.list_sessions(limit=args.limit):
        print(f"- #{row['id']} {row['started_at']} -> {row['ended_at']}: {row['snippet']}")
    print("\nRecent vocab:")
    for line in list_vocab(limit=args.limit):
        print(f"- {line}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="chinese-tutor CLI")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    chat = sub.add_parser("chat", help="Start a voice chat with the agent")
    chat.set_defaults(func=cmd_chat)

    review = sub.add_parser("review", help="Review unknown words")
    review.add_argument("--limit", type=int, default=5, help="Number of items to quiz")
    review.set_defaults(func=cmd_review)

    listing = sub.add_parser("list", help="List recent sessions and vocab")
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
