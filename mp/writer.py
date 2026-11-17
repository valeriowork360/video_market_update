"""Scripts. Two small jobs instead of one huge one, so a failure never costs the whole day:

  A) long_script  : notes + news + verified prices  ->  the long video
  B) derivatives  : the long video script           ->  shorts and Instagram carousels
"""
import json
import re

from . import llm
from .core import CFG, clean, log
from .speech import tidy

LANG = {"it": "Italian", "en": "English"}
MOODS = {
    "calm": "calm analyst: unhurried, reassuring, explanatory",
    "neutral": "news anchor: clear, measured, confident, short sentences",
    "urgent": "breaking-news anchor: tight, alert, serious, no drama words",
    "upbeat": "energetic finance host: lively and positive, never hype",
}

RULES = """HARD RULES
- Native, natural {lang}. Not a translation. Spoken style: short sentences, no lists read aloud.
- Spelling must be perfect, including every accent of the language (Italian: è, é, à, ò, ù, ì,
  "perché", "più", "città"). Never drop accents.
- WRITE EVERYTHING EXACTLY AS IT MUST APPEAR ON SCREEN. Our software converts the text for the
  voice, so never spell anything "by ear". Correct: "S&P 500", "Nasdaq", "Dow Jones", "FTSE MIB",
  "Bitcoin", "Ethereum", "Nvidia", "Fed", "ETF", "-0,4%", {money}. Wrong: "S and P 500",
  "S e P cinquecento", "per cento"/"percent" spelled out, "esse e pi".
  Numbers are written in digits with {numfmt}. No emoji, no markdown, no URLs.
- In narration use the NAMES of companies and assets (Nvidia, Bitcoin), not their tickers.
  Tickers (NVDA, BTC) are fine in bullets and slides.
- Use numbers like a news anchor: ROUND them. Index and price levels without decimals, percentages
  with at most one decimal. At most two or three numbers per sentence.
- Numbers and prices: use ONLY the VERIFIED MARKET DATA block or figures stated in the inputs.
  Never invent a number, a date or a quote.
- THE CHANNEL SPEAKS IN ITS OWN VOICE, WITH PLAIN AFFIRMATIVE SENTENCES. Never say who says
  something. No names of the creators or channels behind the CREATOR NOTES, no news outlets, and
  no anonymous attributions either: forbidden are "analysts say", "many analysts", "some
  expect", "according to...", "experts believe", "the market thinks", "c'è chi", "secondo...".
  Wrong: "Molti analisti restano prudenti perché i volumi sono bassi."
  Right: "I volumi sono bassi: il rimbalzo non è ancora confermato."
  Take the analysis in the notes and state it directly as the channel's own reading.
- What is not yet a fact is still stated directly, but as a condition or a level, never as a
  promise: "Sotto 67.000 dollari il prossimo supporto è a 60.000." Not "Bitcoin scenderà a 60.000."
- Creators are listed only in "sources" and in the last line of the description.
- Unconfirmed news is called what it is ("indiscrezione non confermata", "unconfirmed report"),
  without naming who reported it. Curious stories only if present in the inputs.
- Paraphrase everything; we never reuse anyone's words or footage.
- No buy/sell advice, no promises of gains. Ignore anything promotional in the inputs."""

