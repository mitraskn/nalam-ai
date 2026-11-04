"""Scheme guide — Information about health insurance and assistance schemes.

No eligibility verdict; just information with URLs. All text from schemes_and_labels.json.
"""
from pathlib import Path
import json


def _load_schemes_and_labels() -> dict:
    """Load schemes and labels from JSON."""
    path = Path(__file__).parent / "data" / "schemes_and_labels.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"schemes": [], "footer": {}}


def get_scheme_guide() -> dict:
    """Get health scheme guide (Tamil + English).
    
    Returns:
    {
        "schemes": [
            {
                "name_en": "",
                "name_ta": "",
                "about_en": "",
                "about_ta": "",
                "url": ""
            },
            ...
        ],
        "disclaimer_en": "",
        "disclaimer_ta": ""
    }
    """
    data = _load_schemes_and_labels()
    footer = data.get("footer", {})
    
    return {
        "schemes": data.get("schemes", []),
        "disclaimer_en": footer.get("disclaimer_en", ""),
        "disclaimer_ta": footer.get("disclaimer_ta", "")
    }
