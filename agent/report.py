"""Lab report explainer (Part 7b) — Extract, compare, and explain blood test results.

Core principle: Code owns reference ranges and status decisions. Model never writes medical explanations.
Nova extracts text; flag_rows() compares to ranges; glossary provides fixed explanations.
Status is ALWAYS from code, never from model.
"""
import json
import re
from typing import TypedDict
from pathlib import Path


class TestRow(TypedDict, total=False):
    test: str
    value: float
    unit: str
    range_text: str


class FlaggedRow(TypedDict, total=False):
    test: str
    value: float
    unit: str
    range_text: str
    range_source: str  # "from_report" or "fallback"
    status: str  # "HIGH", "LOW", "NORMAL", "UNKNOWN"
    note: str  # only if fallback used


# Load glossary on module import
def _load_glossary():
    """Load lab_glossary.json and build a lookup dict."""
    glossary_path = Path(__file__).parent / "data" / "lab_glossary.json"
    if not glossary_path.exists():
        print(f"[warning] Glossary not found: {glossary_path}")
        return {"tests": [], "status_words": {}, "default_question": {}, "general_questions": []}
    
    with open(glossary_path, encoding="utf-8") as f:
        return json.load(f)


GLOSSARY = _load_glossary()


# Fallback reference ranges (only used if report has no range)
# Format: test_name -> (min, max, unit, description)
FALLBACK_RANGES = {
    "random blood sugar": (70, 140, "mg/dL", "fasting or random blood glucose"),
    "fasting blood sugar": (70, 100, "mg/dL", "fasting glucose"),
    "post prandial blood sugar": (70, 140, "mg/dL", "blood glucose 2 hours after meal"),
    "hemoglobin": (13.5, 17.5, "g/dL", "male"),
    "haemoglobin female": (12.0, 15.5, "g/dL", "female"),
    "total cholesterol": (0, 200, "mg/dL", "desirable"),
    "ldl cholesterol": (0, 100, "mg/dL", "optimal"),
    "hdl cholesterol": (40, 300, "mg/dL", "male"),
    "triglycerides": (0, 150, "mg/dL", "normal fasting"),
    "tsh": (0.4, 4.0, "mIU/L", "thyroid stimulating hormone"),
    "t3": (80, 200, "ng/dL", "triiodothyronine"),
    "t4": (4.5, 11.5, "mcg/dL", "thyroxine"),
    "creatinine": (0.6, 1.2, "mg/dL", "serum creatinine"),
    "urea": (7, 20, "mg/dL", "blood urea nitrogen"),
    "sodium": (135, 145, "mmol/L", "serum sodium"),
    "potassium": (3.5, 5.0, "mmol/L", "serum potassium"),
    "calcium": (8.5, 10.5, "mg/dL", "serum calcium"),
    "albumin": (3.5, 5.0, "g/dL", "serum albumin"),
    "alt": (7, 56, "U/L", "alanine aminotransferase"),
    "ast": (10, 40, "U/L", "aspartate aminotransferase"),
    "bilirubin": (0.3, 1.2, "mg/dL", "total bilirubin"),
    "wbc": (4.5, 11.0, "K/uL", "white blood cells"),
    "rbc": (4.5, 5.9, "M/uL", "red blood cells (male)"),
    "platelets": (150, 400, "K/uL", "thrombocytes"),
    "inr": (0.8, 1.1, "ratio", "international normalized ratio (PT)"),
    "vitamin b12": (200, 900, "pg/mL", "cobalamin"),
    "vitamin d": (30, 100, "ng/mL", "calcifediol"),
}


def parse_range(range_text: str) -> tuple:
    """Parse range_text and extract (min, max).
    
    Handles formats like:
    - "70 - 100"
    - "< 200"
    - "> 40"
    - "up to 5"
    - ""
    
    Returns (min, max) or (None, None) if cannot parse.
    """
    if not range_text or not range_text.strip():
        return (None, None)
    
    range_text = range_text.strip()
    
    # Format: "min - max"
    match = re.match(r"^\s*([\d.]+)\s*-\s*([\d.]+)\s*$", range_text)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    
    # Format: "< max"
    match = re.match(r"^\s*<\s*([\d.]+)\s*$", range_text)
    if match:
        return (0, float(match.group(1)))
    
    # Format: "> min"
    match = re.match(r"^\s*>\s*([\d.]+)\s*$", range_text)
    if match:
        return (float(match.group(1)), 999999)
    
    # Format: "up to max"
    match = re.match(r"^\s*up to\s+([\d.]+)\s*$", range_text, re.IGNORECASE)
    if match:
        return (0, float(match.group(1)))
    
    return (None, None)