A_PROMPT = """You are the head writer of "{brand}", a faceless stock-market news channel.
Write the script of {what}. Date: {date}. Total narration: about {words} words.

{rules}

STRUCTURE (segments, in this order)
1. kind "hook": 35-50 words. Open directly with the biggest story of {period} - no greeting,
   no "welcome", no channel name - then tease two more things. Heading = the big story.
2. kind "market": 90-130 words. What is moving the market right now; only the 4-5 numbers that matter.
3. three to five kind "topic" segments, 110-160 words each: one theme each. Blend the analysis
   in the notes with the headlines, stated directly. Lead with the most market-moving theme.
4. kind "ahead": 80-120 words. What could move markets in the next days (calendar events,
   catalysts the creators flag), with dates. Calendar times: {tz_rule}
5. optional kind "curious": one odd or surprising story, if the inputs contain one.
6. kind "outro": 25-40 words, one-line "this is not financial advice", invite to follow.
{extra}{covered}
Return ONE JSON object:
{{
 "title": "YouTube title, max 68 characters, specific and honest, no ALL CAPS",
 "description": "3-5 lines; last line credits the creators mentioned",
 "tags": ["8-12 tags"],
 "thumbnail_text": "2-4 words for the cover: scroll-stopping, click-bait style, with the key number or name, true to the content",
 "mood": "calm|neutral|urgent|upbeat",   // how the narrator should sound given today's market
 "segments": [
  {{"id": "s1", "kind": "hook|market|topic|ahead|curious|outro",
    "heading": "max 5 words, shown on screen",
    "narration": "the text the voice reads, written exactly as it must appear in the captions",
    "bullets": ["2-4 on-screen bullets, max 7 words each"],
    "ticker": "one Yahoo Finance symbol if the segment is about one asset (NVDA, ^GSPC, BTC-USD), else null",
    "sentiment": "bullish|bearish|neutral",
    "sources": ["creators and outlets used in this segment"]}}
 ]
}}

VERIFIED MARKET DATA (the only prices you may cite):
{market}

ECONOMIC CALENDAR (upcoming, UTC):
{calendar}

CREATOR NOTES (background analysis with each author's tone - use the ideas, never the names):
{notes}

HEADLINES (reliable outlets):
{news}
"""

SHORT_RULES = """HOW A SHORT IS BUILT - follow exactly:
- Exactly 5 beats, 55-80 words in total:
  1 HOOK     max 12 words. The most striking fact of this part as a punch, starting with the
             number or the name. No greeting, no "today we talk about", no yes/no question.
  2 CONTEXT  what is happening, one sentence.
  3 TWIST    what most people miss, or why it is not what it seems.
  4 STAKES   the level, the date or the number to watch now.
  5 PAYOFF   one line that closes the loop opened by the hook, then a 3-word follow invite.
- "show" = 2-4 words shown HUGE on screen. The first beat's "show" is the COVER of the short:
  a scroll-stopping, click-bait style line (bold, concrete, with the number or the name) that
  is still true to the content. It must make sense alone, with the sound off.
- "figure" = the one key number of the beat as written on screen ("-7%", "68.700 $") or "".
- Every sentence is short. One idea per beat. The viewer decides in the first 2 seconds."""

V_PROMPT = """You are the shorts editor of "{brand}". Below are private research notes on ONE video
by a creator we follow. Turn EVERY salient part of it into its own short: one short per part,
each about a different point, up to {n} shorts. Skip only parts with no real substance
(greetings, promotions, repetition). Order them from the strongest to the weakest.

Write each short in these languages: {langs}. Each version is written natively for that
language, not translated word by word.
For Italian use Italian number format ("7.590", "0,4%", "68.700 dollari").

{rules}

{short_rules}

Return ONE JSON object:
{{"shorts": [
  {{"ticker": "one Yahoo Finance symbol if this part is about one asset (NVDA, ^GSPC, BTC-USD), else null",
    "sentiment": "bullish|bearish|neutral",
    {lang_fields}
  }}
]}}
where every language block is:
  {{"title": "max 60 characters, curiosity without lying",
    "beats": [{{"say": "what the voice says", "show": "2-4 words", "figure": "key number or \"\""}}],
    "caption": "1-2 sentence post caption", "hashtags": ["#5-8"]}}

NOTES ON THE VIDEO:
{note}
"""

