"""X (Twitter) posts: fetch recent posts, keep only the genuinely useful parts.

Provider: twitterapi.io (needs secret TWITTERAPI_KEY). If the key is missing, this step is skipped.
Every post goes through a Gemini filter that discards clickbait, promotions, giveaways,
course/affiliate pitches and vague hype, and keeps only concrete information.
"""
import json
import os
from datetime import datetime, timezone

import requests

from common import CFG, DATA, ask_json, now, read_json, write_json

XDIR = DATA / "x"
SEEN = DATA / "x_seen.json"

FILTER = """You are a strict financial news editor. Below are recent X posts from accounts
that often use clickbait, hype and self-promotion.

For EACH post decide if it contains genuinely useful market information:
concrete data, price levels, macro data, earnings, filings, news facts, specific
trade theses with reasoning, upcoming catalysts with dates.

DISCARD (useful=false): promotions, links to courses/newsletters/Discord/Patreon, affiliate
or exchange referral links, giveaways, "link in bio", engagement bait ("like if..."),
vague hype without data ("this stock will 10x!!"), memes, personal life, pure replies.

For useful posts, extract ONLY the useful part, paraphrased in neutral English
(strip emojis, hype words and the promo part). Flag unverified claims as rumor.

Return JSON: {{"items": [
  {{"id": "...", "useful": true/false, "score": 0-10,
    "extract": "neutral paraphrase of the useful part only, or empty",
    "tickers": ["..."], "category": "macro|stock|crypto|earnings|rumor|other",
    "is_rumor": true/false, "discard_reason": "short reason if useful=false"}}
]}}

POSTS:
{posts}"""


def fetch(handle, key):
    r = requests.get("https://api.twitterapi.io/twitter/user/last_tweets",
                     params={"userName": handle, "includeReplies": "false"},
                     headers={"X-API-Key": key}, timeout=60)
    r.raise_for_status()
    j = r.json()
    tweets = j.get("tweets") or (j.get("data") or {}).get("tweets") or []
    return tweets


def parse_time(s):
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            d = datetime.strptime(s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def run():
    key = os.environ.get("TWITTERAPI_KEY")
    accounts = CFG.get("x_accounts") or []
    if not key or not accounts:
        print("X: saltato (manca TWITTERAPI_KEY o lista account)")
        return
    seen = set(read_json(SEEN, []))
    cutoff = now().timestamp() - CFG.get("x_max_age_hours", 30) * 3600
    batch = []
    for h in accounts:
        h = h.lstrip("@")
        try:
            tweets = fetch(h, key)
        except Exception as e:
            print(f"X @{h}: errore {e}")
            continue
        n = 0
        for t in tweets:
            tid = str(t.get("id"))
            if tid in seen:
                continue
            seen.add(tid)
            ts = parse_time(t.get("createdAt", ""))
            if ts and ts.timestamp() < cutoff:
                continue
            text = t.get("text", "")
            if t.get("isReply") or text.startswith("RT @"):
                continue
            q = t.get("quoted_tweet") or {}
            if q.get("text"):
                text += f"\n[quoting: {q['text'][:500]}]"
            batch.append({"id": tid, "author": "@" + h, "text": text[:2000],
                          "url": t.get("url", f"https://x.com/{h}/status/{tid}"),
                          "created": t.get("createdAt", "")})
            n += 1
        print(f"X @{h}: {n} post nuovi")
    write_json(SEEN, sorted(seen)[-5000:])
    if not batch:
        return
    kept = []
    for i in range(0, len(batch), 40):  # filter in chunks
        chunk = batch[i:i + 40]
        res = ask_json(FILTER.format(posts=json.dumps(
            [{"id": p["id"], "author": p["author"], "text": p["text"]} for p in chunk], ensure_ascii=False)))
        by_id = {p["id"]: p for p in chunk}
        for it in res.get("items", []):
            p = by_id.get(str(it.get("id")))
            if not p:
                continue
            if it.get("useful") and it.get("score", 0) >= CFG.get("x_min_score", 6) and it.get("extract"):
                kept.append({**p, **{k: it.get(k) for k in ("extract", "tickers", "category", "is_rumor", "score")},
                             "analysed_at": now().isoformat()})
            else:
                print(f"  scartato {p['author']}: {it.get('discard_reason', '')}")
    print(f"X: tenuti {len(kept)} su {len(batch)} post")
    if kept:
        write_json(XDIR / f"{now().strftime('%Y-%m-%d_%H%M')}.json", kept)


def recent(hours):
    """Kept X items from the last N hours."""
    if not XDIR.exists():
        return []
    start = (now().timestamp() - hours * 3600)
    out = []
    for f in sorted(XDIR.glob("*.json")):
        for it in read_json(f, []):
            try:
                if datetime.fromisoformat(it["analysed_at"]).timestamp() >= start:
                    out.append(it)
            except Exception:
                pass
    return out
