"""Temporary network probe (run on GitHub to see what YouTube answers from there)."""
import re
import time

import feedparser
import requests

CID = "UCIb34uXDsfTq4PJKW0eztkA"
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
URLS = {"channel": f"https://www.youtube.com/feeds/videos.xml?channel_id={CID}",
        "playlist": f"https://www.youtube.com/feeds/videos.xml?playlist_id=UU{CID[2:]}",
        "playlistUULF": f"https://www.youtube.com/feeds/videos.xml?playlist_id=UULF{CID[2:]}"}
for rnd in range(3):
    for name, url in URLS.items():
        for label, h in (("plain", {}), ("browser", BROWSER), ("browser+lang", {**BROWSER, "Accept-Language": "en-US,en;q=0.8"}),
                         ("feedparserUA", {"User-Agent": feedparser.USER_AGENT})):
            try:
                r = requests.get(url, headers=h, timeout=30)
                n = len(feedparser.parse(r.content).entries) if r.ok else 0
                print(f"round{rnd} {name:13s} {label:13s} -> {r.status_code} entries={n}", flush=True)
            except Exception as e:
                print(f"round{rnd} {name} {label} EXC {str(e)[:80]}", flush=True)
        d = feedparser.parse(url)
        print(f"round{rnd} {name:13s} feedparser.parse -> status={d.get('status')} entries={len(d.entries)}", flush=True)
    time.sleep(4)
for path in ("videos", "streams", "shorts"):
    r = requests.get(f"https://www.youtube.com/channel/{CID}/{path}", headers={**BROWSER, "Accept-Language": "en-US"}, cookies={"CONSENT": "YES+1", "SOCS": "CAI"}, timeout=30)
    ids = list(dict.fromkeys(re.findall(r'"videoId":"([\w-]{11})"', r.text)))
    print(f"page /{path} -> {r.status_code} len={len(r.text)} ids={len(ids)} first={ids[:4]} publishedTimeText={len(re.findall('publishedTimeText', r.text))} url={r.url[:80]}", flush=True)
    m = re.search(r'"publishedTimeText":\{"simpleText":"([^"]+)"', r.text)
    print("   sample time text:", m.group(1) if m else None)
vid = ids[0] if ids else "cn_xARVOK6E"
for v in ("cn_xARVOK6E", vid):
    r = requests.get(f"https://www.youtube.com/watch?v={v}", headers={**BROWSER, "Accept-Language": "en-US"}, cookies={"CONSENT": "YES+1", "SOCS": "CAI"}, timeout=30)
    t = r.text
    print(f"watch {v} -> {r.status_code} len={len(t)} length={re.findall(r'\"lengthSeconds\":\"(\\d+)\"', t)[:1]} "
          f"publish={re.findall(r'\"(?:publishDate|uploadDate)\":\"([^\"]+)\"', t)[:2]} liveNow={re.findall(r'\"isLiveNow\":(\\w+)', t)[:1]} "
          f"upcoming={'isUpcoming\":true' in t} playability={re.findall(r'\"playabilityStatus\":\\{\"status\":\"(\\w+)\"', t)[:1]}", flush=True)
    r = requests.get("https://www.youtube.com/oembed", params={"url": f"https://www.youtube.com/watch?v={v}", "format": "json"}, timeout=30)
    print(f"oembed {v} -> {r.status_code} {r.text[:120]}", flush=True)
for u in ("https://finance.yahoo.com/news/rssindex", "https://finance.yahoo.com/rss/topstories", "https://finance.yahoo.com/rss/",
          "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US",
          "https://www.cnbc.com/id/15839069/device/rss/rss.html", "https://www.cnbc.com/id/20910258/device/rss/rss.html",
          "https://www.cnbc.com/id/10000664/device/rss/rss.html"):
    for label, h in (("bot", {"User-Agent": "Mozilla/5.0 (compatible; MarketPulseBot/1.0)"}), ("browser", BROWSER)):
        try:
            r = requests.get(u, headers=h, timeout=30)
            d = feedparser.parse(r.content)
            print(f"news {label:8s} {r.status_code} entries={len(d.entries)} first={d.entries[0].get('published', '')[:25] if d.entries else ''} {u[:70]}", flush=True)
        except Exception as e:
            print(f"news {label} EXC {str(e)[:60]} {u[:60]}", flush=True)