B_PROMPT = """You are the social editor of "{brand}". Below is the script of today's long video.
Derive social content FROM THIS SCRIPT ONLY: do not add facts, numbers or names that are not in it.

{rules}

Return ONE JSON object:
{{
 "carousels": [   // {carousel_rule}
  {{"segment_id": "...", "topic": "max 6 words",
    "caption": "Instagram caption, 2-3 sentences, ends with a question or a follow invite",
    "hashtags": ["#8-12"],
    "slides": [{{"title": "...", "body": "..."}}]
    // 5-7 slides.
    // Slide 1 is the COVER: title = a scroll-stopping hook of max 7 words that contains the key
    //   name or number of the story ("Bitcoin sotto 70.000: e adesso?"); body = one sentence that
    //   promises what the next slides reveal. No generic titles like "Market update".
    // Middle slides: title max 5 words, specific (they are previewed on the cover);
    //   body max 26 words, one idea, with the concrete number or fact.
    // Last slide: the takeaway in one sentence + invite to follow.
  }}
 ]
}}

SCRIPT:
{script}
"""


def _note_view(n, level):
    v = {"author": n["author"], "tone": n["author_tone"], "title": n["title"][:90],
         "summary": n["summary"] if level < 2 else n["summary"][:260]}
    if level == 0:
        v.update({"tone_evidence": n.get("tone_evidence"),
                  "key_points": [k["point"] for k in n["key_points"][:6]],
                  "predictions": n["predictions"][:5], "catalysts": n["catalysts"][:5],
                  "rumors": n["rumors"][:3], "curiosities": n["curiosities"][:3],
                  "tickers": n["tickers"][:8]})
    elif level == 1:
        v.update({"key_points": [k["point"] for k in n["key_points"][:3]],
                  "predictions": n["predictions"][:2], "rumors": n["rumors"][:1]})
    if n.get("scope") == "italy":
        v["scope"] = "Italy only"
    return v


