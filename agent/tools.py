"""Skeleton tools. Read-only, curated sources only."""
import json
import re
from functools import lru_cache
from pathlib import Path

from strands import tool

DATA = Path(__file__).parent / "data"
TAMIL = re.compile(r"[\u0B80-\u0BFF]")


@lru_cache(maxsize=1)
def guidance():
    return json.loads((DATA / "guidance.json").read_text(encoding="utf-8"))


def guidance_ids():
    return {g["id"] for g in guidance()["items"]}


def language_of(text):
    return "ta" if TAMIL.search(text or "") else "en"


def has_tamil(text):
    return bool(TAMIL.search(text or ""))


@tool
def lookup_guidance(topic: str) -> list[dict]:
    """Find curated, dated guidance to cite. Returns items with id and text.

    Args:
        topic: words to match
    """
    words = [w for w in re.findall(r"\w+", topic.lower()) if len(w) > 2]
    items = guidance()["items"]
    hits = [g for g in items if any(w in (g["id"] + " " + g["text"]).lower() for w in words)]
    return [{"id": g["id"], "text": g["text"]} for g in (hits or items)[:6]]
