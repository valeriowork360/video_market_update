"""New videos of a channel, without API keys.

Two independent sources, because each one fails now and then from cloud servers:
  1. the channel pages (/videos and /streams): ids, titles, length, rough age, live status
  2. the public RSS feed: exact publication time
If one is down the other is enough.
"""
import calendar
import json
import re
from datetime import datetime, timedelta

import feedparser
import requests

from .core import STATE, UTC, clean, log, now, read_json, write_json

_HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
         "Accept-Language": "en-US,en;q=0.8"}
_COOKIES = {"CONSENT": "YES+1", "SOCS": "CAI"}
_UNIT = {"s": 1, "m": 60, "min": 60, "h": 3600, "d": 86400, "w": 7 * 86400, "mo": 30 * 86400, "y": 365 * 86400}


def channel_id(ch):
    if ch.get("id"):
        return ch["id"]
    cache = read_json(STATE / "channels.json", {})
    if ch["url"] in cache:
        return cache[ch["url"]]
    try:
        html = requests.get(ch["url"], timeout=30, headers=_HEAD, cookies=_COOKIES).text
        m = (re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', html)
             or re.search(r"channel_id=(UC[\w-]{22})", html))
        if m:
            cache[ch["url"]] = m.group(1)
            write_json(STATE / "channels.json", cache)
            return m.group(1)
    except Exception as e:
        log(f"  {ch['name']}: id canale non trovato ({str(e)[:80]})")
    return None


def _unescape(s):
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s


def _seconds(clock):
    out = 0
    for p in clock.split(":"):
        out = out * 60 + int(p)
    return out


def parse_tab(html):
    """Videos listed in a channel tab, in page order (newest first)."""
    out = []
    for block in html.split('"lockupViewModel":{')[1:]:
        m = re.search(r'"contentId":"([\w-]{11})"', block) or re.search(r'"videoId":"([\w-]{11})"', block)
        if not m:
            continue
        block = block[:20000]
        t = re.search(r'"lockupMetadataViewModel":\{"title":\{"content":"((?:[^"\\]|\\.)*)"', block)
        d = re.search(r'"text":"(\d{1,2}(?::\d{2}){1,2})"', block)
        a = re.search(r'"content":"(?:[A-Za-z]+ )?(\d+)\s?(mo|min|m|h|d|w|y|s)[a-z]* ago"', block)
        live = "no"
        if re.search(r'"(?:text|content)":"(?:LIVE|Live)"', block) or re.search(r'\d watching"', block):
            live = "live"
        elif re.search(r'"content":"(?:Scheduled|Premieres|Waiting)', block) or "UPCOMING" in block:
            live = "upcoming"
        age = int(a.group(1)) * _UNIT[a.group(2)] if a else None
        out.append({"id": m.group(1), "title": clean(_unescape(t.group(1))) if t else "",
                    "duration": _seconds(d.group(1)) if d else None,
                    "age": age, "live": live})
    return out


def _pages(cid):
    vids, seen = [], set()
    for tab in ("videos", "streams"):
        try:
            r = requests.get(f"https://www.youtube.com/channel/{cid}/{tab}", timeout=40,
                             headers=_HEAD, cookies=_COOKIES)
            if r.status_code != 200:
                continue
            for v in parse_tab(r.text)[:12]:
                if v["id"] not in seen:
                    seen.add(v["id"])
                    v["stream"] = tab == "streams"
                    vids.append(v)
        except Exception as e:
            log(f"    pagina /{tab} non letta ({str(e)[:70]})")
    return vids


def _rss(cid):
    for url in (f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
                f"https://www.youtube.com/feeds/videos.xml?playlist_id=UU{cid[2:]}"):
        try:
            r = requests.get(url, timeout=20, headers=_HEAD)
            if r.status_code != 200:
                continue
            out = {}
            for e in feedparser.parse(r.content).entries:
                vid = e.get("yt_videoid") or e.get("id", "").split(":")[-1]
                ts = e.get("published_parsed")
                if vid:
                    out[vid] = {"title": clean(e.get("title", "")),
                                "published": datetime.fromtimestamp(calendar.timegm(ts), UTC) if ts else None}
            if out:
                return out
        except Exception:
            pass
    return {}


def feed(ch):
    """Recent uploads, newest first: [{id,title,url,published,exact,duration,live}].

    `published` comes from RSS when available (exact=True); otherwise it is estimated from
    the "2h ago" label on the channel page (exact=False). It is None only if both are missing.
    """
    cid = channel_id(ch)
    if not cid:
        log(f"  {ch['name']}: controlla l'URL in config.yaml")
        return [], "id canale mancante"
    pages, rss = _pages(cid), _rss(cid)
    out = []
    if pages:
        for v in pages:
            exact = rss.get(v["id"], {}).get("published")
            est = now() - timedelta(seconds=v["age"]) if v["age"] is not None else None
            out.append({"id": v["id"], "title": v["title"] or rss.get(v["id"], {}).get("title", ""),
                        "url": f"https://www.youtube.com/watch?v={v['id']}",
                        "published": exact or est, "exact": bool(exact),
                        "duration": v["duration"], "live": v["live"]})
    else:
        for vid, e in rss.items():
            out.append({"id": vid, "title": e["title"], "url": f"https://www.youtube.com/watch?v={vid}",
                        "published": e["published"], "exact": True, "duration": None, "live": "unknown"})
    src = "+".join(x for x, ok in (("pagine", pages), ("rss", rss)) if ok) or "nessuna fonte"
    return out, src