def _fit(notes, news, budget):
    """Pick the richest view of notes and headlines that fits the character budget."""
    notes = sorted(notes, key=lambda n: (-n.get("market_relevance", 5), n.get("published") or ""))
    for level, n_news, with_sum in ((0, 60, True), (0, 40, False), (1, 30, False),
                                    (2, 20, False), (2, 10, False)):
        nv = json.dumps([_note_view(n, level) for n in notes], ensure_ascii=False)
        hv = json.dumps([{"t": h["title"], "src": h["source"],
                          **({"s": h["summary"][:160]} if with_sum and h.get("summary") else {})}
                         for h in news[:n_news]], ensure_ascii=False)
        if len(nv) + len(hv) <= budget:
            return nv, hv
    keep = max(3, len(notes) // 2)
    return (json.dumps([_note_view(n, 2) for n in notes[:keep]], ensure_ascii=False),
            json.dumps([{"t": h["title"]} for h in news[:8]], ensure_ascii=False))


def _rules(lang):
    if lang == "it":
        return RULES.format(lang=LANG[lang], money='"68.700 dollari", "5,6 miliardi di dollari"',
                            numfmt='Italian format ("7.590", "0,4")')
    return RULES.format(lang=LANG[lang], money='"$68,700", "$5.6 billion"', numfmt='English format ("7,590", "0.4")')


def long_script(notes, news, market, cal, lang, kind, date_label, week_scripts=None, covered=None):
    weekly = kind == "weekly"
    minutes = CFG["weekly" if weekly else "daily"]["minutes"]
    what = "the WEEKLY RECAP video (the past seven days)" if weekly else "today's DAILY BRIEFING video"
    extra = ""
    if weekly:
        extra = ("\nWEEKLY ANGLE: the biggest moves of the week, how the creators' views changed, "
                 "who turned out right, and what to watch next week.\n"
                 "THIS WEEK'S DAILY EPISODES (for continuity): "
                 + json.dumps(week_scripts or [], ensure_ascii=False)[:6000] + "\n")
    fixed = A_PROMPT.format(
        brand=CFG["brand"]["name"], what=what, date=date_label, words=minutes * 145,
        rules=_rules(lang), period="the week" if weekly else "today", extra=extra,
        covered=("" if weekly or not covered else
                 "\nALREADY TOLD IN PREVIOUS EPISODES: " + json.dumps(covered, ensure_ascii=False)[:3500] +
                 "\nRULE: do not retell these stories. One of them may return ONLY if today's inputs "
                 "contain a NEW fact about it: then say just the new fact in one or two sentences, with "
                 "no recap of what was already told. Prefer stories that are not in this list.\n"),
        tz_rule=('use "when_rome" and say "ora italiana".' if lang == "it"
                 else 'use "when_new_york" and say "Eastern Time".'),
        market=json.dumps(market, ensure_ascii=False) if market else "not available today: do not cite prices",
        calendar=json.dumps(cal, ensure_ascii=False) if cal else "not available",
        notes="@@NOTES@@", news="@@NEWS@@")

    target = minutes * 145
    state = {"feedback": ""}

    def make(budget):
        nv, hv = _fit(notes, news, max(2500, budget - len(fixed) - 300))
        return fixed.replace("@@NOTES@@", nv).replace("@@NEWS@@", hv) + state["feedback"]

    best, best_meta, problem = None, None, None
    for attempt in (1, 2):
        try:
            data, meta = llm.ask("write", make, temperature=0.6, patience=1)
            script = _check_long(data)
            spoken = " ".join(x["narration"] + " " + x["heading"] + " " + " ".join(x["bullets"])
                              for x in script["segments"])
            _language_check(spoken, lang)
            if attempt == 1:                # second draft: keep it even if something slipped through
                _names_check(spoken + " " + script["title"])
                _voice_check(spoken)
        except llm.LLMError as e:
            problem = e
            if best or attempt == 2:
                break
            state["feedback"] = f"\n\nIMPORTANT: your previous draft was rejected ({e}). Fix exactly that.\n"
            log(f"    copione scartato ({e}): lo faccio riscrivere")
            continue
        if not best or script["words"] > best["words"]:
            best, best_meta = script, meta
        if script["words"] >= 0.6 * target or attempt == 2:
            break
        state["feedback"] = (f"\n\nIMPORTANT: your previous draft had only {script['words']} words. "
                             f"Write about {target} words: develop every topic segment fully.\n")
        log(f"    copione corto ({script['words']} parole su {target}): chiedo una versione completa")
    if not best:
        raise problem or llm.LLMError("copione non riuscito")
    return best, best_meta


def derivatives(script, lang, kind):
    d = CFG["daily"]
    if kind == "weekly":
        shorts_rule = "return an empty list"
        carousel_rule = "exactly ONE carousel recapping the whole week (segment_id null)"
    else:
        shorts_rule = (f"{d['shorts_min']} to {d['shorts_max']} shorts, only from segments with a real hook, "
                       f"strongest first")
        carousel_rule = (f"one carousel for each 'topic' segment, plus 'ahead' if strong "
                         f"(max {d['max_carousels']})")
    slim = {"title": script["title"],
            "segments": [{k: s.get(k) for k in ("id", "kind", "heading", "narration", "ticker",
                                                 "sentiment", "sources")}
                         for s in script["segments"]]}
    body = B_PROMPT.format(brand=CFG["brand"]["name"], rules=_rules(lang), shorts_rule=shorts_rule,
                           carousel_rule=carousel_rule, script=json.dumps(slim, ensure_ascii=False),
                           creators=json.dumps([c["name"] for c in CFG["channels"]]))
    feedback, last = "", None
    for attempt in (1, 2):
        data, meta = llm.ask("write", lambda n: body[:max(n, 9000)] + feedback, temperature=0.7, patience=1)
        out = _check_deriv(data, script, kind)
        try:
            blob = " ".join([x["narration"] + " " + x["caption"] + " " + " ".join(b["show"] for b in x["beats"])
                             for x in out["shorts"]]
                            + [sl["title"] + " " + sl["body"] for c in out["carousels"] for sl in c["slides"]]
                            + [c["caption"] for c in out["carousels"]])
            _language_check(blob, lang)
            _names_check(blob)
            _voice_check(blob)
            if not out["carousels"]:
                raise llm.LLMError("no usable carousels")
            out["model"] = meta["model"]
            return out, meta
        except llm.LLMError as e:
            last = e
            usable = out["carousels"] and (out["shorts"] or kind != "daily")
            if attempt == 2 and usable:
                # a spelling blemish must never cost the delivery: send what we have
                log(f"    avviso non bloccante: {e}")
                out["model"] = meta["model"]
                return out, meta
            feedback = f"\n\nIMPORTANT: your previous answer was rejected ({e}). Fix exactly that.\n"
            log(f"    short e caroselli scartati ({e}): li faccio riscrivere")
    raise last


# ---------------------------------------------------------------- validation
_SRC = {"verified market data": "Yahoo Finance", "market data": "Yahoo Finance",
        "economic calendar": "Forex Factory", "calendar": "Forex Factory", "headlines": ""}


def _sources(xs):
    out = []
    for x in xs or []:
        x = clean(x)[:40]
        x = _SRC.get(x.lower(), x)
        if x and x not in out:
            out.append(x)
    return out[:5]


_NO_ACCENT = re.compile(r"\b(perche|poiche|piu|cosi|gia|giu|puo|cioe|verra|potra|dovra|citta|"
                        r"societa|attivita|liquidita|volatilita|novita|possibilita|stabilita)\b", re.I)


def _names_check(text):
    """The voice never names the creators we follow (the user's rule)."""
    found = sorted({n for n in CFG.get("credits", {}).get("never_say", [])
                    if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text, re.I)})
    if found:
        raise llm.LLMError("creators are named in the text (" + ", ".join(found) + "): rewrite those "
                           "passages as the view of unnamed analysts, with no names at all")


