"""AWS Lambda entry point for the Nalam AI web app (public Function URL).

Same pages and API as `python -m agent.web` (agent/web.py get_route / post_route).
Family data lives in /tmp on Lambda, so it is temporary: fine for a demo, not for real records.
Each device may send LIMIT_PER_HOUR AI requests (chat, report, prescription) an hour, to cap the cost.
"""
import base64
import os
import time

os.environ.setdefault("NALAM_DATA_DIR", "/tmp/nalam")
os.environ["TZ"] = os.environ.get("NALAM_TZ", "IST-5:30")  # medicine times, "today" and dates are India time, not UTC
time.tzset()

from agent import web  # noqa: E402

LIMIT_PER_HOUR = int(os.environ.get("LIMIT_PER_HOUR", "40"))
AI_PATHS = ("/api/chat", "/api/report", "/api/prescription")
_hits: dict[str, list[float]] = {}


def _limited(ip: str) -> bool:
    now = time.time()
    seen = [t for t in _hits.get(ip, []) if now - t < 3600]
    _hits[ip] = seen + [now]
    return len(seen) >= LIMIT_PER_HOUR


def _resp(code: int, payload: bytes, ctype: str) -> dict:
    text = ctype.startswith(("text/", "application/json"))
    return {"statusCode": code,
            "headers": {"Content-Type": ctype, "Cache-Control": "no-store"},
            "body": payload.decode("utf-8") if text else base64.b64encode(payload).decode(),
            "isBase64Encoded": not text}


def handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    method, path = http.get("method", "GET"), event.get("rawPath", "/")
    if method == "GET":
        return _resp(*web.get_route(path))
    if method == "POST":
        if path in AI_PATHS and _limited(http.get("sourceIp", "?")):
            return _resp(200, b'{"error":"server","detail":"Too many requests from this device. Please try again in an hour."}',
                         "application/json; charset=utf-8")
        raw = event.get("body") or ""
        raw = base64.b64decode(raw) if event.get("isBase64Encoded") else raw.encode("utf-8")
        return _resp(*web.post_route(path, raw))
    return _resp(405, b"method not allowed", "text/plain")