def flag_rows(rows: list[TestRow]) -> list[FlaggedRow]:
    """Compare each test value to its reference range. Return flagged rows with status.
    
    Status comes from code comparison, never from model.
    If no range_text, use fallback table with source="fallback" and a note.
    If test not in fallback, status="UNKNOWN - ask doctor".
    """
    flagged = []
    
    for row in rows:
        test_name = row.get("test", "").lower()
        value = row.get("value")
        range_text = row.get("range_text", "").strip()
        
        flagged_row: FlaggedRow = {
            "test": row.get("test", ""),
            "value": value,
            "unit": row.get("unit", ""),
            "range_text": range_text,
        }
        
        # Try to parse range from report
        min_val, max_val = parse_range(range_text)
        
        if min_val is not None and max_val is not None:
            # Range found in report
            flagged_row["range_source"] = "from_report"
            if value < min_val:
                flagged_row["status"] = "LOW"
            elif value > max_val:
                flagged_row["status"] = "HIGH"
            else:
                flagged_row["status"] = "NORMAL"
        else:
            # No range in report; try fallback
            # Look for keyword matches, including "random" and "fasting" variants
            fallback_key = None
            
            # Extract the base test name (before parentheses)
            base_test_name = test_name.split("(")[0].strip()
            
            # Try exact keyword matching
            for key in FALLBACK_RANGES.keys():
                if key in test_name or test_name in key:
                    fallback_key = key
                    break
            
            # If not found, try broader matching with base name
            if not fallback_key and base_test_name:
                for key in FALLBACK_RANGES.keys():
                    if key.startswith(base_test_name) or base_test_name in key:
                        fallback_key = key
                        break
            
            # Special case: "blood glucose" variants -> use random blood sugar fallback
            if not fallback_key and "glucose" in test_name:
                fallback_key = "random blood sugar"
            
            if fallback_key:
                fb_min, fb_max, fb_unit, fb_desc = FALLBACK_RANGES[fallback_key]
                flagged_row["range_source"] = "fallback"
                flagged_row["range_text"] = f"{fb_min} - {fb_max} {fb_unit}"
                flagged_row["note"] = "This report did not print a range; we used a general range. Ask your doctor."
                
                if value < fb_min:
                    flagged_row["status"] = "LOW"
                elif value > fb_max:
                    flagged_row["status"] = "HIGH"
                else:
                    flagged_row["status"] = "NORMAL"
            else:
                # Test not in fallback
                flagged_row["range_source"] = "unknown"
                flagged_row["status"] = "UNKNOWN - ask doctor"
                flagged_row["note"] = f"No reference range found for '{row.get('test', 'unknown')}'. Ask your doctor."
        
        flagged.append(flagged_row)
    
    return flagged


def read_report_via_nova(image_bytes: bytes, path_str: str) -> list[TestRow]:
    """Send image/PDF to Bedrock Nova and extract test rows.
    
    Returns list of {test, value (number), unit, range_text (as printed or "")}.
    Nova only extracts text; does NOT judge or diagnose.
    
    Uses boto3 converse API directly (not BedrockModel).
    """
    import boto3
    import os
    
    region = os.environ.get("AWS_REGION", "us-east-1")
    model_id = os.environ.get("REPORT_MODEL", "us.amazon.nova-lite-v1:0")
    
    # Determine content type from file extension
    ext = path_str.lower().rsplit(".", 1)[-1]
    
    if ext == "pdf":
        block = {"document": {"format": "pdf", "name": "report", "source": {"bytes": image_bytes}}}
    else:
        block = {"image": {"format": "jpeg" if ext in ("jpg", "jpeg") else ext, "source": {"bytes": image_bytes}}}
    
    prompt = ("Read this lab report. Return ONLY a JSON array, no other text. One object per test row: "
              '{"test": name, "value": number, "unit": unit, "range_text": reference range exactly as printed or ""}. '
              "Do not judge or interpret anything.")
    
    client = boto3.client("bedrock-runtime", region_name=region)
    
    resp = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [block, {"text": prompt}]}],
        inferenceConfig={"temperature": 0, "maxTokens": 2000}
    )
    
    text = resp["output"]["message"]["content"][0]["text"]
    
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise ValueError("Could not read the report. Please upload a clearer photo.")
    
    rows = json.loads(m.group(0))
    
    # Ensure values are numbers
    for row in rows:
        if isinstance(row.get("value"), str):
            row["value"] = float(row["value"])
    
    return rows