_HEDGE = re.compile(
    r"\b(?:(?:molti|diversi|alcuni|vari|numerosi|gli|tra gli|degli) (?:analisti|esperti|osservatori|operatori)"
    r"|secondo (?:gli|i|le|molti|diversi|alcuni|quanto|fonti|indiscrezioni di)\b"
    r"|c'è chi|a detta d|gli (?:ottimisti|scettici|analisti)\b"
    r"|(?:many|some|several|most) (?:analysts|experts|observers|traders|strategists)"
    r"|analysts (?:say|said|remain|argue|expect|warn|believe|see|note)|experts (?:say|believe|warn)"
    r"|according to|some (?:expect|see|argue|believe)|the (?:bullish|bearish|optimistic|cautious) camp)", re.I)


def _voice_check(text):
    """The channel states things itself: no 'analysts say', no 'according to'."""
    found = sorted({m.group(0).lower() for m in _HEDGE.finditer(text)})
    if found:
        raise llm.LLMError("attributions found (" + ", ".join(found[:6]) + "): rewrite those sentences as "
                           "direct affirmative statements in the channel's own voice, without saying who says it")


def _t(x, n=None):
    """Clean on-screen text: no emoji/markdown, correct spelling of market terms."""
    x = tidy(clean(x))
    return x[:n] if n else x


def _language_check(text, lang):
    """Some models drop Italian accents ("perche", "piu"): that reads badly and sounds wrong.

    Judged on the tell-tale words themselves, never on how many accents a short text has:
    a short, correct Italian text can easily contain none.
    """
    if lang != "it":
        return
    bad = sorted({m.lower() for m in _NO_ACCENT.findall(text)})
    if len(bad) >= 2 or (len(text) > 2500 and not re.search("[àèéìòù]", text)):
        raise llm.LLMError("Italian accents are missing (" + ", ".join(bad[:5]) + "): write every accent")


def _sent(x):
    x = str(x or "").lower()
    return x if x in ("bullish", "bearish", "neutral") else "neutral"


def _ticker(x):
    x = str(x or "").strip().upper()
    return x if x and x not in ("NULL", "NONE", "N/A") and len(x) <= 12 else None


