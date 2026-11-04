"""Family care module (Part 7c) — Profiles, medicines, appointments, reports, prep sheet.

All text and medical facts are code-owned: profiles, medicine names, doses (user-entered),
appointment records, lab report history. The model never suggests or changes doses.

Profiles and medicines are stored as JSON files in data/family/ directory.
"""
import json
import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypedDict, Optional


# On AWS Lambda the code folder is read-only, so NALAM_DATA_DIR points to /tmp there.
FAMILY_DIR = Path(os.environ["NALAM_DATA_DIR"]) if os.environ.get("NALAM_DATA_DIR") else Path(__file__).parent / "data" / "family"
FAMILY_DIR.mkdir(parents=True, exist_ok=True)

# Each phone/browser has its own private family space (a random id kept on that phone).
# The web server sets it per request with set_device(); the command line uses the shared folder.
_ctx = threading.local()


def set_device(device: str) -> None:
    d = (device or "").lower()
    _ctx.device = d if re.fullmatch(r"[a-z0-9]{12,40}", d) else ""


def _dir() -> Path:
    dev = getattr(_ctx, "device", "")
    d = FAMILY_DIR / dev if dev else FAMILY_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key(filename: str) -> str:
    dev = getattr(_ctx, "device", "")
    return f"family/{dev}/{filename}" if dev else f"family/{filename}"


# On AWS, NALAM_S3_BUCKET keeps family data permanently in S3 (Lambda's /tmp is wiped when a new copy starts).
# On a laptop it is not set, and everything stays in the folder above.
S3_BUCKET = os.environ.get("NALAM_S3_BUCKET", "")
_s3 = None


def _s3c():
    global _s3
    if _s3 is None:
        import boto3
        _s3 = boto3.client("s3")
    return _s3


def s3_put(key: str, data: bytes) -> None:
    if S3_BUCKET:
        _s3c().put_object(Bucket=S3_BUCKET, Key=key, Body=data)


def s3_get(key: str) -> bytes | None:
    if not S3_BUCKET:
        return None
    try:
        return _s3c().get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
    except Exception:  # noqa: BLE001  not there
        return None


def _pull_all() -> None:
    """Copy every saved profile from S3 into the local folder (used before listing profiles)."""
    if not S3_BUCKET:
        return
    prefix = _key("")
    resp = _s3c().list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
    for obj in resp.get("Contents", []):
        rest = obj["Key"][len(prefix):]
        if rest.endswith(".json") and "/" not in rest:   # only this phone's own files
            body = s3_get(obj["Key"])
            if body is not None:
                (_dir() / rest).write_bytes(body)


class Profile(TypedDict, total=False):
    """Profile: name, relation, age, notes."""
    name: str
    relation: str  # e.g., "Grandmother", "Grandfather", "Paati", "Thatha"
    age: int
    notes: str


class Medicine(TypedDict, total=False):
    """Medicine per profile: name, dose_text, times, start_date, end_date, food."""
    name: str
    dose_text: str  # e.g., "500 mg", "1 tablet", exactly as user entered
    times: list[str]  # e.g., ["08:00", "20:00"] — times when to take it
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD or "" if ongoing
    food: str  # "before", "after", "with", or ""
    # Adherence tracking (added by app)
    taken_log: list[dict]  # [{"time": "08:00", "date": "2026-11-04", "taken": true/false}, ...]


class Appointment(TypedDict, total=False):
    """Appointment per profile."""
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    doctor_or_hospital: str
    note: str


class LabReportResult(TypedDict, total=False):
    """Lab report result saved per profile with date."""
    date: str  # YYYY-MM-DD
    results: list[dict]  # [{"test": "HbA1c", "value": 7.5, "unit": "%", "status": "NORMAL"}, ...]


def _profile_path(name: str) -> Path:
    """Return JSON file path for profile."""
    return _dir() / f"{name.lower().replace(' ', '_')}.json"


