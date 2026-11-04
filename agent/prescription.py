"""Prescription reader (Part 7c) — Extract and explain medicines from images.

Like report.py, Nova extracts text only; explanations come from med_abbreviations.json.
The model never suggests medicine changes or diagnoses.
"""
import json
import re
from pathlib import Path
import boto3
import os


def _load_abbreviations() -> dict:
    """Load medical abbreviations."""
    path = Path(__file__).parent / "data" / "med_abbreviations.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"items": []}


ABBREVIATIONS = _load_abbreviations()


def read_prescription_via_nova(image_bytes: bytes, path_str: str) -> list[dict]:
    """Send prescription image to Bedrock Nova. Extract medicine rows.
    
    Returns list of:
    {
        "medicine_name": str,
        "dose_text": str,
        "frequency_text": str,
        "duration_text": str,
        "food_text": str,
        "legible": bool
    }
    
    Uses boto3 converse API (same as report.py).
    """
    region = os.environ.get("BEDROCK_REGION") or os.environ.get("AWS_REGION", "us-east-1")
    # Handwriting needs the stronger vision model; fall back to Nova Lite if Pro is not enabled on the account.
    model_id = os.environ.get("RX_MODEL", "us.amazon.nova-pro-v1:0")
    fallback_id = os.environ.get("REPORT_MODEL", "us.amazon.nova-lite-v1:0")
    
    # Determine content type
    ext = path_str.lower().rsplit(".", 1)[-1]
    
    if ext == "pdf":
        block = {"document": {"format": "pdf", "name": "rx", "source": {"bytes": image_bytes}}}
    else:
        block = {"image": {"format": "jpeg" if ext in ("jpg", "jpeg") else ext, "source": {"bytes": image_bytes}}}
    
    prompt = (
        "You are reading a doctor's prescription from India. It may be printed or HANDWRITTEN. Read it carefully, line by line. "
        "Common notation: 'T.' or 'Tab' = tablet, 'Cap' = capsule, 'Syp' = syrup, 'Inj' = injection, 'NS' = nasal spray; "
        "frequency is often written like 1-0-1 or 0-0-1 (morning-afternoon-night), or OD, BD, TDS, HS, SOS; "
        "a circled or underlined number near a line is usually the number of days (e.g. 5 -> '5 days'); "
        "'AC' = before food, 'PC' = after food. Lines like 'IgE 288.5 (150)' or 'AEC 410 (440)' are test results, NOT medicines: skip them. "
        "Return ONLY a JSON array, no other text. One object per MEDICINE line: "
        '{"medicine_name": the name exactly as written (best reading), "dose_text": dose if written, '
        '"frequency_text": frequency as written (e.g. "0-0-1"), "duration_text": duration (e.g. "5 days"), '
        '"food_text": food instruction if written, '
        '"legible": true ONLY if you are sure of the medicine name; false if the handwriting is unclear}. '
        "Never invent a medicine name. If a field is not written, use an empty string."
    )

    client = boto3.client("bedrock-runtime", region_name=region)
    
    def ask(mid):
        return client.converse(modelId=mid, messages=[{"role": "user", "content": [block, {"text": prompt}]}],
                               inferenceConfig={"temperature": 0, "maxTokens": 2000})

    try:
        resp = ask(model_id)
    except Exception as e:  # noqa: BLE001  Pro not enabled / not allowed: use Nova Lite
        print("[rx] falling back to", fallback_id, "-", type(e).__name__, flush=True)
        model_id = fallback_id
        resp = ask(model_id)
    
    text = resp["output"]["message"]["content"][0]["text"]
    rows = _rows_from(text)
    if not rows:  # one retry when the reply was not readable JSON
        rows = _rows_from(ask(model_id)["output"]["message"]["content"][0]["text"])
    if not rows:
        raise ValueError("Could not read the prescription. Please upload a clearer photo.")
    return rows


def _rows_from(text: str) -> list[dict]:
    """Parse the JSON array; if it is broken, keep every medicine object that parses."""
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            rows = json.loads(m.group(0))
            if isinstance(rows, list):
                return [r for r in rows if isinstance(r, dict) and r.get("medicine_name")]
        except json.JSONDecodeError:
            pass
    out = []
    for obj in re.findall(r'\{[^{}]*"medicine_name"[^{}]*\}', text):
        try:
            out.append(json.loads(obj))
        except json.JSONDecodeError:
            continue
    return out


def explain_abbreviations(frequency_text: str) -> dict:
    """Explain abbreviations in frequency_text using med_abbreviations.json.
    
    Returns {en: explanation, ta: explanation, unknown: [list of unknown abbrs]}.
    """
    freq_lower = frequency_text.lower()
    abbr_items = ABBREVIATIONS.get("items", [])
    
    explanations_en = []
    explanations_ta = []
    unknown_abbrs = []
    
    # Try to match known abbreviations
    found_any = False
    
    for item in abbr_items:
        main_abbr = item.get("abbr", "").lower()
        if main_abbr in freq_lower:
            explanations_en.append(item.get("en", ""))
            explanations_ta.append(item.get("ta", ""))
            found_any = True
            break
        
        # Check alternatives
        for alt in item.get("alt", []):
            if alt.lower() in freq_lower:
                explanations_en.append(item.get("en", ""))
                explanations_ta.append(item.get("ta", ""))
                found_any = True
                break
    
    if not found_any:
        # Could not decode
        unknown_abbrs.append(frequency_text)
    
    return {
        "en": " + ".join(explanations_en) if explanations_en else "",
        "ta": " + ".join(explanations_ta) if explanations_ta else "",
        "unknown": unknown_abbrs,
        "original": frequency_text
    }


