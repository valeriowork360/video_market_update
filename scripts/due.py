#!/usr/bin/env python3
"""Decides what is due right now. Standard library only, so a tick with nothing to do costs seconds.

GitHub's scheduler is often hours late and skips runs, so nothing here depends on *which*
cron slot fired: every tick looks at the clock and at what has already been done.

Prints GitHub step outputs:  work, collect, produce (daily|weekly|''), day
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def setting(text, key, default):
    m = re.search(rf"^\s*{key}:\s*\"?([^\"#\n]+?)\"?\s*(?:#.*)?$", text, re.M)
    return m.group(1).strip() if m else default


def load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def hhmm(s):
    h, m = s.split(":")
    return int(h), int(m)


def age_minutes(iso, now):
    try:
        t = datetime.fromisoformat(iso)
        return (now - t).total_seconds() / 60
    except Exception:
        return 10 ** 9


def complete(produced, key, langs):
    rec = produced.get(key, {}).get("langs", {})
    return all(rec.get(l, {}).get("long") and rec.get(l, {}).get("social") for l in langs)


def decide(now_utc, cfg_text, clock, produced):
    tz = ZoneInfo(setting(cfg_text, "timezone", "Europe/Rome"))
    langs = [x.strip() for x in setting(cfg_text, "languages", "[it, en]").strip("[]").split(",")]
    every = float(setting(cfg_text, "collect_every_hours", "4"))
    late = float(setting(cfg_text, "late_hours", "9"))
    now = now_utc.astimezone(tz)
    out = {"collect": False, "produce": "", "day": ""}
    retry_ok = age_minutes(clock.get("last_produce_try", ""), now_utc) >= 40

    def window(day, at):
        """True if `now` is between that day's start time and start + late hours."""
        h, m = hhmm(at)
        start = datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
        return start <= now <= start + timedelta(hours=late)

    # daily: today's window, or yesterday's if we are still inside its late tail
    for day in (now.date(), now.date() - timedelta(days=1)):
        if window(day, setting(cfg_text, "daily_time", "17:30")):
            key = f"{day}_daily"
            if not complete(produced, key, langs) and retry_ok:
                out.update(produce="daily", day=str(day))
            break
    # weekly: only once the daily of that moment is out of the way
    if not out["produce"]:
        wd = DAYS.index(setting(cfg_text, "weekly_day", "sunday").lower())
        for day in (now.date(), now.date() - timedelta(days=1)):
            if day.weekday() == wd and window(day, setting(cfg_text, "weekly_time", "19:00")):
                if not complete(produced, f"{day}_weekly", langs) and retry_ok:
                    out.update(produce="weekly", day=str(day))
                break
    since_ok = age_minutes(clock.get("last_collect_ok", ""), now_utc)
    since_try = age_minutes(clock.get("last_collect_try", ""), now_utc)
    if since_try >= 40 and (since_ok >= every * 60 - 10 or (out["produce"] == "daily" and since_ok >= 90)):
        out["collect"] = True
    out["work"] = bool(out["collect"] or out["produce"])
    return out


if __name__ == "__main__":
    d = decide(datetime.now(timezone.utc), (ROOT / "config.yaml").read_text(encoding="utf-8"),
               load(ROOT / "data/state/clock.json", {}), load(ROOT / "data/state/produced.json", {}))
    for k, v in d.items():
        print(f"{k}={str(v).lower() if isinstance(v, bool) else v}")
    print(f"decisione: {d}", file=sys.stderr)
