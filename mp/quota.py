"""Free-tier bookkeeping.

Gemini free quotas are per model and per day (Pacific time). We keep a small ledger in
the repository so that every run knows how many requests each model already used today,
and never keeps hammering a model that already said "daily quota finished".

Each workflow writes its own file (no merge conflicts) and reads all of them.
"""
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .core import STATE, read_json, write_json

ROLE = os.environ.get("MP_ROLE", "local")
_PT = ZoneInfo("America/Los_Angeles")
_mem = {"last_call": {}, "tokens": {}}


def _day():
    return datetime.now(_PT).strftime("%Y-%m-%d")


def _blank():
    return {"day": _day(), "requests": {}, "exhausted": {}, "video_seconds": 0}


def _mine():
    d = read_json(STATE / f"quota_{ROLE}.json") or _blank()
    return d if d.get("day") == _day() else _blank()


def _all():
    out = []
    for f in STATE.glob("quota_*.json"):
        d = read_json(f) or {}
        if d.get("day") == _day():
            out.append(d)
    return out


def _save(d):
    write_json(STATE / f"quota_{ROLE}.json", d)


def used(model):
    return sum(d.get("requests", {}).get(model, 0) for d in _all())


def add_request(model):
    d = _mine()
    d["requests"][model] = d["requests"].get(model, 0) + 1
    _save(d)


def exhausted(model):
    return any(model in d.get("exhausted", {}) for d in _all())


def mark_exhausted(model, why):
    d = _mine()
    d["exhausted"][model] = why[:120]
    _save(d)


def video_seconds():
    return sum(d.get("video_seconds", 0) for d in _all())


def add_video_seconds(n):
    d = _mine()
    d["video_seconds"] = int(d.get("video_seconds", 0) + max(0, n))
    _save(d)


def summary():
    req, exh = {}, {}
    for d in _all():
        for m, n in d.get("requests", {}).items():
            req[m] = req.get(m, 0) + n
        exh.update(d.get("exhausted", {}))
    return {"requests": req, "exhausted": exh, "video_hours": round(video_seconds() / 3600, 2)}


# ---------------------------------------------------------------- pacing (in memory)
def pace(model, min_gap, est_tokens=0, tpm=220_000):
    """Sleep just enough to respect requests-per-minute and tokens-per-minute."""
    wait = _mem["last_call"].get(model, 0) + min_gap - time.time()
    if est_tokens:
        window = [(t, n) for t, n in _mem["tokens"].get(model, []) if time.time() - t < 62]
        _mem["tokens"][model] = window
        total = sum(n for _, n in window)
        if window and total + est_tokens > tpm:
            wait = max(wait, window[0][0] + 62 - time.time())
    if wait > 0:
        time.sleep(min(wait, 75))
    _mem["last_call"][model] = time.time()


def spent_tokens(model, n):
    if n:
        _mem["tokens"].setdefault(model, []).append((time.time(), n))
