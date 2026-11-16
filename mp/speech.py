"""Two forms of the same text.

The scripts are written the way they must APPEAR ("S&P 500", "BTC", "-0,4%", "$68.700").
  speakable() turns that into what the voice should SAY ("S and P 500", "Bitcoin",
              "meno 0,4 per cento", "68.700 dollari").
  tidy()      repairs on-screen text if a model spelled something phonetically anyway.
  timings()   puts the voice's word timings back on the written words, so captions show
              the correct spelling while staying in sync.
"""
import re
from difflib import SequenceMatcher

# ticker / acronym -> how it is said (same in both languages unless a dict is given)
SAY = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "XRP": "Ripple", "ADA": "Cardano",
    "DOGE": "Dogecoin", "BNB": "Binance Coin", "USDT": "Tether",
    "NVDA": "Nvidia", "TSLA": "Tesla", "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet",
    "GOOG": "Alphabet", "AMZN": "Amazon", "META": "Meta", "NFLX": "Netflix", "PLTR": "Palantir",
    "MSTR": "MicroStrategy", "COIN": "Coinbase", "INTC": "Intel", "AVGO": "Broadcom",
    "SPX": "S and P 500", "SPY": "S and P 500", "NDX": "Nasdaq 100", "QQQ": "Nasdaq 100",
    "DJI": "Dow Jones", "DXY": "Dollar Index",
    "FTSE MIB": {"it": "Futsi Mib", "en": "Footsie MIB"},
    "YoY": {"it": "anno su anno", "en": "year over year"},
    "QoQ": {"it": "trimestre su trimestre", "en": "quarter over quarter"},
    "vs": {"it": "contro", "en": "versus"}, "vs.": {"it": "contro", "en": "versus"},
    "EUR/USD": {"it": "euro dollaro", "en": "euro dollar"},
    "USD": {"it": "dollari", "en": "dollars"}, "EUR": "euro",
}
_ORD = {"it": ["primo", "secondo", "terzo", "quarto"], "en": ["first", "second", "third", "fourth"]}
_W = {"it": {"pct": "per cento", "usd": "dollari", "eur": "euro", "plus": "più", "minus": "meno",
             "k": "mila", "and": "e", "q": "trimestre", "y": "anni"},
      "en": {"pct": "percent", "usd": "dollars", "eur": "euros", "plus": "plus", "minus": "minus",
             "k": "thousand", "and": "and", "q": "quarter", "y": "year"}}
_SCALE = r"(?:miliardi|milioni|mila|migliaia|billion|million|trillion|thousand|bilioni|trilioni)"
_NUM = r"\d[\d.,]*\d|\d"


def _say(key, lang):
    v = SAY[key]
    return v[lang] if isinstance(v, dict) else v


def speakable(text, lang):
    """Written text -> text for the voice. Deterministic, so nothing depends on the AI spelling
    things 'by ear'."""
    w = _W[lang]
    t = " " + text + " "
    t = re.sub(r"\s*\((?:(?:NASDAQ|NYSE|Nasdaq)\s*:\s*)?[A-Z]{1,5}(?:[-.][A-Z]{1,4})?\)", "", t)   # "(NVDA)"
    t = re.sub(r"S\s?&\s?P\s?500", "S and P 500", t)
    t = re.sub(r"S\s?&\s?P", "S and P", t)
    for key in sorted(SAY, key=len, reverse=True):
        t = re.sub(rf"(?<![\w&]){re.escape(key)}(?![\w&])", lambda m: _say(key, lang), t)
    t = re.sub(r"\bQ([1-4])\b", lambda m: (f"{_ORD[lang][int(m.group(1)) - 1]} {w['q']}"), t)
    t = re.sub(r"\b(\d{1,2})[Yy]\b", lambda m: (f"a {m.group(1)} {w['y']}" if lang == "it" else f"{m.group(1)}-{w['y']}"), t)
    # money: "$5,6 miliardi" / "$68.700" / "68.700$" / "€30"
    for sym, name in (("$", w["usd"]), ("€", w["eur"])):
        s = re.escape(sym)
        t = re.sub(rf"{s}\s?({_NUM})\s?({_SCALE})", lambda m: f"{m.group(1)} {m.group(2)} "
                   + ("di " if lang == "it" else "") + name, t)
        t = re.sub(rf"{s}\s?({_NUM})\s?[kK]\b", lambda m: f"{m.group(1)} {w['k']} {name}", t)
        t = re.sub(rf"{s}\s?({_NUM})", lambda m: f"{m.group(1)} {name}", t)
        t = re.sub(rf"({_NUM})\s?{s}", lambda m: f"{m.group(1)} {name}", t)
    t = re.sub(rf"\b({_NUM})\s?[kK]\b", lambda m: f"{m.group(1)} {w['k']}", t)
    # signs and percent: "+3,2%" -> "più 3,2 per cento"
    t = re.sub(rf"(?<=[\s(])\+\s?(?={_NUM})", w["plus"] + " ", t)
    t = re.sub(rf"(?<=[\s(])[-−]\s?(?=(?:{_NUM})\s?%)", w["minus"] + " ", t)
    t = re.sub(r"\s?%", " " + w["pct"], t)
    t = re.sub(r"(?<=\w)\s?&\s?(?=[A-Z])", " and ", t)            # brand names: "AT&T"
    t = re.sub(r"(?<=\w)\s?&\s?(?=\w)", f" {w['and']} ", t)
    t = re.sub(r"(?<=[A-Za-z])/(?=[A-Za-z])", " ", t)
    t = t.replace("#", "").replace("*", "").replace("_", " ")
    return re.sub(r"\s+", " ", t).strip()


