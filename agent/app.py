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

from strands import Agent
from strands.hooks import BeforeNodeCallEvent, HookProvider, HookRegistry
from strands.models import BedrockModel
from strands.multiagent import GraphBuilder

from . import tools
from .plan import Answer, Critique

MODEL_ID = os.environ.get("SHIP_MODEL", "us.amazon.nova-2-lite-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")
logging.getLogger("strands").setLevel(logging.CRITICAL)

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
PLANNER = GOAL + " Call lookup_guidance first. Cite only ids it returns. Short sentences. Fix every problem a critic lists."
CRITIC = ("Reply ok=false with one line per problem if the answer is not in {lang}, cites an id not in {ids}, "
          "gives advice the guidance does not support, or is empty. Otherwise ok=true.")


class RedFlagGate(HookProvider):
    def __init__(self):
        self.tripped = []
        self.is_suicide = False
        self.is_diagnosis_or_dose = False

    def register_hooks(self, registry: HookRegistry, **_):
        registry.add_callback(BeforeNodeCallEvent, self._before)

    def _before(self, event: BeforeNodeCallEvent):
        text = str(event.invocation_state.get("user_text", "")).lower()
        
        # Check for emergency red flags
        hits = [p for p in RED_FLAGS if p.lower() in text]
        
        # Check for suicide/self-harm (separate handling)
        suicide_hits = [p for p in SUICIDE_PHRASES if p.lower() in text]
        
        if hits or suicide_hits:
            self.tripped = hits + suicide_hits
            if suicide_hits:
                self.is_suicide = True
            event.cancel_node = "red flag: " + ", ".join(self.tripped)
        else:
            # Check for diagnosis questions: "do i have", "am i", "if my X is Y"
            diagnosis_keywords = ["do i have", "am i", "if my", "have i got", "کیا مجھے ہے", "என்னுக்கு", "ennukku"]
            is_diagnosis = any(kw in text for kw in diagnosis_keywords)
            
            # Check for dose/medicine change requests: "can i take", "should i", "stop taking", "double", "change", "increase"
            dose_keywords = ["can i take", "should i take", "can i stop", "stop taking", "double", "change my", "increase my", "decrease my", "மாற்ற", "அளவு"]
            is_dose_change = any(kw in text for kw in dose_keywords)
            
            if is_diagnosis or is_dose_change:
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


def run(case: dict) -> dict:
    t0 = time.time()
    lang = case.get("lang") or tools.language_of(case["text"])
    gate = RedFlagGate()
    meta = {"path": "agent", "passes": 0}
    try:
        res = build_graph(lang, gate)(f"User ({lang}): {case['text']}", invocation_state={"user_text": case["text"]})
    except RuntimeError:
        if not gate.tripped and not gate.is_diagnosis_or_dose:
            raise
        res = None
    
    if gate.tripped:
        print(f"[safety] RED FLAG ({', '.join(gate.tripped)}) -> HAND OFF, agents cancelled", flush=True)
        # Emergency text (with suicide addition if needed)
        handoff_text = HANDOFF[lang]
        if gate.is_suicide:
            suicide_text = SUICIDE_EN if lang == "en" else SUICIDE_TA
            handoff_text = handoff_text + "\n\n" + suicide_text
        ans = Answer(language=lang, answer=handoff_text, steps=[], escalation=handoff_text, citations=[])
        meta["path"] = "safety/red_flag"
    elif gate.is_diagnosis_or_dose:
        print(f"[safety] DIAGNOSIS/DOSE QUESTION -> REFUSE, agents cancelled", flush=True)
        refuse_text = REFUSE_EN if lang == "en" else REFUSE_TA
        ans = Answer(language=lang, answer=refuse_text, steps=[], escalation=refuse_text, citations=[])
        meta["path"] = "safety/refuse"
    else:
        ans = res.results["planner"].result.structured_output
        if ans is None:
            raise RuntimeError("planner returned no structured answer")
        meta["passes"] = sum(1 for n in res.execution_order if n.node_id == "planner")
    meta["latency_ms"] = int((time.time() - t0) * 1000)
    print(f"[plan] {meta['path']} | {meta['latency_ms']} ms", flush=True)
    return {"plan": ans.model_dump(), "meta": meta}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m agent.app")
    ap.add_argument("text", nargs="?", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--report", help="Path to lab report (PNG/JPG/PDF) to explain")
    a = ap.parse_args(argv)
    
    if a.report:
        # Report explainer path
        from .report import read_report_via_nova, flag_rows, get_explanation_for_row, get_doctor_questions
        from pathlib import Path
        
        report_path = Path(a.report)
        if not report_path.exists():
            print(f"[error] Report not found: {a.report}")
            return 1
        
        print(f"[report] Reading {report_path.name}...", flush=True)
        
        # Read report via Nova
        try:
            with open(report_path, "rb") as f:
                image_bytes = f.read()
            
            rows = read_report_via_nova(image_bytes, str(report_path))
            if not rows:
                print("[error] Could not extract test results from report")
                return 1
            
            print(f"[report] Extracted {len(rows)} tests", flush=True)
            
            # Flag rows
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
                
                # Get explanation from glossary (code-owned, never model-generated)
                explan = get_explanation_for_row(test, value, status, unit)
                
                print(f"\n{test}:")
                print(f"  English: {explan['en']}")
                print(f"  Tamil:   {explan['ta']}")
                if not explan.get('glossary_found', True):
                    print(f"  (Note: No glossary entry found; using fallback)")
            
            print()
            print("=" * 100)
            print("QUESTIONS TO ASK YOUR DOCTOR:")
            print("=" * 100)
            
            # Get questions from glossary-based function
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
            
            return 0
        
        except Exception as e:
            print(f"[error] {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    if not a.text:
        print("Usage: python -m agent.app <message> [--json] or python -m agent.app --report <path>")
        return 1
    
    out = run({"text": a.text})
    print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else "\n" + out["plan"]["answer"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
