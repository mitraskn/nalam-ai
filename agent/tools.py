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
    stop = {"the", "and", "for", "how", "can", "what", "with", "keep", "my", "your", "about"}
    words = [w for w in re.findall(r"\w+", topic.lower()) if len(w) > 2 and w not in stop]
    if "bp" in topic.lower().split():
        words += ["blood", "pressure"]
    # Tamil / Tanglish words -> the English words the guidance uses
    TA = {"சர்க்கரை": ["sugar", "diabetes"], "சுகர்": ["sugar", "diabetes"], "sugar": ["diabetes"], "இரத்த அழுத்த": ["blood", "pressure"],
          "ரத்த அழுத்த": ["blood", "pressure"], "பிபி": ["blood", "pressure"], "கொலஸ்ட்ரால்": ["cholesterol"], "தைராய்டு": ["thyroid"],
          "மாத்திரை": ["medicine"], "உணவு": ["food", "diet"], "சாப்பா": ["food", "diet"], "நடை": ["walking", "active"],
          "உடற்பயிற்சி": ["active", "exercise"], "கட்டுப்பா": ["care"], "முட்டி": ["knee", "joint"], "மூட்டு": ["joint"]}
    for k, v in TA.items():
        if k in topic.lower():
            words += v
    items = guidance()["items"]
    # rank by how many topic words each item contains, so the best matches come first
    def score(g):
        sc = sum(w in (g["id"] + " " + g["text"]).lower() for w in words)
        # lifestyle / care advice (WHO, MedlinePlus) first when it matches at all
        return sc + (1.5 if sc and g["id"].startswith(("LIFE-", "TIP-")) else 0)
    scored = sorted(((score(g), n, g) for n, g in enumerate(items)),
                    key=lambda x: (-x[0], x[1]))
    hits = [g for sc, _, g in scored if sc > 0]
    return [{"id": g["id"], "text": g["text"]} for g in (hits or items)[:8]]