_FIX = [  # phonetic spellings a model may still produce -> the correct written form
    (r"\bS\s?(?:and|e|&)\s?P\s?(?:500|cinquecento|five hundred)\b", "S&P 500"),
    (r"\bS&P\s?500\b", "S&P 500"), (r"\bSP\s?500\b", "S&P 500"),
    (r"\bStandard (?:and|&) Poor'?s 500\b", "S&P 500"),
    (r"\bS\s(?:and|e)\sP\b", "S&P"),
    (r"(?<=\d)\s?(?:per cento|percento|percent)\b", "%"),
    (r"\bnasdaq\b", "Nasdaq"), (r"\bbit\s?coin\b", "Bitcoin"), (r"\bethereum\b", "Ethereum"),
    (r"\bnvidia\b", "Nvidia"), (r"\bwall street\b", "Wall Street"), (r"\bdow jones\b", "Dow Jones"),
    (r"\bftse\s?mib\b", "FTSE MIB"), (r"\beuro\s?stoxx\b", "Euro Stoxx"),
    (r"\b(btc|eth|etf|ipo|ceo|cfo|pil|gdp|cpi|ppi|vix|bce|ecb|sec|nyse|usa)\b", None),   # upper-case
]


def tidy(text):
    """On-screen spelling of market terms, whatever the model wrote."""
    t = str(text or "")
    for pat, rep in _FIX:
        if rep is None:
            t = re.sub(pat, lambda m: m.group(0).upper(), t, flags=re.I)
        else:
            t = re.sub(pat, rep, t, flags=re.I)
    return t


def _norm(word):
    return re.sub(r"[^\w]+", "", word.lower())


def timings(written, spoken, events, total):
    """Start time of every word of `written`, from the voice timings measured on `spoken`.

    events: [{t, d, w}] reported by the voice. Shared words map one to one; where the two
    texts differ ("S&P" written, "S and P" said) the written words are spread over the
    spoken ones they replace.
    """
    dw, sw = written.split(), spoken.split()
    if not dw:
        return []
    end = max(total - 0.3, 0.0)
    st = [None] * len(sw)
    if events:
        m = SequenceMatcher(None, [_norm(x) for x in sw], [_norm(e["w"]) for e in events], autojunk=False)
        for a, b, n in m.get_matching_blocks():
            for k in range(n):
                st[a + k] = events[b + k]["t"]
    # spoken words the voice did not report: straight line between their neighbours
    pts = [(-1, 0.0)] + [(i, t) for i, t in enumerate(st) if t is not None] + [(len(sw), end)]
    for (i0, t0), (i1, t1) in zip(pts, pts[1:]):
        for i in range(i0 + 1, i1):
            st[i] = t0 + (t1 - t0) * (i - i0) / (i1 - i0) if i0 >= 0 or events else end * i / max(len(sw), 1)
    at = lambda j: st[j] if j < len(sw) else end      # noqa: E731
    dt = [0.0] * len(dw)
    m = SequenceMatcher(None, [_norm(x) for x in dw], [_norm(x) for x in sw], autojunk=False)
    for tag, i1, i2, j1, j2 in m.get_opcodes():
        if tag == "insert":
            continue
        for k in range(i2 - i1):
            if tag == "equal":
                dt[i1 + k] = at(j1 + k)
            elif tag == "replace":
                dt[i1 + k] = at(j1 + k * (j2 - j1) // (i2 - i1))
            else:                                       # written only: said together with what follows
                dt[i1 + k] = at(j1)
    out = [{"t": max(0.0, t), "d": 0.0, "w": w} for t, w in zip(dt, dw)]
    for i in range(1, len(out)):                        # never go backwards
        out[i]["t"] = max(out[i]["t"], out[i - 1]["t"])
    return out
