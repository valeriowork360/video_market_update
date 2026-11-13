"""Turn one YouTube video into a structured note: what the author says and with which tone.

Gemini watches the video straight from its URL (YouTube blocks transcript downloads from
cloud servers). To stay inside the free quota we read few frames (the audio is what
matters) and split long videos into chunks.
"""
import json

from . import llm, quota
from .core import CFG, clean, log, now

V = CFG["video"]
TONES = ["very bearish", "bearish", "cautious", "neutral", "optimistic", "bullish", "euphoric"]

PROMPT = """You are a sceptical financial research assistant. Watch this video by "{author}".
Published title (may be clickbait - judge the content, not the title): "{title}".
{hint}{part}
Report what the author ACTUALLY says. Strip hype, self-promotion, sponsors, course/Discord/
newsletter pitches and referral links: none of that belongs in the notes.

Return ONE JSON object with exactly these keys:
{{
 "empty": false,                      // true only if this portion has no content at all
 "market_relevance": 0-10,            // 0 = not about markets/economy/investing at all
 "scope": "global" | "italy",         // "italy" = matters only to people living in Italy
                                      // (Italian taxes, pensions, Italian politics/banks)
 "kind": "market update|stock pick|macro|crypto|personal finance|interview|other",
 "summary": "4-6 neutral sentences in English",
 "digest_it": "2-3 frasi in italiano semplice: cosa dice l'autore e cosa si aspetta",
 "author_tone": one of {tones},
 "tone_evidence": "one sentence: what in voice and wording shows that tone",
 "key_points": [{{"point": "concrete claim, with numbers/levels if given", "timestamp": "mm:ss"}}],  // max 8
 "tickers": ["NVDA", "BTC"],          // only assets actually discussed
 "predictions": ["explicit calls: direction, price levels, dates"],
 "catalysts": ["upcoming events the author flags, with date if said"],
 "rumors": ["unverified claims, worded as such"],
 "curiosities": ["odd or surprising facts mentioned, if any"],
 "promo": true/false,                 // contains sponsorship or self-promotion
 "language": "it" | "en"
}}
Paraphrase everything: never copy more than 8 consecutive words from the speaker.
Use only what is said or shown in the video. If a number is unclear, leave it out."""

MERGE = """These are notes on consecutive parts of ONE video by "{author}" titled "{title}".
Merge them into a single JSON object with exactly the same keys as each part
(summary 4-6 sentences for the whole video, max 8 key_points keeping timestamps, one
overall author_tone from {tones}, digest_it in Italian, union of the lists without duplicates,
"empty": false). Do not add anything that is not in the parts.

PARTS:
{parts}"""


def _tokens_per_second(fps):
    return 66 * (fps or 1.0) + 34


def _one(v, ch, start, end, fps, part_txt):
    hint = f'Channel note: {ch["hint"]}\n' if ch.get("hint") else ""
    prompt = PROMPT.format(author=ch["name"], title=v["title"], hint=hint, part=part_txt,
                           tones=json.dumps(TONES))
    span = (end - start) if end is not None else (v.get("duration") or 20 * 60)
    video = {"url": v["url"], "fps": fps, "start": start if start else None, "end": end,
             "est_tokens": int(span * _tokens_per_second(fps))}
    return llm.ask("watch", lambda _n: prompt, video=video, temperature=0.3, patience=0)


def _call(v, ch, start, end, part_txt):
    """Try with low frame rate; if Gemini rejects the parameters, fall back step by step."""
    try:
        return _one(v, ch, start, end, V.get("fps") or None, part_txt), True
    except llm.BadVideoRequest as e:
        log(f"    parametri video rifiutati ({str(e)[:90]}): riprovo senza fps")
    try:
        return _one(v, ch, start, end, None, part_txt), False
    except llm.BadVideoRequest as e:
        if start:
            raise
        log(f"    ancora rifiutato ({str(e)[:90]}): riprovo sul video intero")
    return _one(v, ch, None, None, None, ""), False