def _load_profile(name: str) -> dict:
    """Load profile JSON. Return empty if not found."""
    path = _profile_path(name)
    remote = s3_get(_key(path.name))  # S3 is the source of truth on AWS
    if remote is not None:
        path.write_bytes(remote)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {
        "profile": {"name": name},
        "medicines": [],
        "appointments": [],
        "lab_history": []
    }


def _save_profile(name: str, data: dict):
    """Save profile JSON."""
    path = _profile_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    s3_put(_key(path.name), path.read_bytes())


def add_profile(name: str, relation: str, age: int, notes: str = "") -> dict:
    """Add a new profile. Return the profile."""
    data = _load_profile(name)
    data["profile"] = {
        "name": name,
        "relation": relation,
        "age": age,
        "notes": notes,
        "created_at": datetime.now().isoformat()
    }
    _save_profile(name, data)
    return data["profile"]


def list_profiles() -> list[str]:
    """List all profile names."""
    if not FAMILY_DIR.exists():
        return []
    _pull_all()
    return [f.stem.replace("_", " ").title() for f in _dir().glob("*.json")]


def get_profile(name: str) -> dict | None:
    """Get profile details."""
    data = _load_profile(name)
    if not data["profile"]:
        return None
    return data["profile"]


def add_medicine(name: str, medicine_name: str, dose_text: str, times: list[str],
                 start_date: str, end_date: str = "", food: str = "") -> dict:
    """Add medicine for profile. times = ["08:00", "20:00"], food = "before"/"after"/"with"."""
    data = _load_profile(name)
    med = {
        "name": medicine_name,
        "dose_text": dose_text,
        "times": times,
        "start_date": start_date,
        "end_date": end_date,
        "food": food,
        "added_at": datetime.now().isoformat(),
        "taken_log": []
    }
    data["medicines"].append(med)
    _save_profile(name, data)
    return med


def list_medicines(name: str) -> list[dict]:
    """List medicines for profile (today's active ones first)."""
    data = _load_profile(name)
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Sort: active (end_date >= today or "") first, then by start_date
    meds = data.get("medicines", [])
    active = [m for m in meds if not m.get("end_date") or m.get("end_date") >= today]
    past = [m for m in meds if m.get("end_date") and m.get("end_date") < today]
    
    active.sort(key=lambda m: m.get("start_date", ""))
    return active + past


def mark_medicine_taken(name: str, medicine_name: str, time: str, taken: bool = True):
    """Mark a medicine dose as taken or missed. time = "08:00"."""
    data = _load_profile(name)
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Find medicine
    for med in data["medicines"]:
        if med["name"].lower() == medicine_name.lower():
            # Log this dose
            log_entry = {
                "time": time,
                "date": today,
                "taken": taken,
                "logged_at": datetime.now().isoformat()
            }
            if "taken_log" not in med:
                med["taken_log"] = []
            med["taken_log"].append(log_entry)
            _save_profile(name, data)
            return log_entry
    
    return None


def adherence_percentage(name: str, days: int = 7) -> dict:
    """Compute adherence % for the last N days. Return {adherence: %, taken: int, total: int}."""
    data = _load_profile(name)
    meds = data.get("medicines", [])
    
    # Look back N days
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    total_doses = 0
    taken_doses = 0
    
    for med in meds:
        # Only count if started by now
        if med.get("start_date", "") > datetime.now().strftime("%Y-%m-%d"):
            continue
        
        # Count doses in the period
        for log in med.get("taken_log", []):
            log_date = log.get("date", "")
            if log_date >= cutoff:
                total_doses += 1
                if log.get("taken"):
                    taken_doses += 1
    
    adherence = (taken_doses / total_doses * 100) if total_doses > 0 else 0
    return {
        "adherence": round(adherence, 1),
        "taken": taken_doses,
        "total": total_doses,
        "days": days
    }


