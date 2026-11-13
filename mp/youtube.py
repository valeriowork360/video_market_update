"""YouTube without API keys: public RSS feeds for new videos, the watch page for length/live status."""
import calendar
import re
from datetime import datetime

import feedparser
import requests

from .core import STATE, UTC, clean, log, read_json, write_json

_HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
         "Accept-Language": "en-US,en;q=0.8"}
_COOKIES = {"CONSENT": "YES+1", "SOCS": "CAI"}


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


def feed(ch):
    """Latest ~15 uploads of a channel, newest first."""
    cid = channel_id(ch)
    if not cid:
        log(f"  {ch['name']}: controlla l'URL in config.yaml")
        return []
    try:
        r = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
                         timeout=30, headers=_HEAD)
        r.raise_for_status()
        d = feedparser.parse(r.content)
    except Exception as e:
        log(f"  {ch['name']}: feed non letto ({str(e)[:80]})")
        return []
    out = []
    for e in d.entries:
        vid = e.get("yt_videoid") or e.get("id", "").split(":")[-1]
        if not vid:
            continue
        ts = e.get("published_parsed")
        pub = datetime.fromtimestamp(calendar.timegm(ts), UTC) if ts else None
        link = e.get("link", "")
        out.append({"id": vid, "title": clean(e.get("title", "")), "published": pub,
                    "description": clean(e.get("summary", ""))[:1500],
                    "is_short": "/shorts/" in link,
                    "url": f"https://www.youtube.com/watch?v={vid}"})
    return out


def meta(video_id):
    """Best effort: {'duration': seconds|None, 'live': 'live'|'upcoming'|'no'|'unknown'}."""
    out = {"duration": None, "live": "unknown"}
    try:
        html = requests.get(f"https://www.youtube.com/watch?v={video_id}", timeout=30,
                            headers=_HEAD, cookies=_COOKIES).text
    except Exception:
        return out
    m = re.search(r'"lengthSeconds":"(\d+)"', html)
    if m:
        out["duration"] = int(m.group(1)) or None
        out["live"] = "no"
    if re.search(r'"isUpcoming":true', html):
        out["live"] = "upcoming"
    elif re.search(r'"isLiveNow":true', html) or re.search(r'"isLive":true', html):
        out["live"] = "live"
    return out