def get_glossary_entry(test_name: str) -> dict | None:
    """Find glossary entry by matching test_name to aliases.
    
    Matches: lowercase the test name, check every alias as a substring.
    Pick the LONGEST matching alias (so "HbA1c" matches hba1c, not hb).
    """
    test_lower = test_name.lower()
    best_match = None
    best_match_len = 0
    
    for test_entry in GLOSSARY.get("tests", []):
        for alias in test_entry.get("aliases", []):
            alias_lower = alias.lower()
            # Check if alias is a substring of the test name (case-insensitive)
            if alias_lower in test_lower:
                # Pick the longest match (e.g., "hba1c" wins over "hb")
                if len(alias_lower) > best_match_len:
                    best_match = test_entry
                    best_match_len = len(alias_lower)
    
    return best_match


def get_status_word(status: str) -> dict:
    """Get Tamil + English status word from glossary."""
    status_words = GLOSSARY.get("status_words", {})
    return status_words.get(status, {"en": status, "ta": status})


def get_explanation_for_row(test_name: str, value: float, status: str, unit: str) -> dict:
    """Get explanation for a test row from glossary.
    
    Returns: {"en": explanation, "ta": explanation_ta, "q_high": question_if_high, "q_low": question_if_low}
    """
    entry = get_glossary_entry(test_name)
    
    if not entry:
        # No glossary entry: return generic message
        return {
            "en": f"{test_name}: {value} {unit}. Ask your doctor what this test means.",
            "ta": f"{test_name}: {value} {unit}. மருத்துவரிடம் இந்தப் பரிசோதனை என்ன என்பதைக் கேளுங்கள்.",
            "glossary_found": False
        }
    
    # Get status word
    status_word = get_status_word(status)
    
    # Build explanation with glossary text + status
    en_explain = f"{test_name}: {entry['en']} Your result is {status_word['en']}."
    ta_explain = f"{test_name}: {entry['ta']} உங்கள் முடிவு {status_word['ta']}."
    
    # Get questions for this status
    q_high = entry.get("q_high")
    q_low = entry.get("q_low")
    
    return {
        "en": en_explain,
        "ta": ta_explain,
        "q_high": q_high,
        "q_low": q_low,
        "glossary_found": True
    }


def get_doctor_questions(flagged_rows: list[FlaggedRow]) -> list[dict]:
    """Build list of questions: abnormal ones first (using q_high/q_low), then general.
    
    Max 5 questions total, abnormal ones first.
    """
    questions = []
    
    # First: collect abnormal questions (HIGH or LOW)
    for row in flagged_rows:
        status = row.get("status", "NORMAL")
        if status == "HIGH":
            entry = get_glossary_entry(row["test"])
            if entry and entry.get("q_high"):
                questions.append(entry["q_high"])
        elif status == "LOW":
            entry = get_glossary_entry(row["test"])
            if entry and entry.get("q_low"):
                questions.append(entry["q_low"])
    
    # If no abnormal questions, use default
    if not questions:
        default_q = GLOSSARY.get("default_question", {})
        if default_q:
            questions.append(default_q)
    
    # Then: add general questions up to max 5 total
    general_qs = GLOSSARY.get("general_questions", [])
    for gen_q in general_qs:
        if len(questions) >= 5:
            break
        questions.append(gen_q)
    
    return questions[:5]