def add_appointment(name: str, date: str, time: str, doctor_or_hospital: str, note: str = "") -> dict:
    """Add appointment for profile. date = "2026-11-10", time = "10:30"."""
    data = _load_profile(name)
    appt = {
        "date": date,
        "time": time,
        "doctor_or_hospital": doctor_or_hospital,
        "note": note,
        "added_at": datetime.now().isoformat()
    }
    data["appointments"].append(appt)
    _save_profile(name, data)
    return appt


def list_appointments(name: str, upcoming_only: bool = True) -> list[dict]:
    """List appointments. If upcoming_only=True, show only future dates."""
    data = _load_profile(name)
    appts = data.get("appointments", [])
    
    if upcoming_only:
        today = datetime.now().strftime("%Y-%m-%d")
        appts = [a for a in appts if a.get("date", "") >= today]
    
    appts.sort(key=lambda a: a.get("date", ""))
    return appts


def save_lab_report(name: str, date: str, results: list[dict]):
    """Save lab report results for profile. date = "2026-11-04"."""
    data = _load_profile(name)
    
    entry = {
        "date": date,
        "results": results,
        "saved_at": datetime.now().isoformat()
    }
    if "lab_history" not in data:
        data["lab_history"] = []
    data["lab_history"].append(entry)
    _save_profile(name, data)
    return entry


def get_lab_history(name: str, test_name: str = "") -> list[dict]:
    """Get lab report history. If test_name given, filter to that test only (same unit required)."""
    data = _load_profile(name)
    history = data.get("lab_history", [])
    
    if not test_name:
        return history
    
    # Filter to test_name (case-insensitive), same unit required
    results = []
    for entry in history:
        filtered_results = []
        for result in entry.get("results", []):
            if result.get("test", "").lower() == test_name.lower():
                filtered_results.append(result)
        
        if filtered_results:
            results.append({
                "date": entry.get("date"),
                "results": filtered_results
            })
    
    return results


def compare_test_history(name: str, test_name: str) -> dict:
    """Compare a test over time. Return {test, unit, history: [{date, value, status}, ...], can_compare, reason}."""
    history = get_lab_history(name, test_name)
    
    if not history:
        return {
            "test": test_name,
            "can_compare": False,
            "reason": "No results found for this test."
        }
    
    # Check if all units match
    units = set()
    test_data = []
    
    for entry in history:
        for result in entry.get("results", []):
            units.add(result.get("unit", ""))
            test_data.append({
                "date": entry.get("date"),
                "value": result.get("value"),
                "status": result.get("status"),
                "unit": result.get("unit")
            })
    
    if len(units) > 1:
        return {
            "test": test_name,
            "can_compare": False,
            "reason": f"Units differ ({', '.join(sorted(units))}) — cannot compare."
        }
    
    return {
        "test": test_name,
        "unit": list(units)[0] if units else "",
        "can_compare": True,
        "history": sorted(test_data, key=lambda x: x["date"])
    }


def get_current_medicines_text(name: str, lang: str = "en") -> str:
    """Get formatted current medicines list for doctor prep sheet."""
    meds = list_medicines(name)
    if not meds:
        return "No current medicines." if lang == "en" else "தற்போது கொண்டு செல்லும் மருந்துகள் இல்லை."
    
    lines = []
    for med in meds:
        if med.get("end_date") and med.get("end_date") < datetime.now().strftime("%Y-%m-%d"):
            continue  # Skip past medicines
        
        times_str = ", ".join(med.get("times", []))
        food_str = f" ({med['food']})" if med.get("food") else ""
        line = f"• {med['name']}: {med['dose_text']} at {times_str}{food_str}"
        lines.append(line)
    
    return "\n".join(lines)


# ---- Added for the web app: visit history, today's doses, deletes ----

def profile_summary(name: str) -> dict:
    """Everything the web app shows for one person."""
    data = _load_profile(name)
    return {
        "profile": data.get("profile", {"name": name}),
        "medicines": list_medicines(name),
        "today": todays_doses(name),
        "adherence": adherence_percentage(name),
        "appointments": list_appointments(name, upcoming_only=False),
        "visits": sorted(data.get("visits", []), key=lambda v: v.get("date", ""), reverse=True),
        "lab_history": sorted(data.get("lab_history", []), key=lambda r: r.get("date", ""), reverse=True),
    }


