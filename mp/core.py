"""Shared basics: config, paths, time, JSON files, text cleaning."""
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE = DATA / "state"
NOTES = DATA / "notes"          # one JSON per analysed video
NEWS = DATA / "news"            # one JSON per day
SCRIPTS = DATA / "scripts"      # saved scripts (checkpoints)
OUT = ROOT / "output"           # rendered media, never committed
ASSETS = ROOT / "assets"

CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
TZ = ZoneInfo(CFG.get("timezone", "Europe/Rome"))
UTC = timezone.utc


def now():
    return datetime.now(UTC)


def local_day(offset_days=0):
    return (datetime.now(TZ) + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def parse_iso(s):
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except Exception:
        return None


def log(*a):
    print(*a, flush=True)


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"  file illeggibile {p.name}: {e}")
        return default


def write_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def slug(s, n=40):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()[:n] or "x"


_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF\U0000200D\U000025A0-\U000025FF\U00002300-\U000023FF]")


def clean(s):
    """Text safe to draw and to speak: no emoji, no markdown, single spaces."""
    s = _EMOJI.sub(" ", str(s or ""))
    s = s.replace("**", "").replace("__", "").replace("`", "")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("—", " - ").replace("–", "-").replace("…", "...")
    s = s.replace("‼", "!").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def secret(name):
    return (os.environ.get(name) or "").strip()


def fatal(msg):
    log(f"ERRORE: {msg}")
    sys.exit(1)


def clock(**updates):
    """Small shared memory of when things last ran (read by scripts/due.py)."""
    c = read_json(STATE / "clock.json", {}) or {}
    if updates:
        c.update(updates)
        write_json(STATE / "clock.json", c)
    return c
