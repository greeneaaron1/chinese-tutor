from __future__ import annotations

import re
from typing import Dict, List

# Matches lines like: "1) 超市 (chāoshì) — grocery store — 例句：我下班后去超市买牛奶。"
VOCAB_LINE = re.compile(
    r"""
    (?P<index>\d+)\)\s*
    (?P<chinese>[^(\n—-]+?)\s*
    (?:\((?P<pinyin>[^)]+)\))?\s*
    [—-]\s*
    (?P<english>[^—\n-]+?)
    (?:\s*[—-]\s*例句：?\s*(?P<example>.+))?
    """,
    re.IGNORECASE | re.VERBOSE,
)

ENGLISH_PHRASE = re.compile(r"[A-Za-z][A-Za-z\s'\-]+")


def extract_agent_vocab_sections(text: str) -> List[Dict[str, str]]:
    """Parse structured vocab review sections from the agent transcript."""
    results: List[Dict[str, str]] = []
    for match in VOCAB_LINE.finditer(text):
        results.append(
            {
                "chinese": match.group("chinese").strip(),
                "pinyin": (match.group("pinyin") or "").strip(),
                "english": match.group("english").strip(),
                "example": (match.group("example") or "").strip(),
            }
        )
    return results


def extract_english_runs(text: str) -> List[str]:
    """Find English phrases in user utterances as fallback unknown words."""
    phrases = []
    for match in ENGLISH_PHRASE.finditer(text):
        phrase = " ".join(match.group(0).split())
        if len(phrase) < 2:
            continue
        if phrase.lower() in ("i", "the", "a"):
            continue
        phrases.append(phrase)
    return phrases


def extract_unknown_words(agent_text: str, user_text: str) -> List[Dict[str, str]]:
    """
    Combine structured vocab detections from the agent with fallback English runs from the user.
    """
    items = extract_agent_vocab_sections(agent_text)
    existing_english = {item["english"] for item in items}
    for phrase in extract_english_runs(user_text):
        if phrase in existing_english:
            continue
        items.append({"english": phrase, "chinese": "", "pinyin": "", "example": ""})
    return items


if __name__ == "__main__":
    sample_agent = (
        "快速复习一下： 1) 超市 (chāoshì) — grocery store — 例句：我下班后去超市买牛奶。 "
        "2) 睡过头 — oversleep — 例句：今天早上我睡过头了。"
    )
    sample_user = "我今天 I went to the grocery store and overslept again."
    print(extract_unknown_words(sample_agent, sample_user))
