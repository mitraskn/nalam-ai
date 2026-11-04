"""Doctor visit prep sheet — Combine medicines, abnormal tests, and symptoms.

Generates printable Tamil + English text for elderly to bring to doctor.
"""
from pathlib import Path
from .family import (
    get_profile, list_medicines, get_lab_history
)
from .report import get_glossary_entry, get_status_word


def _load_json(filename: str) -> dict:
    """Load JSON from agent/data/."""
    path = Path(__file__).parent / "data" / filename
    if path.exists():
        import json
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


GLOSSARY = _load_json("lab_glossary.json")


def make_prep_sheet(profile_name: str, symptoms: str = "") -> dict:
    """Generate doctor visit prep sheet.
    
    Combines:
    1. Current medicines
    2. Last report's HIGH/LOW tests with glossary questions
    3. User-entered symptoms
    
    Returns {en: text, ta: text}
    """
    profile = get_profile(profile_name)
    if not profile:
        return {
            "en": f"Profile '{profile_name}' not found.",
            "ta": f"சுயவிவரம் '{profile_name}' காணப்படவில்லை."
        }
    
    lines_en = []
    lines_ta = []
    
    # Header
    lines_en.append("=" * 60)
    lines_en.append(f"DOCTOR VISIT PREPARATION SHEET")
    lines_en.append(f"Name: {profile.get('name', '')}")
    lines_en.append(f"Relation: {profile.get('relation', '')}")
    lines_en.append(f"Age: {profile.get('age', '')}")
    lines_en.append("=" * 60)
    lines_en.append("")
    
    lines_ta.append("=" * 60)
    lines_ta.append(f"மருத்துவர் சந்திப்பு தயாரிப்பு பத்திரம்")
    lines_ta.append(f"பெயர்: {profile.get('name', '')}")
    lines_ta.append(f"உறவு: {profile.get('relation', '')}")
    lines_ta.append(f"வயது: {profile.get('age', '')}")
    lines_ta.append("=" * 60)
    lines_ta.append("")
    
    # Current medicines
    lines_en.append("CURRENT MEDICINES:")
    lines_ta.append("தற்போதைய மருந்துகள்:")
    
    meds = list_medicines(profile_name)
    if meds:
        for med in meds:
            # Skip if end date is past
            if med.get("end_date") and med.get("end_date") < __import__("datetime").datetime.now().strftime("%Y-%m-%d"):
                continue
            
            times_str = ", ".join(med.get("times", []))
            dose = med.get("dose_text", "")
            food = f" ({med['food']})" if med.get("food") else ""
            
            line_en = f"  • {med['name']}: {dose} at {times_str}{food}"
            line_ta = f"  • {med['name']}: {dose}, {times_str} மணி{food}"
            
            lines_en.append(line_en)
            lines_ta.append(line_ta)
    else:
        lines_en.append("  No current medicines")
        lines_ta.append("  மருந்துகளெதுவுமில்லை")
    
    lines_en.append("")
    lines_ta.append("")
    
    # Recent lab results (abnormal only)
    lines_en.append("RECENT LAB RESULTS (abnormal values):")
    lines_ta.append("சமீபத்திய ஆய்வு முடிவுகள் (অস্বাভাবিক):")
    
    lab_history = get_lab_history(profile_name)
    if lab_history:
        # Get last report
        last_report = lab_history[-1]
        abnormal_tests = [r for r in last_report.get("results", [])
                         if r.get("status") in ["HIGH", "LOW"]]
        
        if abnormal_tests:
            for test in abnormal_tests:
                status = test.get("status")
                status_word = get_status_word(status)
                
                line_en = f"  • {test['test']}: {test['value']} {test['unit']} ({status_word['en']})"
                line_ta = f"  • {test['test']}: {test['value']} {test['unit']} ({status_word['ta']})"
                
                lines_en.append(line_en)
                lines_ta.append(line_ta)
                
                # Add glossary question if available
                entry = get_glossary_entry(test['test'])
                if entry:
                    if status == "HIGH" and entry.get("q_high"):
                        q = entry["q_high"]
                        lines_en.append(f"    Question: {q.get('en', '')}")
                        lines_ta.append(f"    கேள்வி: {q.get('ta', '')}")
                    elif status == "LOW" and entry.get("q_low"):
                        q = entry["q_low"]
                        lines_en.append(f"    Question: {q.get('en', '')}")
                        lines_ta.append(f"    கேள்வி: {q.get('ta', '')}")
        else:
            lines_en.append("  All tests normal")
            lines_ta.append("  அனைத்துப் பரிசோதனைகளும் சரியாக உள்ளன")
    else:
        lines_en.append("  No lab history")
        lines_ta.append("  ஆய்வு வரலாறு இல்லை")
    
    lines_en.append("")
    lines_ta.append("")
    
    # Symptoms
    if symptoms:
        lines_en.append("CURRENT SYMPTOMS:")
        lines_ta.append("தற்போதைய அறிகுறிகள்:")
        lines_en.append(f"  {symptoms}")
        lines_ta.append(f"  {symptoms}")
        lines_en.append("")
        lines_ta.append("")
    
    # Footer
    lines_en.append("=" * 60)
    lines_en.append("Please show this sheet to your doctor.")
    lines_en.append("=" * 60)
    
    lines_ta.append("=" * 60)
    lines_ta.append("இந்தப் பத்திரத்தை மருத்துவரிடம் காட்டுங்கள்.")
    lines_ta.append("=" * 60)
    
    return {
        "en": "\n".join(lines_en),
        "ta": "\n".join(lines_ta)
    }