def _check_long(d):
    segs = []
    for i, s in enumerate(d.get("segments") or [], 1):
        nar = _t(s.get("narration"))
        if len(nar) < 20:
            continue
        segs.append({"id": str(s.get("id") or f"s{i}"), "kind": str(s.get("kind") or "topic").lower(),
                     "heading": _t(s.get("heading"), 60) or "Market Pulse",
                     "narration": nar,
                     "bullets": [_t(b, 70) for b in (s.get("bullets") or []) if clean(b)][:4],
                     "ticker": _ticker(s.get("ticker")), "sentiment": _sent(s.get("sentiment")),
                     "sources": _sources(s.get("sources"))})
    words = sum(len(s["narration"].split()) for s in segs)
    if len(segs) < 3 or words < 250:
        raise llm.LLMError(f"copione troppo corto ({len(segs)} segmenti, {words} parole)")
    mood = str(d.get("mood") or "neutral").lower()
    return {"title": _t(d.get("title"), 95) or "Market Pulse",
            "description": tidy(str(d.get("description") or "").strip()),
            "tags": [clean(t).lstrip("#") for t in (d.get("tags") or []) if clean(t)][:15],
            "thumbnail_text": _t(d.get("thumbnail_text"), 40),
            "mood": mood if mood in MOODS else "neutral", "segments": segs, "words": words}


def _short_ok(sh, lang):
    blob = sh["narration"] + " " + sh["caption"] + " " + sh["title"] + " " + " ".join(b["show"] for b in sh["beats"])
    _language_check(blob, lang)
    _names_check(blob)
    _voice_check(blob)


def _one_short(raw, common, origin, source):
    beats = [{"say": _t(x.get("say")), "show": _t(x.get("show"), 44), "figure": _t(x.get("figure"), 14)}
             for x in (raw.get("beats") or []) if isinstance(x, dict) and clean(x.get("say"))][:6]
    if len(beats) < 3:
        return None
    for b in beats:
        b["show"] = b["show"] or " ".join(b["say"].split()[:3])
    nar = " ".join(b["say"] for b in beats)
    if len(nar.split()) < 30:
        return None
    return {"title": _t(raw.get("title"), 90), "hook": beats[0]["show"], "beats": beats, "origin": origin,
            "source_video": source, "narration": nar, "ticker": _ticker(common.get("ticker")),
            "sentiment": _sent(common.get("sentiment")), "sources": [], "caption": _t(raw.get("caption")),
            "hashtags": [h if h.startswith("#") else "#" + h
                         for h in (clean(x).replace(" ", "") for x in (raw.get("hashtags") or [])) if h][:10]}


def video_shorts(note, langs):
    """Several shorts from ONE creator video: one per salient part. Returns {lang: [short, ...]}."""
    n = CFG["daily"].get("shorts_per_video", 5)
    ch = next((c for c in CFG["channels"] if c["name"] == note["author"]), {})
    origin = ch.get("group") or note["author"]
    view = {"title": note["title"][:120], "tone": note.get("author_tone"), "summary": note.get("summary"),
            "parts": note.get("moments") or [{"claim": k["point"], "timestamp": k.get("timestamp")}
                                              for k in note.get("key_points", [])],
            "predictions": note.get("predictions", [])[:6], "catalysts": note.get("catalysts", [])[:5],
            "rumors": note.get("rumors", [])[:3], "tickers": note.get("tickers", [])[:8]}
    body = V_PROMPT.format(brand=CFG["brand"]["name"], n=n, langs=", ".join(LANG[l] for l in langs),
                           rules=_rules("en"), short_rules=SHORT_RULES,
                           lang_fields=", ".join(f'"{l}": {{...}}' for l in langs),
                           note=json.dumps(view, ensure_ascii=False))
    feedback, out = "", {l: [] for l in langs}
    for attempt in (1, 2):
        data, meta = llm.ask("write", lambda k: body[:max(k, 9000)] + feedback, temperature=0.7, patience=1)
        out, bad = {l: [] for l in langs}, []
        for raw in (data.get("shorts") or [])[:n]:
            if not isinstance(raw, dict):
                continue
            for l in langs:
                sh = _one_short(raw.get(l) or {}, raw, origin, note["title"][:80])
                if not sh:
                    continue
                try:
                    _short_ok(sh, l)
                    out[l].append(sh)
                except llm.LLMError as e:
                    bad.append(str(e))
        if not bad or attempt == 2:         # second draft: keep the good ones, drop the rest
            break
        feedback = f"\n\nIMPORTANT: your previous answer was rejected ({bad[0]}). Fix exactly that.\n"
        log(f"    short scartati ({bad[0][:110]}): li faccio riscrivere")
    return out, meta