def list_profiles_full() -> list[dict]:
    out = []
    _pull_all()
    for f in sorted(_dir().glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                p = json.load(fh).get("profile", {})
            if p.get("name"):
                out.append({"name": p["name"], "relation": p.get("relation", ""), "age": p.get("age", "")})
        except (OSError, ValueError):
            continue
    return out


def todays_doses(name: str) -> list[dict]:
    """Each active medicine x each time today, with taken / missed / pending status."""
    data = _load_profile(name)
    today = datetime.now().strftime("%Y-%m-%d")
    doses = []
    for med in data.get("medicines", []):
        if med.get("start_date") and med["start_date"] > today:
            continue
        if med.get("end_date") and med["end_date"] < today:
            continue
        for t in med.get("times", []):
            status = "pending"
            for log in med.get("taken_log", []):
                if log.get("date") == today and log.get("time") == t:
                    status = "taken" if log.get("taken") else "missed"
            doses.append({"medicine": med["name"], "dose_text": med.get("dose_text", ""), "time": t,
                          "food": med.get("food", ""), "status": status})
    doses.sort(key=lambda d: d["time"])
    return doses


def set_dose_status(name: str, medicine_name: str, time: str, taken: bool) -> dict | None:
    """Mark today's dose; replaces an earlier mark for the same dose (so a mis-tap can be fixed)."""
    data = _load_profile(name)
    today = datetime.now().strftime("%Y-%m-%d")
    for med in data.get("medicines", []):
        if med["name"].lower() == medicine_name.lower():
            log = [x for x in med.get("taken_log", []) if not (x.get("date") == today and x.get("time") == time)]
            entry = {"time": time, "date": today, "taken": taken, "logged_at": datetime.now().isoformat()}
            log.append(entry)
            med["taken_log"] = log
            _save_profile(name, data)
            return entry
    return None


def delete_medicine(name: str, medicine_name: str) -> bool:
    data = _load_profile(name)
    before = len(data.get("medicines", []))
    data["medicines"] = [m for m in data.get("medicines", []) if m["name"].lower() != medicine_name.lower()]
    _save_profile(name, data)
    return len(data["medicines"]) < before


def delete_appointment(name: str, index: int) -> bool:
    data = _load_profile(name)
    appts = sorted(data.get("appointments", []), key=lambda a: a.get("date", ""))
    if 0 <= index < len(appts):
        appts.pop(index)
        data["appointments"] = appts
        _save_profile(name, data)
        return True
    return False


def add_visit(name: str, date: str, doctor_or_hospital: str, symptoms: str, doctor_notes: str, photo: str = "") -> dict:
    """Save a doctor visit with a snapshot of current medicines and the last report's high/low values."""
    data = _load_profile(name)
    today = datetime.now().strftime("%Y-%m-%d")
    meds = [{"name": m["name"], "dose_text": m.get("dose_text", ""), "times": m.get("times", []), "food": m.get("food", "")}
            for m in data.get("medicines", []) if not m.get("end_date") or m["end_date"] >= today]
    last = sorted(data.get("lab_history", []), key=lambda r: r.get("date", ""))
    abnormal = []
    if last:
        abnormal = [r for r in last[-1].get("results", []) if r.get("status") in ("HIGH", "LOW")]
    visit = {"date": date or today, "doctor_or_hospital": doctor_or_hospital, "symptoms": symptoms,
             "doctor_notes": doctor_notes, "medicines": meds, "report_date": last[-1]["date"] if last else "",
             "abnormal_results": abnormal, "photo": photo, "saved_at": datetime.now().isoformat()}
    data.setdefault("visits", []).append(visit)
    _save_profile(name, data)
    return visit