def _decode_food_text(food_text: str) -> dict:
    """Decode food abbreviations (AC -> before food, PC -> after food).
    
    Returns {en, ta} or empty if not recognized.
    """
    if not food_text or not food_text.strip():
        return {"en": "", "ta": ""}
    
    food_lower = food_text.lower()
    abbr_items = ABBREVIATIONS.get("items", [])
    
    # Find matching abbreviation
    for item in abbr_items:
        main_abbr = item.get("abbr", "").lower()
        if main_abbr == "ac" and main_abbr in food_lower:
            return {"en": item.get("en", ""), "ta": item.get("ta", "")}
        if main_abbr == "pc" and main_abbr in food_lower:
            return {"en": item.get("en", ""), "ta": item.get("ta", "")}
    
    # If not found, return as-is
    return {"en": food_text, "ta": food_text}


def _decode_duration_text(duration_text: str) -> dict:
    """Parse duration text like "x 5 days" or "x 2 weeks".
    
    Returns {en: "for N days", ta: "N நாட்களுக்கு"} or as-is if not parsed.
    """
    if not duration_text or not duration_text.strip():
        return {"en": "", "ta": ""}
    
    duration_lower = duration_text.lower()
    
    # Try to match patterns like "5 days", "2 weeks", "x 7 days"
    match = re.search(r"(\d+)\s*(day|week|month)", duration_lower)
    if match:
        num = match.group(1)
        unit = match.group(2).lower()
        
        if unit.startswith("day"):
            return {
                "en": f"for {num} days",
                "ta": f"{num} நாட்களுக்கு"
            }
        elif unit.startswith("week"):
            return {
                "en": f"for {num} weeks",
                "ta": f"{num} வாரங்களுக்கு"
            }
        elif unit.startswith("month"):
            return {
                "en": f"for {num} months",
                "ta": f"{num} மாதங்களுக்கு"
            }
    
    # If not parsed, return as-is
    return {"en": duration_text, "ta": duration_text}


def get_prescription_explanation(row: dict) -> dict:
    """Get explanation for a prescription row.
    
    If legible=false or unknown abbreviation, return warning.
    Never say what the medicine is for or suggest dose changes.
    """
    if not row.get("legible"):
        return {
            "en": f"{row.get('medicine_name', 'Medicine')}: I can't read this clearly. Please confirm with your pharmacist.",
            "ta": f"{row.get('medicine_name', 'Medicine')}: இதை உறுதியாகப் படிக்க முடியவில்லை. மருந்தாளரிடம் சரிபார்க்கவும்."
        }
    
    medicine = row.get("medicine_name", "")
    dose = row.get("dose_text", "")
    frequency = row.get("frequency_text", "")
    duration = row.get("duration_text", "")
    food = row.get("food_text", "")
    
    if not frequency.strip():
        # e.g. a pharmacy bill: it lists the medicine but not how often to take it
        return {
            "en": f"{medicine} {dose}: How often is not written here. Please follow your doctor's prescription or ask your pharmacist.".replace("  ", " "),
            "ta": f"{medicine} {dose}: எத்தனை முறை என்பது இதில் எழுதப்படவில்லை. மருத்துவரின் மருந்துச் சீட்டைப் பின்பற்றுங்கள் அல்லது மருந்தாளரிடம் கேளுங்கள்.".replace("  ", " "),
        }

    # Try to explain frequency
    freq_explain = explain_abbreviations(frequency)
    
    if freq_explain.get("unknown"):
        # Unknown abbreviation
        return {
            "en": f"{medicine} {dose}: I can't decode '{frequency}'. Please confirm with your pharmacist.",
            "ta": f"{medicine} {dose}: '{frequency}' என்பதை நான் புரிந்துகொள்ள முடியவில்லை. மருந்தாளரிடம் சரிபார்க்கவும்."
        }
    
    # Decode food text
    food_explain = _decode_food_text(food)
    
    # Decode duration
    duration_explain = _decode_duration_text(duration)
    
    # Build explanation
    parts_en = [f"{medicine} {dose}"]
    parts_ta = [f"{medicine} {dose}"]
    
    if freq_explain.get("en"):
        parts_en.append(f"({freq_explain['en']})")
        parts_ta.append(f"({freq_explain['ta']})")
    
    if food_explain.get("en"):
        parts_en.append(food_explain['en'])
        parts_ta.append(food_explain['ta'])
    
    if duration_explain.get("en"):
        parts_en.append(duration_explain['en'])
        parts_ta.append(duration_explain['ta'])
    
    return {
        "en": " ".join(parts_en),
        "ta": " ".join(parts_ta)
    }


def get_confirmation_text(rows: list[dict]) -> dict:
    """Get confirmation text before saving prescription rows as medicines for a profile."""
    text_en = "Please confirm these medicines before saving to your profile:\n\n"
    text_ta = "உங்கள் சுயவிவரத்தில் சேமிப்பதற்கு முன் இந்த மருந்துகளைச் சரிபார்க்கவும்:\n\n"
    
    for i, row in enumerate(rows, 1):
        explan = get_prescription_explanation(row)
        text_en += f"{i}. {explan['en']}\n"
        text_ta += f"{i}. {explan['ta']}\n"
    
    text_en += "\nAre these correct? (yes/no)"
    text_ta += "\nஇவை சரியாக உள்ளதா? (ஆம்/இல்லை)"
    
    return {"en": text_en, "ta": text_ta}