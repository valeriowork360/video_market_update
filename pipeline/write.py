"""Turns analysed notes + headlines into scripts for long video, shorts, carousels."""
import json

from common import CFG, ask_json

LANG_NAME = {"it": "Italian", "en": "English"}

TONE_GUIDE = {
    "news": "authoritative news anchor: clear, measured, confident, short sentences",
    "energetic": "energetic finance creator: punchy, fast, enthusiastic but not hype",
    "calm": "calm analyst: slow, reassuring, explanatory",
}

PROMPT = """You are the head writer of "{brand}", a FACELESS stock-market news channel.
Write in native, natural {lang} (not a translation). Narrator style: {tone}.

KIND: {kind}. Target length of the long video narration: about {words} words.

Inputs below: (A) analyses of videos published by creators we follow, each with
the author's tone; (B) market headlines.

RULES
- Lead with what is moving the market NOW, then what could move it next (catalysts, dates).
- Compare creators: where they agree, where they disagree, and their tone
  (e.g. "Jason Pizzino is cautious, while Financial Education is bullish on ...").
- Always attribute opinions ("according to Marco Casario..."). Paraphrase, never quote
  more than 10 words. We never reuse their footage.
- Curious/sensational stories are welcome ONLY if present in the inputs; label anything
  unverified as a rumor. Never invent facts, numbers, or prices.
- No buy/sell advice. The outro must contain a one-line "not financial advice" disclaimer.
- Each segment should be one topic. Use a ticker when the topic is about one stock/index
  (e.g. NVDA, ^GSPC, ^IXIC, BTC-USD), otherwise null.

Return JSON:
{{
  "title": "YouTube title, <70 chars, curiosity-driven, no clickbait lies",
  "description": "YouTube description, 3-6 lines, list creators credited",
  "tags": ["..."],
  "segments": [
    {{"id": "s1", "heading": "<=5 words", "narration": "...", "bullets": ["<=8 words", "..."],
      "ticker": "NVDA or null", "sentiment": "bullish|bearish|neutral", "sources": ["creator or outlet"]}}
  ],
  "shorts": [
    {{"hook": "first line, <=10 words", "narration": "self-contained, 90-130 words",
      "segment_id": "s2", "ticker": "or null", "sentiment": "bullish|bearish|neutral",
      "caption": "post caption", "hashtags": ["#..."]}}
  ],
  "carousels": [
    {{"topic": "...", "caption": "Instagram caption with CTA", "hashtags": ["#..."],
      "slides": [{{"title": "<=6 words", "body": "<=30 words"}}]}}
  ]
}}
Constraints: first segment is a hook intro, last is outro. {shorts_rule}
Carousels: one per main topic, 5-8 slides each, slide 1 is a hook, last slide is a CTA.

(A) CREATOR ANALYSES:
{notes}

(B) HEADLINES:
{news}
"""


def build(notes, news, lang, kind="daily"):
    minutes = CFG["weekly_minutes"] if kind == "weekly" else CFG["daily_minutes"]
    if kind == "weekly":
        kind_txt = "WEEKLY RECAP of the past 7 days: biggest moves, who was right, what's next week"
        shorts_rule = "shorts: return an empty list."
    else:
        kind_txt = "DAILY BRIEFING for today"
        shorts_rule = f"shorts: {CFG['shorts_min']}-{CFG['shorts_max']} items, one per strong topic."
    slim = [{k: n.get(k) for k in ("author", "title", "summary", "author_tone", "tone_evidence",
                                    "key_points", "tickers", "predictions", "catalysts", "rumors",
                                    "is_sponsored_or_promo")} for n in notes]
    prompt = PROMPT.format(
        brand=CFG["brand"]["name"], lang=LANG_NAME[lang],
        tone=TONE_GUIDE.get(CFG["narrator_tone"], TONE_GUIDE["news"]),
        kind=kind_txt, words=int(minutes * 150), shorts_rule=shorts_rule,
        notes=json.dumps(slim, ensure_ascii=False)[:250000],
        news=json.dumps([{"t": n["title"], "s": n["source"]} for n in news], ensure_ascii=False))
    return ask_json(prompt)
