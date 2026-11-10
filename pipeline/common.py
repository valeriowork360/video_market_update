"""Shared helpers: config, paths, Gemini client, JSON I/O."""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
NOTES = DATA / "notes"      # one JSON per analysed video
NEWS = DATA / "news"        # one JSON per collect run
OUT = ROOT / "output"       # rendered media (not committed)
STATE = DATA / "seen.json"  # video ids already processed

CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def now():
    return datetime.now(timezone.utc)


def today_str(offset_days=0):
    return (now() + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def slug(s, n=40):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:n] or "x"


# ---------------------------------------------------------------- Gemini
_client = None


def gemini():
    global _client
    if _client is None:
        from google import genai
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise SystemExit("GEMINI_API_KEY mancante (aggiungila nei Secrets di GitHub)")
        _client = genai.Client(api_key=key)
    return _client


def ask_json(prompt, video_url=None, retries=3):
    """Ask Gemini and return parsed JSON. Optionally attach a YouTube URL."""
    from google.genai import types
    parts = []
    if video_url:
        parts.append(types.Part(file_data=types.FileData(file_uri=video_url)))
    parts.append(types.Part(text=prompt))
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.6,
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW if video_url else None,
    )
    last = None
    for i in range(retries):
        try:
            r = gemini().models.generate_content(
                model=CFG["model"], contents=[types.Content(role="user", parts=parts)], config=cfg)
            txt = r.text.strip()
            txt = re.sub(r"^```(json)?|```$", "", txt).strip()
            return json.loads(txt)
        except Exception as e:  # rate limits on free tier -> wait and retry
            last = e
            print(f"  Gemini errore ({e}); riprovo tra {30 * (i + 1)}s")
            time.sleep(30 * (i + 1))
    raise RuntimeError(f"Gemini fallito: {last}")


def notes_between(start_date, end_date):
    """All video notes with folder date in [start_date, end_date]."""
    out = []
    if not NOTES.exists():
        return out
    for d in sorted(NOTES.iterdir()):
        if start_date <= d.name <= end_date:
            for f in sorted(d.glob("*.json")):
                out.append(read_json(f))
    return out


def news_between(start_date, end_date, limit=60):
    items, seen = [], set()
    if not NEWS.exists():
        return items
    for f in sorted(NEWS.glob("*.json"), reverse=True):
        if start_date <= f.name[:10] <= end_date:
            for it in read_json(f, []):
                if it["title"] not in seen:
                    seen.add(it["title"])
                    items.append(it)
    return items[:limit]
