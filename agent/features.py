"""Part 7c features: word bridge, myth buster, tips, care finder, prescription reader.

All text comes from JSON files in agent/data/. The model never generates medical verdicts,
advice, or interpretations. All labels loaded from schemes_and_labels.json.
"""
import json
from datetime import datetime
from pathlib import Path
import re


def _load_json(filename: str) -> dict:
    """Load JSON from agent/data/."""
    path = Path(__file__).parent / "data" / filename
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


# Load data files once
_GLOSSARY = _load_json("lab_glossary.json")
_ABBREVIATIONS = _load_json("med_abbreviations.json")
_MYTHS = _load_json("myths.json")
_TIPS = _load_json("health_tips.json")
_CARE = _load_json("care_places.json")
_LABELS = _load_json("schemes_and_labels.json").get("labels", {})


def word_bridge(term: str) -> dict:
    """Look up a term in abbreviations and glossary. Return {en, ta, found}."""
    term_lower = term.lower()
    
    # Check abbreviations first
    for item in _ABBREVIATIONS.get("items", []):
        if item.get("abbr", "").lower() == term_lower:
            return {
                "term": term,
                "type": "abbreviation",
                "en": item.get("en", ""),
                "ta": item.get("ta", ""),
                "found": True
            }
        # Check alts
        for alt in item.get("alt", []):
            if alt.lower() == term_lower:
                return {
                    "term": term,
                    "type": "abbreviation",
                    "en": item.get("en", ""),
                    "ta": item.get("ta", ""),
                    "abbr": item.get("abbr", ""),
                    "found": True
                }
    
    # Check glossary aliases
    for test in _GLOSSARY.get("tests", []):
        for alias in test.get("aliases", []):
            if alias.lower() == term_lower:
                return {
                    "term": term,
                    "type": "test",
                    "en": test.get("en", ""),
                    "ta": test.get("ta", ""),
                    "found": True
                }
    
    # Not found
    return {
        "term": term,
        "found": False,
        "en": f"I don't have a definition for '{term}'. Ask your doctor.",
        "ta": f"'{term}' என்பதற்கான விளக்கம் எனிடம் இல்லை. மருத்துவரிடம் கேளுங்கள்."
    }


def myth_buster(question: str) -> dict:
    """Match question to a myth. Return {myth_en, myth_ta, verdict, en, ta, found}."""
    q_lower = question.lower()
    
    for item in _MYTHS.get("items", []):
        # Check if any key matches in the question (substring match, case-insensitive)
        for key in item.get("keys", []):
            if key.lower() in q_lower:
                return {
                    "question": question,
                    "myth_en": item.get("myth_en", ""),
                    "myth_ta": item.get("myth_ta", ""),
                    "verdict": item.get("verdict", ""),
                    "en": item.get("en", ""),
                    "ta": item.get("ta", ""),
                    "found": True
                }
    
    # No match
    return {
        "question": question,
        "found": False,
        "en": "I don't have a checked answer for this. Please ask your doctor.",
        "ta": "இந்தக் கேள்விக்கு எனிடம் சரிபார்க்கப்பட்ட பதில் இல்லை. மருத்துவரிடம் கேளுங்கள்."
    }


def tip_of_the_day() -> dict:
    """Get health tip for today (rotate by day of year)."""
    items = _TIPS.get("items", [])
    if not items:
        return {"en": "", "ta": ""}
    
    # Rotate by day of year
    day_of_year = datetime.now().timetuple().tm_yday
    index = (day_of_year - 1) % len(items)
    return items[index]


def care_finder() -> dict:
    """Get care finder info (emergency + places + near-me links)."""
    return {
        "emergency": _CARE.get("emergency", []),
        "places": _CARE.get("places", []),
        "near_me": _CARE.get("near_me", [])
    }
