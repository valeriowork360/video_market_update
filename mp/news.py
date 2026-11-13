"""Market context from free, reliable sources: news RSS, verified prices, economic calendar."""
import calendar
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import feedparser
import requests

from .core import CFG, NEWS, UTC, clean, log, now, parse_iso, read_json, write_json

N = CFG["news"]
_HEAD = {"User-Agent": "Mozilla/5.0 (compatible; MarketPulseBot/1.0)"}


def _key(title):
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:70]


def fetch_feeds():
    """Read every feed and merge the new headlines into today's file. Returns how many were added."""
    path = NEWS / f"{now().strftime('%Y-%m-%d')}.json"
    items = read_json(path, [])
    seen = {_key(i["title"]) for i in items}
    added = 0
    for f in N["feeds"]:
        try:
            r = requests.get(f["url"], timeout=30, headers=_HEAD)
            r.raise_for_status()
            d = feedparser.parse(r.content)
        except Exception as e:
            log(f"  notizie {f['name']}: non lette ({str(e)[:70]})")
            continue
        n = 0
        for e in d.entries[:25]:
            title = clean(e.get("title", ""))
            if not title or _key(title) in seen:
                continue
            ts = e.get("published_parsed") or e.get("updated_parsed")
            pub = datetime.fromtimestamp(calendar.timegm(ts), UTC) if ts else now()
            if now() - pub > timedelta(hours=N["max_age_hours"]):
                continue
            summary = clean(re.sub(r"<[^>]+>", " ", e.get("summary", "")))[:260]
            items.append({"title": title, "summary": summary, "source": f["name"],
                          "link": e.get("link", ""), "published": pub.isoformat(),
                          "scope": f.get("scope", "global")})
            seen.add(_key(title))
            n += 1
        added += n
        log(f"  notizie {f['name']}: +{n}")
    write_json(path, items)
    return added


def recent(hours, lang):
    """Headlines of the last `hours`, newest first. English edition skips Italy-only feeds."""
    cut = now() - timedelta(hours=hours)
    out, seen = [], set()
    for f in sorted(NEWS.glob("*.json"), reverse=True)[: hours // 24 + 2]:
        for it in read_json(f, []):
            pub = parse_iso(it.get("published")) or now()
            if pub < cut or _key(it["title"]) in seen:
                continue
            if lang != "it" and it.get("scope") == "italy":
                continue
            seen.add(_key(it["title"]))
            out.append(it)
    out.sort(key=lambda i: i.get("published", ""), reverse=True)
    return out


def snapshot():
    """Verified prices: last close, 1-day and 5-day change. Empty list if Yahoo is unreachable."""
    out = []
    try:
        import yfinance as yf
    except Exception:
        return out
    for m in CFG.get("market", []):
        try:
            h = yf.Ticker(m["symbol"]).history(period="1mo", interval="1d")["Close"].dropna()
            if len(h) < 6:
                continue
            last, prev, wk = float(h.iloc[-1]), float(h.iloc[-2]), float(h.iloc[-6])
            out.append({"name": m["name"], "symbol": m["symbol"], "last": round(last, 4 if last < 10 else 2),
                        "change_1d_pct": round((last / prev - 1) * 100, 2),
                        "change_5d_pct": round((last / wk - 1) * 100, 2),
                        "as_of": str(h.index[-1].date())})
        except Exception as e:
            log(f"  prezzo {m['symbol']}: non letto ({str(e)[:60]})")
    log(f"  prezzi verificati: {len(out)}/{len(CFG.get('market', []))}")
    return out


def history(symbol, period="3mo"):
    """Closing prices for a chart, or None."""
    if os.environ.get("MP_FAKE_PRICES"):        # offline tests only
        import random
        r = random.Random(symbol)
        v, out = 100.0, []
        for _ in range(64):
            v *= 1 + r.uniform(-0.022, 0.026)
            out.append(v)
        return out
    try:
        import yfinance as yf
        h = yf.Ticker(symbol).history(period=period, interval="1d")["Close"].dropna()
        return [float(x) for x in h.tolist()] if len(h) >= 10 else None
    except Exception:
        return None


def calendar_events():
    """High/medium-impact economic events from now to the end of the week."""
    url = N.get("calendar_url")
    if not url:
        return []
    try:
        data = requests.get(url, timeout=30, headers=_HEAD).json()
    except Exception as e:
        log(f"  calendario economico: non letto ({str(e)[:70]})")
        return []
    out = []
    for ev in data:
        if ev.get("country") not in N.get("calendar_currencies", ["USD", "EUR"]):
            continue
        if ev.get("impact") not in ("High", "Medium"):
            continue
        when = parse_iso(ev.get("date"))
        if not when or when < now() - timedelta(hours=6):
            continue
        out.append({"event": clean(ev.get("title", "")), "currency": ev["country"],
                    "impact": ev["impact"],
                    "when_rome": when.astimezone(ZoneInfo("Europe/Rome")).strftime("%a %d %b %H:%M"),
                    "when_new_york": when.astimezone(ZoneInfo("America/New_York")).strftime("%a %d %b %H:%M"),
                    "forecast": ev.get("forecast", ""), "previous": ev.get("previous", ""),
                    "_t": when.timestamp()})
    out.sort(key=lambda e: (e["impact"] != "High", e["_t"]))
    out = out[:14]
    out.sort(key=lambda e: e.pop("_t"))
    log(f"  calendario economico: {len(out)} eventi in arrivo")
    return out