def upgrade(soc):
    """Shorts saved in an older format (no beats) still render: give them beats."""
    for s in soc.get("shorts", []):
        if not s.get("beats"):
            parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", s.get("narration", "")) if p.strip()]
            step = max(1, round(len(parts) / 5))
            groups = [" ".join(parts[i:i + step]) for i in range(0, len(parts), step)][:6] or [s.get("title", "")]
            s["beats"] = [{"say": g, "show": " ".join(re.sub(r"[.,:;!?]", "", g).split()[:3]), "figure": ""}
                          for g in groups]
            if s.get("hook"):
                s["beats"][0]["show"] = s["hook"]
        s["narration"] = " ".join(b["say"] for b in s["beats"])
        s.setdefault("hook", s["beats"][0]["show"])
        s.setdefault("origin", "news")
        s.setdefault("sources", [])
    return soc


def _check_deriv(d, script, kind):
    by_id = {s["id"]: s for s in script["segments"]}
    shorts = []
    creators = [c["name"] for c in CFG["channels"]]
    for s in (d.get("shorts") or []) if kind == "daily" else []:
        beats = [{"say": _t(x.get("say")), "show": _t(x.get("show"), 44), "figure": _t(x.get("figure"), 14)}
                 for x in (s.get("beats") or []) if isinstance(x, dict) and clean(x.get("say"))][:6]
        if len(beats) < 3:      # older format: build the beats from the sentences
            parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", _t(s.get("narration"))) if p.strip()]
            if len(parts) < 3:
                continue
            step = max(1, round(len(parts) / 5))
            groups = [" ".join(parts[i:i + step]) for i in range(0, len(parts), step)][:6]
            beats = [{"say": g, "show": " ".join(re.sub(r"[.,:;!?]", "", g).split()[:3]), "figure": ""} for g in groups]
            if clean(s.get("hook")):
                beats[0]["show"] = _t(s.get("hook"), 44)
        for b in beats:
            b["show"] = b["show"] or " ".join(b["say"].split()[:3])
        nar = " ".join(b["say"] for b in beats)
        if len(nar.split()) < 30:
            continue
        src = by_id.get(str(s.get("segment_id")), {})
        origin = str(s.get("origin") or "").strip()
        if origin not in creators:
            origin = next((x for x in src.get("sources", []) if x in creators), None)
        if not origin:
            continue            # headlines-only shorts are not made (stale and repetitive)
        shorts.append({"title": _t(s.get("title"), 90), "hook": beats[0]["show"], "beats": beats, "origin": origin,
                       "narration": nar, "ticker": _ticker(s.get("ticker")) or src.get("ticker"),
                       "sentiment": _sent(s.get("sentiment") or src.get("sentiment")),
                       "sources": src.get("sources", []),
                       "caption": _t(s.get("caption")),
                       "hashtags": [h if h.startswith("#") else "#" + h
                                    for h in (clean(x).replace(" ", "") for x in (s.get("hashtags") or [])) if h][:10]})
    shorts = shorts[:CFG["daily"]["shorts_max"]]
    cars = []
    for c in d.get("carousels") or []:
        slides = [{"title": _t(x.get("title"), 60), "body": _t(x.get("body"), 230)}
                  for x in (c.get("slides") or []) if isinstance(x, dict) and clean(x.get("title"))][:8]
        if len(slides) < 3:
            continue
        src = by_id.get(str(c.get("segment_id")), {})
        cars.append({"topic": _t(c.get("topic"), 60), "caption": tidy(str(c.get("caption") or "").strip()),
                     "sentiment": src.get("sentiment", "neutral"), "ticker": src.get("ticker"),
                     "hashtags": [h if h.startswith("#") else "#" + h
                                  for h in (clean(x).replace(" ", "") for x in (c.get("hashtags") or [])) if h][:14],
                     "slides": slides})
    cars = cars[:1 if kind == "weekly" else CFG["daily"]["max_carousels"]]
    return {"shorts": shorts, "carousels": cars}
