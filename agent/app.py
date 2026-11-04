"""Generic starter for YOUR idea. It runs as-is (a planner -> critic graph with a red-flag hook); make it yours.

    python -m agent.app "your user's message"

Same spine as the HeatSafe Shift example (kit/examples/heatsafe), with the domain left for you. Add blocks
from `ss blocks` as DESIGN.md says:
- EDIT ME 1: GOAL and the planner/critic rules below.
- EDIT ME 2: RED_FLAGS: phrases that must stop the agents and get a human (pharmacist, teacher, officer).
- EDIT ME 3: agent/data/guidance.json: the only sources the agent may cite, each with a URL and date.
- EDIT ME 4: Answer fields in agent/plan.py.
IDEA.md says who it is for; DESIGN.md says which Strands blocks it uses and what is measured.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

from strands import Agent
from strands.hooks import BeforeNodeCallEvent, HookProvider, HookRegistry
from strands.models import BedrockModel
from strands.multiagent import GraphBuilder

from . import tools
from .plan import Answer, Critique

MODEL_ID = os.environ.get("SHIP_MODEL", "us.amazon.nova-2-lite-v1:0")
REGION = os.environ.get("BEDROCK_REGION") or os.environ.get("AWS_REGION", "us-east-1")  # on Lambda in Sydney, Bedrock stays in us-east-1
logging.getLogger("strands").setLevel(logging.CRITICAL)


def _load_json(filename: str) -> dict:
    """Load JSON from agent/data/."""
    from pathlib import Path
    path = Path(__file__).parent / "data" / filename
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


# Load data once for routing
ABBREVIATIONS = _load_json("med_abbreviations.json")
GLOSSARY = _load_json("lab_glossary.json")
MYTHS = _load_json("myths.json")

GOAL = "Explain the user's question in plain {lang} (en = English, ta = Tamil script) using only the cited guidance."  # EDIT ME 1

# EDIT ME 2: RED_FLAGS — emergency keywords (English, Tamil, Tanglish), matched case-insensitively.
# Sources: Tamil Nadu ambulance (108), India emergency (112), Tele-MANAS mental health (14416)
RED_FLAGS = [
    # English
    "chest pain", "can't breathe", "cannot breathe", "breathing difficulty", "unconscious", "fainted",
    "seizure", "fits", "stroke", "face drooping", "slurred speech", "one side weak", "snake bite",
    "snakebite", "heavy bleeding", "bleeding won't stop", "poison", "swallowed", "suicide", "kill myself",
    "want to die", "overdose",
    # Tamil
    "நெஞ்சு வலி", "மூச்சு விட முடியவில்லை", "மூச்சுத் திணறல்", "மயக்கம்", "வலிப்பு", "வாய் கோணல்",
    "பாம்பு கடி", "ரத்தம் நிற்கவில்லை", "விஷம்", "தற்கொலை", "சாக வேண்டும்",
    # Tanglish
    "nenju vali", "moochu vida mudiyala", "mayakkam", "valippu", "paambu kadi", "ratham nikkala", "visham", "sethuralam"
]

# HANDOFF text — fixed, code-owned, model cannot change
EMERGENCY_EN = "This may be a medical emergency. Call 108 (ambulance) or 112 now. Do not wait for this app."
EMERGENCY_TA = "இது அவசர மருத்துவ நிலையாக இருக்கலாம். உடனே 108 (ஆம்புலன்ஸ்) அல்லது 112-ஐ அழைக்கவும். இந்த செயலிக்காக காத்திருக்க வேண்டாம்."
SUICIDE_EN = "You are not alone. Call Tele-MANAS 14416 (free, 24x7) or 112 now."
SUICIDE_TA = "நீங்கள் தனியாக இல்லை. இப்போதே டெலி-மனஸ் 14416 (இலவசம், 24 மணி நேரமும்) அல்லது 112-ஐ அழைக்கவும்."
REFUSE_EN = "I can't diagnose illness or change medicine doses. Please ask your doctor or pharmacist."
REFUSE_TA = "நோயைக் கண்டறியவோ, மருந்தின் அளவை மாற்றவோ என்னால் முடியாது. உங்கள் மருத்துவர் அல்லது மருந்தாளரிடம் கேளுங்கள்."

HANDOFF = {"en": EMERGENCY_EN, "ta": EMERGENCY_TA}
SUICIDE_PHRASES = ["suicide", "kill myself", "want to die", "தற்கொலை", "சாக வேண்டும்", "sethuralam"]
PLANNER = GOAL + (" Call lookup_guidance first. Cite only ids it returns. Answer like a kind health worker talking to an elder:"
           " 2 or 3 short, simple sentences that say directly what it is and what to do. No long lists, at most 2 steps."
           " Never diagnose and never change a medicine dose. If asked what a medicine is for and lookup_guidance has no MED- item for it,"
           " say you do not have checked information on that medicine and to ask the pharmacist. Never say how many times a day to take any medicine."
           " Fix every problem a critic lists.")
CRITIC = ("Reply ok=false with one line per problem if the answer is not in {lang}, cites an id not in {ids}, "
          "gives advice the guidance does not support, or is empty. Otherwise ok=true.")


class RedFlagGate(HookProvider):
    def __init__(self):
        self.tripped = []
        self.is_suicide = False
        self.is_diagnosis_or_dose = False
        self.kind = None

    def register_hooks(self, registry: HookRegistry, **_):
        registry.add_callback(BeforeNodeCallEvent, self._before)

    def _before(self, event: BeforeNodeCallEvent):
        # One shared, code-only safety check (agent/safety.py), same as the web app.
        from .safety import classify
        verdict = classify(str(event.invocation_state.get("user_text", "")))
        self.kind = verdict["kind"]
        if verdict["kind"] in ("emergency", "distress", "support"):
            self.tripped = verdict["hits"]
            self.is_suicide = verdict["kind"] in ("distress", "support")
            event.cancel_node = "red flag: " + ", ".join(self.tripped)
        elif verdict["kind"] == "refuse":
            self.is_diagnosis_or_dose = True
            event.cancel_node = "diagnosis/dose question"


def _model():
    return BedrockModel(model_id=MODEL_ID, region_name=REGION, temperature=0.2)


def build_graph(lang, gate):
    planner = Agent(model=_model(), name="planner", system_prompt=PLANNER.format(lang=lang), tools=[tools.lookup_guidance],
                    structured_output_model=Answer, callback_handler=None)
    critic = Agent(model=_model(), name="critic", system_prompt=CRITIC.format(lang=lang, ids=sorted(tools.guidance_ids())),
                   structured_output_model=Critique, callback_handler=None)

    def again(state):
        r = state.results.get("critic")
        v = getattr(r.result, "structured_output", None) if r else None
        n = sum(1 for x in state.execution_order if x.node_id == "planner")
        if v is not None:
            print(f"[critic] pass {n}: " + ("PASS" if v.ok else "REVISE - " + "; ".join(v.problems)[:200]), flush=True)
        return bool(v is not None and not v.ok and n < 2)

    b = GraphBuilder()
    b.add_node(planner, "planner")
    b.add_node(critic, "critic")
    b.add_edge("planner", "critic")
    b.add_edge("critic", "planner", condition=again)
    b.set_entry_point("planner")
    b.set_max_node_executions(4)
    b.reset_on_revisit(True)
    b.set_hook_providers([gate])
    return b.build()


def _try_router(text: str, lang: str) -> dict | None:
    """Try to route the message to word/myth/care before calling the model.
    
    Returns {answer, route} or None if should go to model.
    """
    from .features import word_bridge, myth_buster, care_finder
    
    text_lower = text.lower()
    
    # Load abbreviations and glossary for matching
    abbr_items = ABBREVIATIONS.get("items", [])
    glossary_tests = GLOSSARY.get("tests", [])
    myth_items = MYTHS.get("items", [])
    
    # Keywords that indicate meaning lookup
    meaning_keywords = ["enna", "na enna", "meaning", "what is", "endral", "என்ன", "அர்த்தம்"]
    has_meaning_keyword = any(kw in text_lower for kw in meaning_keywords)
    
    # 1. Word bridge: check if asking for a term's meaning
    if has_meaning_keyword:
        # Try to find an abbreviation or glossary term
        for item in abbr_items:
            abbr = item.get("abbr", "").lower()
            if abbr in text_lower:
                result = word_bridge(abbr)
                if result["found"]:
                    print(f"[router] word", flush=True)
                    return {"answer": result, "route": "word"}
        
        # Try glossary aliases
        for test in glossary_tests:
            for alias in test.get("aliases", []):
                if alias.lower() in text_lower:
                    result = word_bridge(alias)
                    if result["found"]:
                        print(f"[router] word", flush=True)
                        return {"answer": result, "route": "word"}
    
    # 2. Myth buster: check for myth keywords
    for item in myth_items:
        for key in item.get("keys", []):
            if key.lower() in text_lower:
                result = myth_buster(text)
                if result["found"]:
                    print(f"[router] myth", flush=True)
                    return {"answer": result, "route": "myth"}
    
    # 3. Care finder: check for care-related keywords
    care_keywords = ["hospital", "phc", "pharmacy", "ambulance", "aspathiri", 
                     "மருத்துவமனை", "மருந்தகம்", "ஆம்புலன்ஸ்"]
    if any(kw in text_lower for kw in care_keywords):
        care = care_finder()
        print(f"[router] care", flush=True)
        return {"answer": care, "route": "care"}
    
    # 4. Otherwise, go to model
    print(f"[router] model", flush=True)
    return None


def _format_routed_answer(routed: dict, lang: str) -> str:
    """Format routed answer for display."""
    route = routed.get("route")
    answer = routed.get("answer", {})
    
    if route == "word":
        if answer.get("found"):
            text = f"{answer['term']}:\n"
            text += f"  English: {answer['en']}\n"
            text += f"  Tamil:   {answer['ta']}"
            return text
        else:
            return answer["en"]
    
    elif route == "myth":
        if answer.get("found"):
            labels = _load_json("schemes_and_labels.json").get("labels", {})
            myth_label = labels.get("myth", {})
            verdict_label = labels.get("verdict", {})
            answer_label = labels.get("answer", {})
            
            text = f"{myth_label.get('en', 'Myth')}: {answer['myth_en']}\n"
            text += f"{myth_label.get('ta', 'நம்பிக்கை')}: {answer['myth_ta']}\n\n"
            text += f"{verdict_label.get('en', 'Verdict')}: {answer['verdict']}\n\n"
            text += f"{answer_label.get('en', 'Answer')}:\n{answer['en']}\n\n"
            text += f"{answer_label.get('ta', 'விடை')}:\n{answer['ta']}"
            return text
        else:
            return answer["en"]
    
    elif route == "care":
        labels = _load_json("schemes_and_labels.json").get("labels", {})
        emergency_label = labels.get("emergency_numbers", {})
        
        text = f"{emergency_label.get('en', 'Emergency')}: {emergency_label.get('ta', 'அவசர')}\n"
        for em in answer.get("emergency", []):
            text += f"{em['number']}: {em['en']} / {em['ta']}\n"
        return text
    
    return ""


def _routed_text(r: dict, lang: str) -> str:
    """Fixed-content answer from agent/web.py route(), in ONE language (same text the web app shows)."""
    L = "ta" if lang == "ta" else "en"
    k = r["type"]
    if k == "medicine":
        return f"{r['name']}: {r['use_' + L]} {r['how_' + L]}".strip()
    if k == "word":
        how = r.get("how_" + L, "")
        return f"{r['term']} = {how}" if how else f"{r['term']}: {r[L]}"
    if k == "myth":
        return f"{r['myth_' + L]} {r['verdict_' + L]}: {r[L]}"
    if k == "scheme":
        return r[L]
    if k == "care":
        return ("அருகிலுள்ள மருத்துவமனையைக் கண்டறிய 'மருத்துவமனை' பக்கத்தைத் திறங்கள். அவசரம் என்றால் 108." if L == "ta"
                else "Open the Hospitals page to find a hospital near you. In an emergency call 108.")
    return ""


ESC_ROUTED = {"en": "If you are unsure or feel unwell, ask your doctor or pharmacist. In an emergency call 108.",
              "ta": "சந்தேகம் இருந்தாலோ உடல்நிலை சரியில்லை என்றாலோ மருத்துவர் அல்லது மருந்தாளரிடம் கேளுங்கள். அவசரம் என்றால் 108."}


def _routed_cites(r: dict) -> list[str]:
    ids = tools.guidance_ids()
    k = r["type"]
    if k == "medicine":
        for g in tools.guidance()["items"]:
            if g["id"].startswith("MED-") and g["text"].lower().startswith(r["name"].lower() + ":"):
                return [g["id"]]
    if k == "word":
        c = "ABBR-" + r["term"].upper().replace(" ", "_")
        if c in ids:
            return [c]
        for g in tools.guidance()["items"]:
            if g["id"].startswith("LAB-") and g["text"] == r.get("en"):
                return [g["id"]]
    if k == "myth":
        return ["MYTH-" + r["id"]]
    return {"scheme": ["SCHEME-RULES"], "care": ["CARE-FIND"]}.get(k, [])


def run(case: dict) -> dict:
    """Same order as the web app: code safety check -> fixed-content router -> Strands graph (planner + critic)."""
    t0 = time.time()
    lang = case.get("lang") or tools.language_of(case["text"])
    from .safety import classify
    meta = {"path": "agent", "passes": 0}
    verdict = classify(case["text"])
    L = "ta" if lang == "ta" else "en"
    warn = verdict[L] if verdict["kind"] == "warn" and not case.get("skip_warn") else ""
    if verdict["kind"] in (None, "warn"):
        from .web import route
        routed = route(case["text"], case.get("profile", ""))
        if routed:
            ans = Answer(language=lang, answer=((warn + "\n\n") if warn else "") + _routed_text(routed, lang), steps=[],
                         escalation=warn or ESC_ROUTED[L], citations=_routed_cites(routed) + (["SAFE-WARN"] if warn else []))
            meta.update(path=f"router/{routed['type']}", latency_ms=int((time.time() - t0) * 1000))
            print(f"[plan] {meta['path']} | {meta['latency_ms']} ms", flush=True)
            return {"plan": ans.model_dump(), "meta": meta}
    gate = RedFlagGate()
    try:
        res = build_graph(lang, gate)(f"User ({lang}): {case['text']}", invocation_state={"user_text": case["text"]})
    except RuntimeError:
        if not gate.tripped and not gate.is_diagnosis_or_dose:
            raise
        res = None
    if gate.tripped:
        print(f"[safety] RED FLAG ({', '.join(gate.tripped)}) -> HAND OFF, agents cancelled", flush=True)
        handoff_text = classify(case["text"])["ta" if lang == "ta" else "en"]  # same words the web app shows
        ans = Answer(language=lang, answer=handoff_text, steps=[], escalation=handoff_text,
                     citations=["SAFE-MIND"] if gate.is_suicide else ["SAFE-EMERG"])
        meta["path"] = "handoff"
    elif gate.is_diagnosis_or_dose:
        print("[safety] DIAGNOSIS/DOSE QUESTION -> REFUSE, agents cancelled", flush=True)
        refuse_text = REFUSE_EN if lang == "en" else REFUSE_TA
        ans = Answer(language=lang, answer=refuse_text, steps=[], escalation=refuse_text, citations=["SAFE-DOSE", "SAFE-DIAG"])
        meta["path"] = "handoff"
    else:
        ans = res.results["planner"].result.structured_output
        if ans is None:
            raise RuntimeError("planner returned no structured answer")
        # The hand-off line is code-owned: always the fixed, checked wording (never model-written).
        ans = ans.model_copy(update={"escalation": ESC_ROUTED[L]})
        if warn:  # warning sign mentioned in a normal chat: fixed warning first, then the agent's answer
            ans = ans.model_copy(update={"answer": warn + "\n\n" + ans.answer, "escalation": warn,
                                         "citations": list(ans.citations) + ["SAFE-WARN"]})
        meta["passes"] = sum(1 for n in res.execution_order if n.node_id == "planner")
    meta["latency_ms"] = int((time.time() - t0) * 1000)
    print(f"[plan] {meta['path']} | {meta['latency_ms']} ms", flush=True)
    return {"plan": ans.model_dump(), "meta": meta}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m agent.app")
    subparsers = ap.add_subparsers(dest="command", help="Commands")
    
    # Chat
    chat_parser = subparsers.add_parser("chat", help="Chat with the agent")
    chat_parser.add_argument("text", nargs="?", default="")
    chat_parser.add_argument("--json", action="store_true")
    
    # Report
    report_parser = subparsers.add_parser("report", help="Read and explain a lab report")
    report_parser.add_argument("report", help="Path to lab report image")
    report_parser.add_argument("--profile", help="Profile to save results to (optional)")
    
    # Family (profiles, medicines, appointments, etc.)
    profile_parser = subparsers.add_parser("profile", help="Manage profiles")
    profile_subparsers = profile_parser.add_subparsers(dest="profile_cmd")
    profile_subparsers.add_parser("list", help="List all profiles")
    add_p = profile_subparsers.add_parser("add", help="Add a profile")
    add_p.add_argument("--name", required=True)
    add_p.add_argument("--relation", required=True)
    add_p.add_argument("--age", type=int, required=True)
    add_p.add_argument("--notes", default="")
    
    # Medicine
    med_parser = subparsers.add_parser("med", help="Manage medicines")
    med_subparsers = med_parser.add_subparsers(dest="med_cmd")
    med_subparsers.add_parser("list", help="List medicines").add_argument("--profile", required=True)
    add_m = med_subparsers.add_parser("add", help="Add medicine")
    add_m.add_argument("--profile", required=True)
    add_m.add_argument("--name", required=True)
    add_m.add_argument("--dose", required=True)
    add_m.add_argument("--times", required=True, help="Comma-separated times: 08:00,20:00")
    add_m.add_argument("--start", required=True, help="YYYY-MM-DD")
    add_m.add_argument("--end", default="", help="YYYY-MM-DD")
    add_m.add_argument("--food", default="", help="before/after/with")
    
    taken = med_subparsers.add_parser("taken", help="Mark medicine as taken")
    taken.add_argument("--profile", required=True)
    taken.add_argument("--name", required=True)
    taken.add_argument("--time", required=True, help="HH:MM")
    
    missed = med_subparsers.add_parser("missed", help="Mark medicine as missed")
    missed.add_argument("--profile", required=True)
    missed.add_argument("--name", required=True)
    missed.add_argument("--time", required=True, help="HH:MM")
    
    adh = med_subparsers.add_parser("adherence", help="Show medicine adherence")
    adh.add_argument("--profile", required=True)
    adh.add_argument("--days", type=int, default=7)
    
    # Appointment
    appt_parser = subparsers.add_parser("appt", help="Manage appointments")
    appt_subparsers = appt_parser.add_subparsers(dest="appt_cmd")
    appt_subparsers.add_parser("list", help="List upcoming").add_argument("--profile", required=True)
    add_a = appt_subparsers.add_parser("add", help="Add appointment")
    add_a.add_argument("--profile", required=True)
    add_a.add_argument("--date", required=True, help="YYYY-MM-DD")
    add_a.add_argument("--time", required=True, help="HH:MM")
    add_a.add_argument("--where", required=True)
    add_a.add_argument("--note", default="")
    
    # History
    hist_parser = subparsers.add_parser("history", help="Compare lab test history")
    hist_parser.add_argument("--profile", required=True)
    hist_parser.add_argument("--test", required=True)
    
    # Prep sheet
    prep_parser = subparsers.add_parser("prep", help="Make doctor prep sheet")
    prep_parser.add_argument("--profile", required=True)
    prep_parser.add_argument("--symptoms", default="")
    
    # Word bridge
    word_parser = subparsers.add_parser("word", help="Look up medical term")
    word_parser.add_argument("term")
    
    # Myth buster
    myth_parser = subparsers.add_parser("myth", help="Check health myth")
    myth_parser.add_argument("question")
    
    # Tip
    subparsers.add_parser("tip", help="Health tip of the day")
    
    # Care finder
    subparsers.add_parser("care", help="Emergency and care places")
    
    # Scheme
    subparsers.add_parser("scheme", help="Health insurance schemes")
    
    # Prescription
    rx_parser = subparsers.add_parser("prescription", help="Read prescription")
    rx_parser.add_argument("image", help="Path to prescription image")
    rx_parser.add_argument("--profile", help="Profile to save to (optional)")
    
    a = ap.parse_args(argv)
    
    # Import feature modules
    from .family import (
        add_profile, list_profiles, get_profile,
        add_medicine, list_medicines, mark_medicine_taken, adherence_percentage,
        add_appointment, list_appointments, save_lab_report, compare_test_history
    )
    from .features import word_bridge, myth_buster, tip_of_the_day, care_finder
    from .scheme_guide import get_scheme_guide
    from .prep_sheet import make_prep_sheet
    from .prescription import read_prescription_via_nova, get_prescription_explanation, get_confirmation_text
    from .report import read_report_via_nova, flag_rows, get_explanation_for_row, get_doctor_questions
    from pathlib import Path
    
    # Default: chat
    if not a.command or a.command == "chat":
        text = a.text if a.text else (ap.parse_args([]).text if len(argv or []) > 0 else "")
        if not text:
            print("Usage: python -m agent.app <message> [--json] or python -m agent.app --help")
            return 1
        out = run({"text": text})
        print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else "\n" + out["plan"]["answer"])
        return 0
    
    # Report
    if a.command == "report":
        report_path = Path(a.report)
        if not report_path.exists():
            print(f"[error] Report not found: {a.report}")
            return 1
        
        print(f"[report] Reading {report_path.name}...", flush=True)
        
        try:
            with open(report_path, "rb") as f:
                image_bytes = f.read()
            
            rows = read_report_via_nova(image_bytes, str(report_path))
            if not rows:
                print("[error] Could not extract test results from report")
                return 1
            
            print(f"[report] Extracted {len(rows)} tests", flush=True)
            
            flagged = flag_rows(rows)
            
            print()
            print("=" * 100)
            print(f"Lab Report: {report_path.name}")
            print("=" * 100)
            print()
            print(f"{'Test':<25} {'Value':<12} {'Unit':<12} {'Range':<20} {'Status':<15}")
            print("-" * 100)
            
            for f in flagged:
                status = f.get("status", "UNKNOWN")
                note = f.get("note", "")
                range_text = f.get("range_text", "")
                range_source = f.get("range_source", "")
                
                if range_source == "fallback":
                    range_text = f"{range_text} (fallback)"
                
                print(f"{f['test']:<25} {str(f['value']):<12} {f['unit']:<12} {range_text:<20} {status:<15}")
                if note:
                    print(f"  Note: {note}")
            
            print()
            print("=" * 100)
            print("EXPLANATIONS")
            print("=" * 100)
            
            for f in flagged:
                status = f.get("status", "UNKNOWN")
                test = f["test"]
                value = f["value"]
                unit = f["unit"]
                
                explan = get_explanation_for_row(test, value, status, unit)
                
                print(f"\n{test}:")
                print(f"  English: {explan['en']}")
                print(f"  Tamil:   {explan['ta']}")
            
            print()
            print("=" * 100)
            print("QUESTIONS TO ASK YOUR DOCTOR:")
            print("=" * 100)
            
            questions = get_doctor_questions(flagged)
            
            for i, q in enumerate(questions, 1):
                if isinstance(q, dict):
                    print(f"{i}. {q.get('ta', q.get('en', ''))}")
                    print(f"   {q.get('en', '')}")
                else:
                    print(f"{i}. {q}")
            
            print()
            print("=" * 100)
            print("DISCLAIMER:")
            print("Tamil: இது ஒரு விளக்கம் மட்டுமே, நோய் கண்டறிதல் அல்ல. உங்கள் மருத்துவரிடம் காட்டுங்கள்.")
            print("English: This is only an explanation, not a diagnosis. Please show this report to your doctor.")
            print("=" * 100)
            
            # Optionally save to profile
            if a.profile:
                save_lab_report(a.profile, str(datetime.now().date()), [
                    {"test": f["test"], "value": f["value"], "unit": f["unit"], "status": f["status"]}
                    for f in flagged
                ])
                print(f"\n[saved] Results saved to profile '{a.profile}'")
            
            return 0
        
        except Exception as e:
            print(f"[error] {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    # Profile commands
    if a.command == "profile":
        if a.profile_cmd == "list":
            profiles = list_profiles()
            if profiles:
                for p in profiles:
                    profile = get_profile(p)
                    if profile:
                        print(f"{p} ({profile.get('relation', '')}), age {profile.get('age', '')}")
            else:
                print("No profiles found.")
            return 0
        
        elif a.profile_cmd == "add":
            profile = add_profile(a.name, a.relation, a.age, a.notes)
            print(f"[added] Profile: {profile['name']} ({profile['relation']}, age {profile['age']})")
            return 0
    
    # Medicine commands
    if a.command == "med":
        if a.med_cmd == "list":
            meds = list_medicines(a.profile)
            if meds:
                for med in meds:
                    times = ", ".join(med.get("times", []))
                    food = f" ({med['food']})" if med.get("food") else ""
                    end_note = f" until {med['end_date']}" if med.get("end_date") else ""
                    print(f"• {med['name']}: {med['dose_text']} at {times}{food}{end_note}")
            else:
                print("No medicines.")
            return 0
        
        elif a.med_cmd == "add":
            times = a.times.split(",")
            med = add_medicine(a.profile, a.name, a.dose, times, a.start, a.end, a.food)
            print(f"[added] {med['name']}: {med['dose_text']}")
            return 0
        
        elif a.med_cmd == "taken":
            result = mark_medicine_taken(a.profile, a.name, a.time, taken=True)
            if result:
                print(f"[logged] {a.name} at {a.time} marked as TAKEN")
            else:
                print(f"[error] Medicine '{a.name}' not found")
            return 0
        
        elif a.med_cmd == "missed":
            result = mark_medicine_taken(a.profile, a.name, a.time, taken=False)
            if result:
                print(f"[logged] {a.name} at {a.time} marked as MISSED")
            else:
                print(f"[error] Medicine '{a.name}' not found")
            return 0
        
        elif a.med_cmd == "adherence":
            adh = adherence_percentage(a.profile, a.days)
            print(f"Adherence (last {adh['days']} days): {adh['adherence']}% ({adh['taken']}/{adh['total']})")
            return 0
    
    # Appointment commands
    if a.command == "appt":
        if a.appt_cmd == "list":
            appts = list_appointments(a.profile, upcoming_only=True)
            if appts:
                for appt in appts:
                    print(f"{appt['date']} {appt['time']}: {appt['doctor_or_hospital']}")
                    if appt.get("note"):
                        print(f"  Note: {appt['note']}")
            else:
                print("No upcoming appointments.")
            return 0
        
        elif a.appt_cmd == "add":
            appt = add_appointment(a.profile, a.date, a.time, a.where, a.note)
            print(f"[added] Appointment on {appt['date']} at {appt['time']} ({appt['doctor_or_hospital']})")
            return 0
    
    # History
    if a.command == "history":
        comp = compare_test_history(a.profile, a.test)
        if comp["can_compare"]:
            print(f"\nHistory of {comp['test']} ({comp['unit']}):")
            for h in comp["history"]:
                print(f"  {h['date']}: {h['value']} ({h['status']})")
        else:
            print(f"Cannot compare: {comp['reason']}")
        return 0
    
    # Prep sheet
    if a.command == "prep":
        sheet = make_prep_sheet(a.profile, a.symptoms)
        print(sheet["en"])
        print("\n" + "=" * 60 + "\n")
        print(sheet["ta"])
        return 0
    
    # Word bridge
    if a.command == "word":
        result = word_bridge(a.term)
        if result["found"]:
            print(f"{a.term}:")
            print(f"  English: {result['en']}")
            print(f"  Tamil:   {result['ta']}")
        else:
            print(result["en"])
        return 0
    
    # Myth buster
    if a.command == "myth":
        result = myth_buster(a.question)
        if result["found"]:
            labels = _load_json("schemes_and_labels.json").get("labels", {})
            myth_label = labels.get("myth", {})
            verdict_label = labels.get("verdict", {})
            answer_label = labels.get("answer", {})
            
            print(f"{myth_label.get('en', 'Myth')}: {result['myth_en']}")
            print(f"{myth_label.get('ta', 'நம்பிக்கை')}: {result['myth_ta']}")
            print()
            print(f"{verdict_label.get('en', 'Verdict')}: {result['verdict']}")
            print()
            print(f"{answer_label.get('en', 'Answer')}:")
            print(result['en'])
            print(f"\n{answer_label.get('ta', 'விடை')}:")
            print(result['ta'])
        else:
            print(result["en"])
        return 0
    
    # Tip
    if a.command == "tip":
        tip = tip_of_the_day()
        labels = _load_json("schemes_and_labels.json").get("labels", {})
        tip_label = labels.get("todays_health_tip", {})
        
        print(f"{tip_label.get('en', 'Today health tip')}:")
        print(f"\n{tip['en']}")
        print(f"\n{tip_label.get('ta', 'இன்றைய சுகாதார ஆலோசனை')}:")
        print(f"\n{tip['ta']}")
        return 0
    
    # Care finder
    if a.command == "care":
        care = care_finder()
        labels = _load_json("schemes_and_labels.json").get("labels", {})
        emergency_label = labels.get("emergency_numbers", {})
        places_label = labels.get("care_places", {})
        near_me_label = labels.get("near_me", {})
        
        print("=" * 60)
        print(f"{emergency_label.get('en', 'Emergency numbers')} / {emergency_label.get('ta', 'அவசர எண்கள்')}")
        print("=" * 60)
        for em in care["emergency"]:
            print(f"{em['number']}: {em['en']} / {em['ta']}")
        
        print()
        print("=" * 60)
        print(f"{places_label.get('en', 'Care places')} / {places_label.get('ta', 'சுகாதார நிலையங்கள்')}")
        print("=" * 60)
        for place in care["places"]:
            print(f"{place['name']} ({place['city']})")
            print(f"  {place['maps']}")
        
        print()
        print("=" * 60)
        print(f"{near_me_label.get('en', 'Near me')} / {near_me_label.get('ta', 'என் அருகில்')}")
        print("=" * 60)
        for nm in care["near_me"]:
            print(f"{nm['en']} / {nm['ta']}")
            print(f"  {nm['maps']}")
        
        return 0
    
    # Scheme
    if a.command == "scheme":
        schemes = get_scheme_guide()
        labels = _load_json("schemes_and_labels.json").get("labels", {})
        scheme_label = labels.get("health_schemes", {})
        
        print(f"{scheme_label.get('en', 'Health insurance schemes')} / {scheme_label.get('ta', 'சுகாதார காப்பீட்டு திட்டங்கள்')}")
        print()
        for scheme in schemes["schemes"]:
            print(f"\n{scheme['name_en']} / {scheme['name_ta']}")
            print(f"  {scheme['about_en']}")
            print(f"  {scheme['about_ta']}")
            print(f"  {scheme['url']}")
        
        print()
        print(f"{schemes['disclaimer_en']}")
        print(f"{schemes['disclaimer_ta']}")
        return 0
    
    # Prescription
    if a.command == "prescription":
        rx_path = Path(a.image)
        if not rx_path.exists():
            print(f"[error] Image not found: {a.image}")
            return 1
        
        print(f"[prescription] Reading {rx_path.name}...", flush=True)
        
        try:
            with open(rx_path, "rb") as f:
                image_bytes = f.read()
            
            rows = read_prescription_via_nova(image_bytes, str(rx_path))
            if not rows:
                print("[error] Could not extract medicines from prescription")
                return 1
            
            print(f"[prescription] Extracted {len(rows)} medicines", flush=True)
            print()
            print("=" * 100)
            print("MEDICINES ON THIS PRESCRIPTION")
            print("=" * 100)
            
            for i, row in enumerate(rows, 1):
                explan = get_prescription_explanation(row)
                print(f"\n{i}. {explan['en']}")
                print(f"   {explan['ta']}")
            
            print()
            print("=" * 100)
            print("DISCLAIMER:")
            print("Do not change any medicine dose yourself. Ask your pharmacist or doctor.")
            print("மருந்தின் அளவை நீங்களாக மாற்ற வேண்டாம். மருந்தாளர் அல்லது மருத்துவரிடம் கேளுங்கள்.")
            print("=" * 100)
            
            # Optionally save to profile
            if a.profile:
                confirm = get_confirmation_text(rows)
                print()
                print(confirm["en"])
                print(confirm["ta"])
                # In a real app, would prompt user for confirmation
                print("\n(Use 'med add' to add these to your profile manually)")
            
            return 0
        
        except Exception as e:
            print(f"[error] {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    # If no command recognized
    print("Usage: python -m agent.app --help")
    return 1


if __name__ == "__main__":
    sys.exit(main())
