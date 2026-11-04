"""Nalam AI web app server (standard library only, nothing extra to install).

    python -m agent.web                 # http://127.0.0.1:8000
    python -m agent.web --host 0.0.0.0  # reachable from a phone on the same Wi-Fi

The browser page is web/index.html. Every answer passes through agent/safety.py first (code, no model),
then fixed-content routes (word meaning, myths, care, schemes), and only then the Strands agent on Bedrock.
Report and prescription photos: Nova only reads the text; code decides HIGH/LOW and all explanations
come from agent/data/*.json.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import time
import traceback
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import family
from .features import care_finder, myth_buster, tip_of_the_day, word_bridge
from .safety import classify

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DATA = Path(__file__).resolve().parent / "data"


def _json(name: str) -> dict:
    with open(DATA / name, encoding="utf-8") as f:
        return json.load(f)


ABBR = _json("med_abbreviations.json")
GLOSSARY = _json("lab_glossary.json")
MYTHS = _json("myths.json")
SCHEMES = _json("schemes_and_labels.json")
MEDS = _json("medicines.json")

MEANING_CUES = ["enna", "na enna", "meaning", "what is", "what does", "endral", "means", "என்ன", "அர்த்தம்", "என்றால்"]
MYTH_CUES = ["true", "unmai", "unmaiya", "உண்மை", "myth", "is it ok", "is it safe", "sariya", "சரியா", "nijama", "really"]
CARE_CUES = ["hospital", "phc", "pharmacy", "medical shop", "clinic", "aspathiri", "aspatri", "jan aushadhi",
             "மருத்துவமனை", "மருந்தகம்", "மருந்துக் கடை", "near me", "nearby", "pakkathula"]
SCHEME_CUES = ["scheme", "insurance", "cmchis", "ayushman", "vay vandana", "pmjay", "pm-jay", "காப்பீடு", "திட்டம்", "kaapeedu"]


def _word(term: str, text: str) -> bool:
    t = term.lower()
    if t.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", text) is not None
    return t in text


# ---------------- chat ----------------

def find_medicine(name: str) -> dict | None:
    t = (name or "").lower()
    best = None
    for m in MEDS["medicines"]:
        for a in m["aliases"]:
            if _word(a, t) and (best is None or len(a) > len(best[1])):
                best = (m, a)
    return best[0] if best else None


def medicine_answer(med: dict, profile: str) -> dict:
    out = {"type": "medicine", "name": med["name"], "use_en": med["en"], "use_ta": med["ta"], "person": profile,
           "source": med.get("source", ""),
           "how_en": MEDS["not_saved"]["en"], "how_ta": MEDS["not_saved"]["ta"], "saved": False}
    if profile:
        for m in family.list_medicines(profile):
            hit = find_medicine(m["name"])
            if (hit and hit["name"] == med["name"]) or med["name"].lower() in m["name"].lower():
                times = m.get("times", [])
                food_en = {"after": ", after food", "before": ", before food"}.get(m.get("food", ""), "")
                food_ta = {"after": ", சாப்பாட்டுக்குப் பின்", "before": ", சாப்பாட்டுக்கு முன்"}.get(m.get("food", ""), "")
                out.update(saved=True, times=times,
                           how_en=f"{profile} takes it {len(times)} time{'s' if len(times) != 1 else ''} a day: {', '.join(times)}{food_en}.",
                           how_ta=f"{profile} ஒரு நாளைக்கு {len(times)} முறை எடுக்கிறார்: {', '.join(times)}{food_ta}.")
                break
    return out


def route(text: str, profile: str = "") -> dict | None:
    t = text.lower()
    text = text or ""
    med = find_medicine(t)
    if med:
        return medicine_answer(med, profile)
    short = len(t.split()) <= 3
    if short or any(c in t for c in MEANING_CUES):
        for item in ABBR.get("items", []):
            for term in [item["abbr"], *item.get("alt", [])]:
                if _word(term, t):
                    return {"type": "word", "term": item["abbr"], "en": item["en"], "ta": item["ta"],
                            "how_en": item.get("how_en", ""), "how_ta": item.get("how_ta", "")}
        best = None
        for test in GLOSSARY.get("tests", []):
            for alias in test.get("aliases", []):
                if len(alias) >= 3 and _word(alias, t) and (best is None or len(alias) > len(best[1])):
                    best = (test, alias)
        if best:
            m = re.search(re.escape(best[1]), text, re.I)
            return {"type": "word", "term": m.group(0) if m else best[1],
                    "en": best[0]["en"], "ta": best[0]["ta"]}
    hits = []
    for item in MYTHS.get("items", []):
        n = sum(1 for k in item.get("keys", []) if _word(k, t))
        if n:
            hits.append((n, item))
    if hits:
        hits.sort(key=lambda x: -x[0])
        n, item = hits[0]
        if n >= 2 or any(c in t for c in MYTH_CUES):
            return {"type": "myth", **_myth_payload(item)}
    if any(c in t for c in SCHEME_CUES) or ("70" in t and any(w in t for w in ("age", "vayasu", "வயது"))):
        return scheme_answer(t)
    if any(c in t for c in CARE_CUES):
        return {"type": "care"}
    return None


def scheme_answer(t: str) -> dict:
    """Rules for the scheme(s) the person asked about, from schemes_and_labels.json. Never says 'you are eligible'."""
    all_ = SCHEMES.get("schemes", [])
    want = [x for x in all_ if (x["id"] == "cmchis" and any(w in t for w in ("cmchis", "chief minister", "முதலமைச்சர்")))
            or (x["id"] == "vayvandana" and any(w in t for w in ("vay vandana", "ayushman", "pmjay", "pm-jay", "70", "முதியோ", "elder", "senior", "old age")))]
    out = []
    for x in want or all_:
        rules_en = " ".join(r["en"] for r in x["rules"])
        rules_ta = " ".join(r["ta"] for r in x["rules"])
        docs_en = ", ".join(d["en"] for d in x["documents"])
        docs_ta = ", ".join(d["ta"] for d in x["documents"])
        out.append({"id": x["id"], "url": x.get("url", ""),
                    "en": f"{x['name_en']}: {x['en']} Rules: {rules_en} Documents: {docs_en}. Where: {x['where']['en']}",
                    "ta": f"{x['name_ta']}: {x['ta']} விதிகள்: {rules_ta} ஆவணங்கள்: {docs_ta}. எங்கே: {x['where']['ta']}"})
    note = {"en": "Only the official office can confirm if you qualify.",
            "ta": "நீங்கள் தகுதியானவரா என்பதை அரசு அலுவலகம் மட்டுமே உறுதிப்படுத்த முடியும்."}
    return {"type": "scheme", "schemes": out,
            "en": " ".join(o["en"] for o in out) + " " + note["en"], "ta": " ".join(o["ta"] for o in out) + " " + note["ta"]}


def _myth_payload(item: dict) -> dict:
    v = SCHEMES["labels"].get(item["verdict"], {"en": item["verdict"], "ta": item["verdict"]})
    return {"id": item["id"], "myth_en": item["myth_en"], "myth_ta": item["myth_ta"], "verdict": item["verdict"],
            "verdict_en": v["en"], "verdict_ta": v["ta"], "en": item["en"], "ta": item["ta"],
            "source": item.get("source", "")}


def chat(text: str, lang: str, profile: str = "") -> dict:
    t0 = time.time()
    text = (text or "").strip()
    if not text:
        return {"type": "empty"}
    verdict = classify(text)
    if verdict["kind"] and verdict["kind"] != "warn":
        return {"type": verdict["kind"], "en": verdict["en"], "ta": verdict["ta"], "hits": verdict["hits"],
                "ms": int((time.time() - t0) * 1000), "path": "safety"}
    # "warn": a warning sign came up in a normal chat -> keep answering, but put the warning on top.
    warn = {"en": verdict["en"], "ta": verdict["ta"], "hits": verdict["hits"]} if verdict["kind"] == "warn" else None
    routed = route(text, profile)
    if routed:
        routed.update({"ms": int((time.time() - t0) * 1000), "path": "router", "warn": warn})
        return routed
    from .app import run  # loads Strands + Bedrock only when needed
    try:
        out = run({"text": text, "lang": "ta" if lang == "ta" else "en", "skip_warn": True})
    except Exception:
        if not warn:
            raise
        # The model failed, but a warning sign was mentioned: never lose the warning.
        return {"type": "answer", "warn": warn, "answer": "", "steps": [], "escalation": "",
                "note_en": "I could not answer the rest right now. Please ask your doctor.",
                "note_ta": "மீதியை இப்போது பதில் சொல்ல முடியவில்லை. மருத்துவரிடம் கேளுங்கள்.",
                "ms": int((time.time() - t0) * 1000), "path": "safety/warn"}
    plan = out["plan"]
    return {"type": "answer", "warn": warn, "lang": plan.get("language", lang), "answer": plan.get("answer", ""),
            "steps": plan.get("steps", []), "escalation": plan.get("escalation", ""),
            "note_en": "General information only. Please ask your doctor about your own health.",
            "note_ta": "இது பொதுவான தகவல் மட்டுமே. உங்கள் உடல்நிலை பற்றி மருத்துவரிடம் கேளுங்கள்.",
            "ms": out["meta"].get("latency_ms"), "path": out["meta"].get("path")}


# ---------------- input checks (dates, times, photos) ----------------

class Invalid(ValueError):
    """Bad user input: shown to the user as a friendly message, not a crash."""


def _norm_times(times) -> list[str]:
    out = []
    for x in times or []:
        m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(x))
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            raise Invalid("bad_time")
        out.append(f"{int(m.group(1)):02d}:{m.group(2)}")
    return out


def _check_date(d: str, *, future_ok: bool, past_ok: bool, time_: str = "") -> str:
    try:
        day = datetime.strptime((d or "").strip(), "%Y-%m-%d")
    except ValueError:
        raise Invalid("bad_date")
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    ds = day.strftime("%Y-%m-%d")
    if not past_ok and ds < today:
        raise Invalid("past_date")
    if not past_ok and ds == today and time_ and _norm_times([time_])[0] < now.strftime("%H:%M"):
        raise Invalid("past_time")
    if not future_ok and ds > today:
        raise Invalid("future_date")
    return ds


PHOTOS = family.FAMILY_DIR / "photos"


def _save_photo(data_url: str) -> str:
    if not data_url:
        return ""
    head, _, b64 = data_url.partition(",")
    ext = "pdf" if "pdf" in head else "jpg"
    raw = base64.b64decode(b64)
    if len(raw) > 6_000_000:
        raise Invalid("too_big")
    PHOTOS.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    (PHOTOS / name).write_bytes(raw)
    family.s3_put(f"photos/{name}", raw)  # kept permanently on AWS
    return name


# ---------------- report ----------------

def explain_report(filename: str, raw: bytes, profile: str = "") -> dict:
    from .report import flag_rows, get_doctor_questions, get_glossary_entry, get_status_word, read_report_via_nova
    rows = read_report_via_nova(raw, filename)
    flagged = flag_rows(rows)
    out_rows = []
    for r in flagged:
        status = r.get("status", "UNKNOWN")
        key = status if status in ("HIGH", "LOW", "NORMAL") else "UNKNOWN"
        entry = get_glossary_entry(r.get("test", ""))
        sw = get_status_word(key)
        row = {"test": r.get("test"), "value": r.get("value"), "unit": r.get("unit", ""), "range": r.get("range_text", ""),
               "range_source": r.get("range_source", ""), "status": key, "status_en": sw["en"], "status_ta": sw["ta"],
               "note_en": r.get("note", ""), "note_ta": "", "what_en": "", "what_ta": "", "warn": None, "source": ""}
        if r.get("range_source") == "fallback":
            row["note_ta"] = "இந்த அறிக்கையில் வரம்பு அச்சிடப்படவில்லை; பொதுவான வரம்பைப் பயன்படுத்தினோம். மருத்துவரிடம் கேளுங்கள்."
        elif r.get("range_source") == "unknown":
            row["note_ta"] = "இந்தப் பரிசோதனைக்கான வரம்பு கிடைக்கவில்லை. மருத்துவரிடம் கேளுங்கள்."
        if entry:
            row["what_en"], row["what_ta"] = entry["en"], entry["ta"]
            row["source"] = entry.get("source", "")
            if key == "HIGH" and entry.get("warn_high"):
                row["warn"] = entry["warn_high"]
            if key == "LOW" and entry.get("warn_low"):
                row["warn"] = entry["warn_low"]
        else:
            row["what_en"] = "Ask your doctor what this test means."
            row["what_ta"] = "இந்தப் பரிசோதனை என்ன என்று மருத்துவரிடம் கேளுங்கள்."
        out_rows.append(row)
    order = {"HIGH": 0, "LOW": 0, "UNKNOWN": 1, "NORMAL": 2}
    out_rows.sort(key=lambda x: order.get(x["status"], 3))
    questions = get_doctor_questions(flagged)
    saved = False
    if profile:
        family.save_lab_report(profile, datetime.now().strftime("%Y-%m-%d"),
                               [{"test": r["test"], "value": r["value"], "unit": r["unit"], "status": r["status"]} for r in out_rows])
        saved = True
    return {"rows": out_rows, "questions": questions, "saved_to": profile if saved else "",
            "counts": {k: sum(1 for r in out_rows if r["status"] == k) for k in ("HIGH", "LOW", "NORMAL", "UNKNOWN")},
            "disclaimer": {"en": "This is only an explanation, not a diagnosis. Please show this report to your doctor.",
                           "ta": "இது ஒரு விளக்கம் மட்டுமே, நோய் கண்டறிதல் அல்ல. உங்கள் மருத்துவரிடம் காட்டுங்கள்."}}


# ---------------- prescription ----------------

def _suggest_times(freq: str) -> list[str]:
    f = (freq or "").upper().replace(" ", "")
    m = re.search(r"(\d)-(\d)-(\d)", f)
    if m:
        slots = ["08:00", "13:00", "20:00"]
        return [s for s, n in zip(slots, m.groups()) if n != "0"]
    for keys, times in ((("QID", "QDS"), ["08:00", "12:00", "16:00", "20:00"]), (("TDS", "TID"), ["08:00", "14:00", "20:00"]),
                        (("BD", "BID"), ["08:00", "20:00"]), (("OD",), ["08:00"]), (("HS",), ["21:00"])):
        if any(re.search(r"(?<![A-Z])" + k + r"(?![A-Z])", f) for k in keys):
            return times
    return []


def _food(text: str) -> str:
    t = (text or "").upper()
    if re.search(r"(?<![A-Z])PC(?![A-Z])|AFTER", t):
        return "after"
    if re.search(r"(?<![A-Z])AC(?![A-Z])|BEFORE", t):
        return "before"
    return ""


def explain_prescription(filename: str, raw: bytes) -> dict:
    from .prescription import get_prescription_explanation, read_prescription_via_nova
    rows = read_prescription_via_nova(raw, filename)
    out = []
    for r in rows:
        exp = get_prescription_explanation(r)
        unsure = (not r.get("legible", True)) or "pharmacist" in exp["en"].lower()
        med = find_medicine(r.get("medicine_name", ""))
        use = {"en": med["en"], "ta": med["ta"]} if med else None
        out.append({"name": r.get("medicine_name", ""), "dose": r.get("dose_text", ""), "frequency": r.get("frequency_text", ""),
                    "duration": r.get("duration_text", ""), "food_raw": r.get("food_text", ""), "en": exp["en"], "ta": exp["ta"],
                    "unsure": unsure, "times": _suggest_times(r.get("frequency_text", "")),
                    "food": _food(r.get("food_text", "") + " " + r.get("frequency_text", "")),
                    "use_en": use["en"] if use else "", "use_ta": use["ta"] if use else ""})
    return {"rows": out, "disclaimer": {"en": "Do not change any medicine dose yourself. Ask your pharmacist or doctor.",
                                       "ta": "மருந்தின் அளவை நீங்களாக மாற்ற வேண்டாம். மருந்தாளர் அல்லது மருத்துவரிடம் கேளுங்கள்."}}


# ---------------- voice backup (for devices with no Tamil voice) ----------------

def tts(text: str, lang: str) -> dict:
    """Make an MP3 with gTTS (pip install gTTS). Used only when the browser has no voice for that language."""
    try:
        from gtts import gTTS
    except ImportError:
        return {"error": "no_tts", "detail": "Run: pip install gTTS"}
    import io
    buf = io.BytesIO()
    gTTS(text[:1500], lang="ta" if lang == "ta" else "en", tld="co.in").write_to_fp(buf)
    return {"audio": "data:audio/mpeg;base64," + base64.b64encode(buf.getvalue()).decode()}


# ---------------- HTTP ----------------

def bootstrap() -> dict:
    return {"tip": tip_of_the_day(), "care": care_finder(), "schemes": SCHEMES["schemes"], "scheme_footer": SCHEMES["footer"],
            "labels": SCHEMES["labels"], "myths": [_myth_payload(m) for m in MYTHS.get("items", [])],
            "words": ABBR.get("items", []), "profiles": family.list_profiles_full()}


def handle_api(path: str, body: dict) -> dict:
    p = body.get("profile", "")
    if path == "/api/bootstrap":
        return bootstrap()
    if path == "/api/chat":
        return chat(body.get("text", ""), body.get("lang", "ta"), body.get("profile", ""))
    if path == "/api/safety":
        return classify(body.get("text", ""))
    if path in ("/api/report", "/api/prescription"):
        raw = base64.b64decode(body.get("data", "").split(",")[-1])
        if len(raw) > 6_000_000:
            return {"error": "too_big"}
        name = body.get("filename", "photo.jpg")
        return explain_report(name, raw, p) if path == "/api/report" else explain_prescription(name, raw)
    if path == "/api/profiles":
        return {"profiles": family.list_profiles_full()}
    if path == "/api/profile/add":
        family.add_profile(body["name"].strip(), body.get("relation", ""), int(body.get("age") or 0))
        return {"profiles": family.list_profiles_full()}
    if path == "/api/profile/get":
        return family.profile_summary(p)
    if path == "/api/med/add":
        family.add_medicine(p, body["name"].strip(), body.get("dose", ""), _norm_times(body.get("times", [])),
                            body.get("start") or datetime.now().strftime("%Y-%m-%d"), body.get("end", ""), body.get("food", ""))
        return family.profile_summary(p)
    if path == "/api/med/delete":
        family.delete_medicine(p, body["name"])
        return family.profile_summary(p)
    if path == "/api/dose":
        family.set_dose_status(p, body["name"], body["time"], bool(body.get("taken")))
        return family.profile_summary(p)
    if path == "/api/appt/add":
        t_ = _norm_times([body["time"]])[0] if body.get("time") else ""
        d_ = _check_date(body.get("date", ""), future_ok=True, past_ok=False, time_=t_)
        family.add_appointment(p, d_, t_, body.get("where", ""), body.get("note", ""))
        return family.profile_summary(p)
    if path == "/api/appt/delete":
        family.delete_appointment(p, int(body["index"]))
        return family.profile_summary(p)
    if path == "/api/visit/add":
        d_ = _check_date(body.get("date") or datetime.now().strftime("%Y-%m-%d"), future_ok=False, past_ok=True)
        family.add_visit(p, d_, body.get("where", ""), body.get("symptoms", ""), body.get("notes", ""),
                         photo=_save_photo(body.get("photo", "")))
        return family.profile_summary(p)
    if path == "/api/tts":
        return tts(body.get("text", ""), body.get("lang", "ta"))
    if path == "/api/history":
        return family.compare_test_history(p, body.get("test", ""))
    return {"error": "not_found"}


def get_route(path: str) -> tuple[int, bytes, str]:
    """GET pages and files. Shared by the local server and the AWS Lambda entry point."""
    if path in ("/", "/index.html"):
        return 200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8"
    if path == "/manifest.json":
        return 200, (WEB / "manifest.json").read_bytes(), "application/json"
    if path.startswith("/photo/"):
        name = path.rsplit("/", 1)[-1]
        f = PHOTOS / name
        if re.fullmatch(r"[0-9a-f]{32}\.(jpg|pdf)", name) and not f.exists():
            remote = family.s3_get(f"photos/{name}")
            if remote is not None:
                PHOTOS.mkdir(parents=True, exist_ok=True)
                f.write_bytes(remote)
        if re.fullmatch(r"[0-9a-f]{32}\.(jpg|pdf)", name) and f.exists():
            return 200, f.read_bytes(), "application/pdf" if name.endswith("pdf") else "image/jpeg"
        return 404, b"not found", "text/plain"
    if path == "/api/bootstrap":
        return 200, json.dumps(bootstrap(), ensure_ascii=False).encode(), "application/json; charset=utf-8"
    return 404, b"not found", "text/plain"


def post_route(path: str, raw: bytes) -> tuple[int, bytes, str]:
    """POST /api/... Shared by the local server and the AWS Lambda entry point."""
    try:
        body = json.loads(raw or b"{}")
        family.set_device(body.get("device", ""))  # each phone only sees its own family
        result = handle_api(path, body)
        code = 404 if result.get("error") == "not_found" else 200
    except Invalid as bad:
        result, code = {"error": "invalid", "detail": str(bad)}, 200
    except Exception as exc:  # show a friendly message in the app, full error in the log
        traceback.print_exc()
        result, code = {"error": "server", "detail": str(exc)[:300]}, 200
    return code, json.dumps(result, ensure_ascii=False).encode(), "application/json; charset=utf-8"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._send(*get_route(self.path.split("?")[0]))

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        self._send(*post_route(self.path.split("?")[0], self.rfile.read(n)))

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            print("[web]", args[0], flush=True)


def main():
    ap = argparse.ArgumentParser(prog="python -m agent.web")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    print(f"Nalam AI running: open http://{'localhost' if a.host in ('127.0.0.1', '0.0.0.0') else a.host}:{a.port}", flush=True)
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