def _norm(n):
    n = dict(n or {})
    tone = str(n.get("author_tone", "neutral")).lower().strip()
    n["author_tone"] = tone if tone in TONES else "neutral"
    try:
        n["market_relevance"] = max(0, min(10, int(float(n.get("market_relevance", 5)))))
    except Exception:
        n["market_relevance"] = 5
    n["scope"] = "italy" if str(n.get("scope", "")).lower().startswith("ital") else "global"
    for k in ("summary", "digest_it", "tone_evidence", "kind"):
        n[k] = clean(n.get(k, ""))
    for k in ("tickers", "predictions", "catalysts", "rumors", "curiosities"):
        n[k] = [clean(x) for x in (n.get(k) or []) if clean(x)][:10]
    kp = []
    for p in (n.get("key_points") or [])[:8]:
        if isinstance(p, dict) and clean(p.get("point")):
            kp.append({"point": clean(p["point"]), "timestamp": clean(p.get("timestamp") or "")})
        elif isinstance(p, str) and clean(p):
            kp.append({"point": clean(p), "timestamp": ""})
    n["key_points"] = kp
    n["promo"] = bool(n.get("promo"))
    return n


def _merge_local(parts):
    base = dict(parts[0])
    base["summary"] = " ".join(p["summary"] for p in parts)
    base["digest_it"] = " ".join(p["digest_it"] for p in parts)[:600]
    for k in ("tickers", "predictions", "catalysts", "rumors", "curiosities"):
        seen = []
        for p in parts:
            for x in p[k]:
                if x not in seen:
                    seen.append(x)
        base[k] = seen[:10]
    kps = [k for p in parts for k in p["key_points"][:4]]
    base["key_points"] = kps[:8]
    base["market_relevance"] = max(p["market_relevance"] for p in parts)
    base["promo"] = any(p["promo"] for p in parts)
    return base


def analyse(v, ch):
    """v: {id,title,url,duration?}. Returns the note dict. Raises llm.LLMError to retry later."""
    dur = v.get("duration")
    limit = V["max_minutes"] * 60
    chunk = V["chunk_minutes"] * 60
    parts, start, partial, model = [], 0, False, ""
    while True:
        end = start + chunk
        if dur:
            end = min(end, dur, limit)
            whole = start == 0 and end >= dur
        else:
            whole = False
        part_txt = "" if whole else (
            f"\nYou are given only the part from {start // 60} to {end // 60} minutes of a longer "
            f"video: describe this part only.\n")
        try:
            (data, meta), fps_ok = _call(v, ch, start, None if whole else end, part_txt)
        except llm.BadVideoRequest:
            if parts:           # we asked past the end of the video
                break
            raise llm.LLMError("video non leggibile da Gemini (privato, live in corso o non pronto)")
        except llm.LLMError:
            if not parts:
                raise
            partial = True      # keep what we already understood instead of starting over
            break
        model = meta["model"]
        if meta.get("audio_tokens"):
            seen_sec = meta["audio_tokens"] / 32
        elif meta.get("prompt_tokens"):
            seen_sec = meta["prompt_tokens"] / _tokens_per_second(V.get("fps") if fps_ok else 1.0)
        else:
            seen_sec = (end - start)
        if dur:
            seen_sec = min(seen_sec, end - start) if seen_sec else end - start
        quota.add_video_seconds(seen_sec)
        if data.get("empty") and parts:
            break
        parts.append(_norm(data))
        if dur:
            if end >= min(dur, limit):
                partial = dur > limit
                break
        else:
            if seen_sec < (end - start) - 120:      # the video ended inside this chunk
                break
            if end >= limit:
                partial = True
                break
        start = end

    if len(parts) == 1:
        note = parts[0]
    else:
        try:
            body = MERGE.format(author=ch["name"], title=v["title"], tones=json.dumps(TONES),
                                parts=json.dumps(parts, ensure_ascii=False))
            merged, _ = llm.ask("light", lambda n: body[:n], temperature=0.2, patience=0)
            note = _norm(merged)
        except Exception as e:
            log(f"    unione note fatta in locale ({str(e)[:80]})")
            note = _merge_local(parts)
    note.pop("empty", None)
    note.update({"video_id": v["id"], "title": v["title"], "author": ch["name"], "url": v["url"],
                 "published": v["published"].isoformat() if v.get("published") else None,
                 "duration_min": round(dur / 60) if dur else None, "partial": partial,
                 "analysed_at": now().isoformat(), "model": model})
    return note
