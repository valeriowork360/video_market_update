"""Runs every 4 hours: find new videos, analyse them, grab market headlines.

Order of attempts per video:
  1. free transcript (youtube-transcript-api) -> Gemini analyses the text
  2. if YouTube blocks the cloud server: Gemini watches the video from its URL
"""
import feedparser
import yt_dlp

from common import CFG, NEWS, NOTES, STATE, ask_json, now, read_json, today_str, write_json

ANALYSE = """You are a financial research assistant. Analyse this video by "{author}"
titled "{title}" ({url}).

Return JSON with exactly these keys:
{{
  "summary": "3-5 sentences, in English, neutral",
  "author_tone": "one of: very bearish, bearish, cautious, neutral, optimistic, bullish, euphoric",
  "tone_evidence": "1 sentence: what in the delivery/words shows the tone",
  "key_points": [{{"point": "...", "timestamp": "mm:ss or null"}}],
  "tickers": ["NVDA", "..."],          // only tickers explicitly discussed
  "predictions": ["concrete calls the author makes, with levels/dates if any"],
  "catalysts": ["upcoming events mentioned: earnings, Fed, CPI..."],
  "rumors": ["unverified claims, clearly labelled as such"],
  "is_sponsored_or_promo": true/false
}}
Paraphrase; never copy more than 10 consecutive words from the speaker.
{extra}"""


def channel_id(channel):
    """Resolve @handle -> UC... id (cached in data/channel_ids.json)."""
    import re
    import requests
    from common import DATA
    cache = read_json(DATA / "channel_ids.json", {})
    if channel.get("channel_id"):
        return channel["channel_id"]
    if channel["url"] in cache:
        return cache[channel["url"]]
    try:
        html = requests.get(channel["url"], timeout=30, headers={"User-Agent": "Mozilla/5.0",
                            "Accept-Language": "en"}, cookies={"CONSENT": "YES+1"}).text
        m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', html) or \
            re.search(r'channel_id=(UC[\w-]{22})', html)
        if m:
            cache[channel["url"]] = m.group(1)
            write_json(DATA / "channel_ids.json", cache)
            return m.group(1)
    except Exception as e:
        print(f"  id canale non risolto: {e}")
    return None


def list_recent_videos(channel):
    """Primary: public RSS feed (reliable from cloud). Fallback: yt-dlp."""
    cid = channel_id(channel)
    if cid:
        d = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}")
        print(f"  RSS: {len(d.entries)} video (id {cid})")
        if d.entries:
            out = []
            for e in d.entries[:CFG["videos_per_channel"] * 2]:
                vid = e.get("yt_videoid") or e.get("id", "").split(":")[-1]
                ts = None
                if e.get("published_parsed"):
                    import calendar
                    ts = calendar.timegm(e.published_parsed)
                out.append({"id": vid, "title": e.get("title", ""), "duration": 0, "ts": ts})
            return out
    else:
        print("  id canale NON trovato: controlla l'URL in config.yaml")
    vids = list_recent_videos_ytdlp(channel)
    print(f"  yt-dlp: {len(vids)} video")
    return vids


def list_recent_videos_ytdlp(channel):
    opts = {"quiet": True, "extract_flat": True, "playlistend": CFG["videos_per_channel"],
            "skip_download": True}
    vids = []
    for tab in ("/videos", "/streams"):
        try:
            with yt_dlp.YoutubeDL(opts) as y:
                info = y.extract_info(channel["url"].rstrip("/") + tab, download=False)
            for e in info.get("entries") or []:
                vids.append({"id": e["id"], "title": e.get("title", ""),
                             "duration": e.get("duration") or 0})
        except Exception as ex:
            print(f"  [{channel['name']}{tab}] non leggibile: {ex}")
    return vids


def video_upload_time(vid):
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as y:
            info = y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
        return info.get("timestamp"), info.get("duration") or 0, info.get("live_status")
    except Exception:
        return None, 0, None


def get_transcript(vid):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        t = YouTubeTranscriptApi().fetch(vid, languages=["en", "it", "en-US"])
        lines = []
        for s in t:
            m, sec = divmod(int(s.start), 60)
            lines.append(f"[{m:02d}:{sec:02d}] {s.text}")
        return "\n".join(lines)
    except Exception as e:
        print(f"    trascrizione non disponibile ({type(e).__name__}) -> uso Gemini sul video")
        return None


def analyse(channel, v):
    url = f"https://www.youtube.com/watch?v={v['id']}"
    tr = get_transcript(v["id"])
    if tr:
        extra = ("Infer tone from wording only (no audio available).\nTRANSCRIPT:\n" + tr[:180000])
        data = ask_json(ANALYSE.format(author=channel["name"], title=v["title"], url=url, extra=extra))
    else:
        data = ask_json(ANALYSE.format(author=channel["name"], title=v["title"], url=url,
                                       extra="Listen to the voice for the tone."), video_url=url)
    data.update({"video_id": v["id"], "title": v["title"], "author": channel["name"], "url": url,
                 "analysed_at": now().isoformat()})
    return data


def collect_news():
    items = []
    for f in CFG["news_feeds"]:
        try:
            d = feedparser.parse(f)
            for e in d.entries[:15]:
                items.append({"title": e.get("title", ""), "link": e.get("link", ""),
                              "source": d.feed.get("title", f), "published": e.get("published", "")})
        except Exception as ex:
            print(f"  feed {f}: {ex}")
    stamp = now().strftime("%Y-%m-%d_%H%M")
    write_json(NEWS / f"{stamp}.json", items)
    print(f"Notizie salvate: {len(items)}")


def main():
    seen = set(read_json(STATE, []))
    cutoff = now().timestamp() - CFG["max_age_hours"] * 3600
    new = 0
    for ch in CFG["channels"]:
        print(f"Canale: {ch['name']}")
        for v in list_recent_videos(ch):
            if v["id"] in seen:
                continue
            if v.get("ts") and v["ts"] < cutoff:
                print(f"  vecchio, salto: {v['title'][:60]}")
                seen.add(v["id"])
                continue
            ts, dur, live = video_upload_time(v["id"])
            ts = ts or v.get("ts")
            if live in ("is_live", "is_upcoming"):
                continue  # wait until the live ends
            seen.add(v["id"])
            if ts and ts < cutoff:
                print(f"  vecchio, salto: {v['title'][:60]}")
                continue
            if dur and dur > CFG["max_duration_min"] * 60:
                print(f"  salto (troppo lungo): {v['title']}")
                continue
            print(f"  analizzo: {v['title']}")
            try:
                note = analyse(ch, v)
                write_json(NOTES / today_str() / f"{v['id']}.json", note)
                new += 1
            except Exception as e:
                print(f"  ERRORE analisi: {e}")
                seen.discard(v["id"])  # retry next run
    write_json(STATE, sorted(seen))
    collect_news()
    print(f"Video nuovi analizzati: {new}")


class Tee:
    """Mirror console output into data/logs so it can be read from the repo."""
    def __init__(self, path, stream):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f, self.s = open(path, "w", encoding="utf-8"), stream

    def write(self, x):
        self.s.write(x)
        self.f.write(x)
        self.f.flush()

    def flush(self):
        self.s.flush()


if __name__ == "__main__":
    import sys
    import traceback
    from common import DATA
    sys.stdout = Tee(DATA / "logs" / "collect_last.log", sys.stdout)
    try:
        main()
    except Exception:
        traceback.print_exc(file=sys.stdout)
        raise
