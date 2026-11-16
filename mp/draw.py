"""All the pictures: video frames, shorts frames, carousel slides, thumbnail. Pure Pillow."""
import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .core import ASSETS, CFG, clean

B = CFG["brand"]
SHOW_SOURCES = bool(CFG.get("credits", {}).get("on_screen", True))
L = {
    "it": {"hook": "IN APERTURA", "market": "MERCATI ADESSO", "topic": "FOCUS", "ahead": "PROSSIMI GIORNI",
           "curious": "IL CASO CURIOSO", "outro": "IN CHIUSURA", "bullish": "RIALZISTA",
           "bearish": "RIBASSISTA", "neutral": "NEUTRALE", "sources": "Fonti", "swipe": "Scorri",
           "months": "3 mesi", "follow": "Segui per l'aggiornamento di domani",
           "disclaimer": "Contenuto informativo, non consulenza finanziaria.", "weekly": "RECAP SETTIMANALE",
           "inside": "IN QUESTO CAROSELLO", "takeaway": "IN SINTESI"},
    "en": {"hook": "TODAY", "market": "MARKETS NOW", "topic": "FOCUS", "ahead": "COMING DAYS",
           "curious": "ODD ONE OUT", "outro": "WRAP-UP", "bullish": "BULLISH", "bearish": "BEARISH",
           "neutral": "NEUTRAL", "sources": "Sources", "swipe": "Swipe", "months": "3 months",
           "follow": "Follow for tomorrow's update",
           "disclaimer": "For information only, not financial advice.", "weekly": "WEEKLY RECAP",
           "inside": "INSIDE THIS CAROUSEL", "takeaway": "THE TAKEAWAY"},
}


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


BG, PANEL, TEXT, MUTED, ACCENT = (rgb(B[k]) for k in ("background", "panel", "text", "muted", "accent"))
SENT = {"bullish": rgb(B["bullish"]), "bearish": rgb(B["bearish"]), "neutral": rgb(B["neutral"])}
NAMES = {m["symbol"]: m["name"] for m in CFG.get("market", [])}
_W = {"r": "Regular", "m": "Medium", "s": "SemiBold", "b": "Bold", "x": "ExtraBold"}


@lru_cache(maxsize=256)
def font(weight, size):
    return ImageFont.truetype(str(ASSETS / "fonts" / f"Inter-{_W[weight]}.otf"), size)


def wrap(text, f, max_w):
    lines, cur = [], ""
    for word in clean(text).split():
        trial = (cur + " " + word).strip()
        if f.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit(text, weight, max_w, max_lines, size, min_size):
    """Largest font size at which the text fits in max_lines."""
    while True:
        f = font(weight, size)
        lines = wrap(text, f, max_w)
        if (len(lines) <= max_lines and all(f.getlength(x) <= max_w for x in lines)) or size <= min_size:
            if len(lines) > max_lines:
                lines = lines[:max_lines]
                while lines[-1] and f.getlength(lines[-1] + "...") > max_w:
                    lines[-1] = lines[-1][:-1]
                lines[-1] = lines[-1].rstrip() + "..."
            return f, lines
        size -= 4


def text_block(d, xy, lines, f, fill, gap=1.2, anchor="la"):
    x, y = xy
    for ln in lines:
        d.text((x, y), ln, font=f, fill=fill, anchor=anchor)
        y += round(f.size * gap)
    return y


@lru_cache(maxsize=16)
def backdrop(w, h, tint):
    """Dark background with a soft glow in one corner, for depth."""
    small = Image.new("RGB", (64, 64), BG)
    px = small.load()
    for yy in range(64):
        for xx in range(64):
            dist = (((xx - 56) / 46) ** 2 + ((yy - 4) / 40) ** 2) ** 0.5
            px[xx, yy] = mix(BG, tint, max(0.0, 0.20 * (1 - min(dist, 1.0)) ** 2))
    return small.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(max(w, h) // 28))


def chart(prices, w, h, color):
    """Line chart with a soft fill, drawn at 2x and reduced for smooth edges."""
    W, H = w * 2, h * 2
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    lo, hi = min(prices), max(prices)
    span = (hi - lo) or 1.0
    pad = 14
    pts = [(pad + i * (W - 2 * pad - 20) / (len(prices) - 1),
            pad + (H - 2 * pad) * (1 - (p - lo) / span)) for i, p in enumerate(prices)]
    d.polygon(pts + [(pts[-1][0], H), (pts[0][0], H)], fill=color + (38,))
    d.line(pts, fill=color + (255,), width=7, joint="curve")
    x, y = pts[-1]
    d.ellipse((x - 16, y - 16, x + 16, y + 16), fill=color + (255,))
    d.ellipse((x - 7, y - 7, x + 7, y + 7), fill=BG + (255,))
    return im.resize((w, h), Image.LANCZOS)


def _fmt(v, lang="en"):
    if v >= 1000:
        t = f"{v:,.0f}"
    else:
        t = f"{v:,.2f}" if v >= 10 else f"{v:,.4f}".rstrip("0").rstrip(".")
    return t.translate(str.maketrans(",.", ".,")) if lang == "it" else t


def chart_card(im, box, ticker, prices, lang):
    """Panel with symbol, last price, 3-month change and the line."""
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(box, 30, fill=PANEL)
    chg = (prices[-1] / prices[0] - 1) * 100
    col = SENT["bullish"] if chg >= 0 else SENT["bearish"]
    pad = 40
    d.text((x0 + pad, y0 + pad), NAMES.get(ticker, ticker.replace("^", "").replace("=X", "").replace("-USD", "")),
           font=font("s", 34), fill=MUTED)
    d.text((x0 + pad, y0 + pad + 48), _fmt(prices[-1], lang), font=font("x", 62), fill=TEXT)
    label = f"{chg:+.1f}%  {L[lang]['months']}"
    if lang == "it":
        label = label.replace(".", ",")
    f = font("b", 30)
    tw = f.getlength(label)
    d.rounded_rectangle((x1 - pad - tw - 36, y0 + pad + 4, x1 - pad, y0 + pad + 58), 27, fill=mix(PANEL, col, 0.22))
    d.text((x1 - pad - 18, y0 + pad + 31), label, font=f, fill=col, anchor="rm")
    top = y0 + pad + 150
    ch = chart(prices, x1 - x0 - 2 * pad, y1 - top - pad, col)
    im.paste(ch, (x0 + pad, top), ch)


def _chip(d, x, y, sentiment, lang, size=26, right=False):
    """Sentiment pill with an up/down marker. Returns its width."""
    col = SENT[sentiment]
    f = font("b", size)
    label = L[lang][sentiment]
    w = round(f.getlength(label)) + size * 2 + 26
    h = round(size * 1.9)
    if right:
        x -= w
    d.rounded_rectangle((x, y, x + w, y + h), h // 2, fill=mix(BG, col, 0.2))
    cx, cy, r = x + size, y + h // 2, size // 3 + 2
    if sentiment == "bullish":
        d.polygon([(cx - r, cy + r - 2), (cx + r, cy + r - 2), (cx, cy - r)], fill=col)
    elif sentiment == "bearish":
        d.polygon([(cx - r, cy - r + 2), (cx + r, cy - r + 2), (cx, cy + r)], fill=col)
    else:
        d.ellipse((cx - r + 1, cy - r + 1, cx + r - 1, cy + r - 1), fill=col)
    d.text((x + size * 2, cy), label, font=f, fill=col, anchor="lm")
    return w


def _caption(im, text, cy, max_w, weight, size, min_size, lines=1):
    if not text:
        return
    d = ImageDraw.Draw(im)
    f, ls = fit(text, weight, max_w, lines, size, min_size)
    lh = round(f.size * 1.22)
    tw = max(f.getlength(x) for x in ls)
    th = lh * len(ls)
    px, py = round(f.size * 0.55), round(f.size * 0.36)
    cx = im.width // 2
    d.rounded_rectangle((cx - tw / 2 - px, cy - th / 2 - py, cx + tw / 2 + px, cy + th / 2 + py),
                        round(f.size * 0.42), fill=mix(BG, PANEL, 0.5), outline=mix(PANEL, TEXT, 0.14), width=2)
    y = cy - th / 2 + lh / 2
    for ln in ls:
        d.text((cx, y), ln, font=f, fill=TEXT, anchor="mm")
        y += lh


def _progress(im, frac, h=10):
    d = ImageDraw.Draw(im)
    d.rectangle((0, im.height - h, im.width, im.height), fill=PANEL)
    d.rectangle((0, im.height - h, round(im.width * max(0.0, min(1.0, frac))), im.height), fill=ACCENT)


# ---------------------------------------------------------------- long video 1920x1080
class LongScene:
    W, H = 1920, 1080

    def __init__(self, seg, index, total, lang, date_label, prices=None, weekly=False):
        self.seg, self.index, self.total, self.lang = seg, index, total, lang
        self.date_label, self.prices, self.weekly = date_label, prices, weekly
        self._base = {}

    def base(self, n_bullets):
        if n_bullets in self._base:
            return self._base[n_bullets]
        s, lang = self.seg, self.lang
        col = SENT[s["sentiment"]]
        im = backdrop(self.W, self.H, col).copy()
        d = ImageDraw.Draw(im)
        m = 96
        d.text((m, 70), B["name"].upper(), font=font("x", 30), fill=ACCENT, anchor="lm")
        bw = font("x", 30).getlength(B["name"].upper())
        tag = self.date_label + ("   " + L[lang]["weekly"] if self.weekly else "")
        d.text((m + bw + 22, 70), tag, font=font("m", 28), fill=MUTED, anchor="lm")
        count = f"{self.index:02d} / {self.total:02d}"
        d.text((self.W - m, 70), count, font=font("s", 28), fill=MUTED, anchor="rm")
        cw = font("s", 28).getlength(count)
        if s["kind"] not in ("hook", "outro"):
            _chip(d, self.W - m - cw - 28, 45, s["sentiment"], lang, right=True)

        has_chart = bool(self.prices)
        text_w = 940 if has_chart else 1560
        d.text((m, 176), L[lang].get(s["kind"], L[lang]["topic"]), font=font("b", 30), fill=col, anchor="lm")
        f, lines = fit(s["heading"], "x", text_w, 2, 92, 60)
        y = text_block(d, (m, 214), lines, f, TEXT, gap=1.1)
        d.rounded_rectangle((m, y + 14, m + 132, y + 24), 5, fill=col)
        y += 78
        bf = font("s", 46)
        for b in s["bullets"][:n_bullets]:
            bl = wrap(b, bf, text_w - 56)[:2]
            d.rounded_rectangle((m, y + 18, m + 20, y + 38), 5, fill=col)
            y = text_block(d, (m + 56, y), bl, bf, TEXT, gap=1.24) + 26
        if s["kind"] == "outro":
            d.text((m, 760), L[lang]["disclaimer"], font=font("m", 32), fill=MUTED, anchor="lm")
        if has_chart:
            chart_card(im, (1100, 176, self.W - m, 800), s["ticker"], self.prices, lang)
        if s["sources"] and SHOW_SOURCES:
            src = f"{L[lang]['sources']}: " + "  ·  ".join(s["sources"])
            f2, l2 = fit(src, "m", self.W - 2 * m, 1, 28, 22)
            d.text((m, 846), l2[0], font=f2, fill=MUTED, anchor="lm")
        self._base[n_bullets] = im
        return im

    def frame(self, n_bullets, caption, progress):
        im = self.base(n_bullets).copy()
        _caption(im, caption, 952, 1560, "s", 46, 34)
        _progress(im, progress)
        return im


# ---------------------------------------------------------------- shorts 1080x1920
class ShortScene:
    W, H = 1080, 1920

    def __init__(self, short, lang, date_label, prices=None):
        self.s, self.lang, self.date_label, self.prices = short, lang, date_label, prices
        self._base = None

    def base(self):
        if self._base is not None:
            return self._base
        s, lang = self.s, self.lang
        col = SENT[s["sentiment"]]
        im = backdrop(self.W, self.H, col).copy()
        d = ImageDraw.Draw(im)
        m = 72
        d.text((m, 190), B["name"].upper(), font=font("x", 34), fill=ACCENT, anchor="lm")
        bw = font("x", 34).getlength(B["name"].upper())
        d.text((m + bw + 20, 190), self.date_label, font=font("m", 30), fill=MUTED, anchor="lm")
        _chip(d, m, 250, s["sentiment"], lang, size=30)
        f, lines = fit(s["hook"] or s["title"], "x", self.W - 2 * m - 60, 4, 96, 64)
        y = text_block(d, (m, 350), lines, f, TEXT, gap=1.1)
        d.rounded_rectangle((m, y + 18, m + 150, y + 30), 6, fill=col)
        self.cap_y = 1330
        if self.prices:
            top = max(y + 90, 820)
            chart_card(im, (m, top, self.W - m, top + 390), s["ticker"], self.prices, lang)
            self.cap_y = top + 390 + 190
        else:
            self.cap_y = max(y + 330, 1120)
        if s.get("sources") and SHOW_SOURCES:
            src = f"{L[lang]['sources']}: " + " · ".join(s["sources"][:3])
            f2, l2 = fit(src, "m", self.W - 2 * m - 140, 1, 28, 22)
            d.text((m, 1610), l2[0], font=f2, fill=MUTED, anchor="lm")
        self._base = im
        return im

    def frame(self, caption, progress):
        im = self.base().copy()
        _caption(im, caption, self.cap_y, self.W - 200, "x", 84, 56, lines=2)
        _progress(im, progress, h=12)
        return im


# ---------------------------------------------------------------- carousel 1080x1350
_HOT = re.compile(r"\d|%|\$|€")


def rich(d, x, y, lines, f, base, hot, gap=1.1):
    """Text block where figures (numbers, %, prices) take the accent colour."""
    space = f.getlength(" ")
    for ln in lines:
        cx = x
        for word in ln.split(" "):
            d.text((cx, y), word, font=f, fill=hot if _HOT.search(word) else base)
            cx += f.getlength(word) + space
        y += round(f.size * gap)
    return y


def _pill(d, x, y, text, f, fill, ink, pad=(26, 13)):
    w = round(f.getlength(text)) + pad[0] * 2
    h = f.size + pad[1] * 2
    d.rounded_rectangle((x, y, x + w, y + h), h // 2, fill=fill)
    d.text((x + pad[0], y + h / 2), text, font=f, fill=ink, anchor="lm")
    return w, h


def _swipe(d, W, H, m, lang, col):
    """Bottom-right call to action: a solid pill with an arrow."""
    f = font("x", 34)
    label = L[lang]["swipe"]
    w = round(f.getlength(label)) + 128
    x0, y0 = W - m - w, H - 150
    d.rounded_rectangle((x0, y0, x0 + w, y0 + 84), 42, fill=col)
    d.text((x0 + 38, y0 + 42), label, font=f, fill=BG, anchor="lm")
    ax, ay = x0 + w - 36, y0 + 42
    d.line((ax - 40, ay, ax, ay), fill=BG, width=6)
    d.polygon([(ax + 6, ay), (ax - 16, ay - 15), (ax - 16, ay + 15)], fill=BG)


def _dots(d, m, y, n, i, col):
    for k in range(n):
        x = m + k * 30
        d.ellipse((x, y - 7, x + 14, y + 7), fill=col if k == i else mix(BG, MUTED, 0.45))


def _cover(car, lang, date_label, prices, W, H, m, col):
    """Slide 1: stop the scroll (big hook, key figures in colour, price line behind)
    and preview what the next slides contain."""
    slides, n = car["slides"], len(car["slides"])
    im = backdrop(W, H, col).copy()
    if prices:
        up = prices[-1] >= prices[0]
        ch = chart(prices, W, 520, SENT["bullish"] if up else SENT["bearish"])
        faded = Image.blend(Image.new("RGBA", ch.size, (0, 0, 0, 0)), ch, 0.5)
        im.paste(faded, (0, 250), faded)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 14), fill=col)
    d.text((m, 104), B["name"].upper(), font=font("x", 32), fill=ACCENT, anchor="lm")
    if date_label:
        d.text((W - m, 104), date_label, font=font("s", 30), fill=MUTED, anchor="rm")
    _pill(d, m, 176, clean(car["topic"]).upper(), font("x", 28), col, BG)

    # preview of the next slides, anchored to the bottom
    items = [s["title"] for s in slides[1:-1]][:3] or [s["title"] for s in slides[1:]][:3]
    row, head = 66, 58
    box_h = head + row * len(items) + 30
    box_top = H - 190 - box_h
    # hook: as large as the remaining room allows
    room = box_top - 40 - 270
    teaser = slides[0].get("body", "")
    for size in (132, 120, 108, 96, 88, 80, 72, 64):
        f = font("x", size)
        lines = wrap(slides[0]["title"], f, W - 2 * m)
        f2 = font("m", 40)
        l2 = wrap(teaser, f2, W - 2 * m)[:2] if teaser else []
        need = len(lines) * round(size * 1.06) + (34 + len(l2) * 54 if l2 else 0)
        if need <= room and all(f.getlength(x) <= W - 2 * m for x in lines):
            break
        if size <= 88 and l2:               # still too tall: drop the teaser before shrinking more
            l2, need = [], len(lines) * round(size * 1.06)
            if need <= room:
                break
    y = rich(d, m, 270 + max(0, (room - need) // 3), lines, f, TEXT, col, gap=1.06)
    if l2:
        text_block(d, (m, y + 26), l2, f2, mix(TEXT, MUTED, 0.45), gap=1.32)

    d.rounded_rectangle((m, box_top, W - m, box_top + box_h), 30, fill=mix(BG, PANEL, 0.92),
                        outline=mix(PANEL, col, 0.5), width=2)
    d.text((m + 34, box_top + 38), L[lang]["inside"], font=font("x", 24), fill=col, anchor="lm")
    yy = box_top + head + 14
    for k, title in enumerate(items):
        d.text((m + 34, yy + row / 2 - 6), f"{k + 2:02d}", font=font("x", 34), fill=col, anchor="lm")
        ft, tl = fit(title, "s", W - 2 * m - 150, 1, 36, 28)
        d.text((m + 106, yy + row / 2 - 6), tl[0], font=ft, fill=TEXT, anchor="lm")
        yy += row
    _dots(d, m, H - 108, n, 0, col)
    _swipe(d, W, H, m, lang, col)
    return im


def carousel(car, lang, folder, date_label="", prices=None):
    """Write the slides as PNG and return their paths."""
    W, H, m = 1080, 1350, 84
    folder.mkdir(parents=True, exist_ok=True)
    col = SENT.get(car.get("sentiment", "neutral"), ACCENT)
    slides, paths = car["slides"], []
    n = len(slides)
    for i, s in enumerate(slides):
        last = i == n - 1
        if i == 0:
            im = _cover(car, lang, date_label, prices, W, H, m, col)
        else:
            im = backdrop(W, H, col).copy()
            d = ImageDraw.Draw(im)
            d.rectangle((0, 0, W, 14), fill=col)
            d.text((m, 104), B["name"].upper(), font=font("x", 32), fill=ACCENT, anchor="lm")
            d.text((W - m, 104), f"{i + 1}/{n}", font=font("s", 30), fill=MUTED, anchor="rm")
            f, lines = fit(s["title"], "x", W - 2 * m, 3, 92, 60)
            f2, l2 = fit(s.get("body", ""), "m", W - 2 * m - 80, 9, 54, 38)
            card_h = 70 + len(l2) * round(f2.size * 1.36)
            h = 150 + len(lines) * round(f.size * 1.1) + 60 + card_h
            y = 210 + max(0, (H - 250 - 210 - h) * 0.4)
            if last:
                _pill(d, m, y + 20, L[lang]["takeaway"], font("x", 28), col, BG)
            else:
                d.rounded_rectangle((m, y, m + 112, y + 112), 26, fill=col)
                d.text((m + 56, y + 56), f"{i + 1:02d}", font=font("x", 58), fill=BG, anchor="mm")
            y = rich(d, m, y + 150, lines, f, TEXT, col, gap=1.1)
            d.rounded_rectangle((m, y + 34, W - m, y + 34 + card_h), 28, fill=mix(BG, PANEL, 0.9))
            d.rounded_rectangle((m, y + 34, m + 10, y + 34 + card_h), 5, fill=col)
            rich(d, m + 44, y + 34 + 36, l2, f2, mix(TEXT, MUTED, 0.15), TEXT, gap=1.36)
            _dots(d, m, H - 108, n, i, col)
            if last:
                tail = (B.get("handle") or "").strip() or L[lang]["follow"]
                f3, l3 = fit(tail, "x", W - 2 * m - n * 30 - 110, 1, 32, 22)
                tw = round(f3.getlength(l3[0])) + 64
                d.rounded_rectangle((W - m - tw, H - 150, W - m, H - 66), 42, fill=col)
                d.text((W - m - tw / 2, H - 108), l3[0], font=f3, fill=BG, anchor="mm")
                d.text((m, H - 196), L[lang]["disclaimer"], font=font("m", 26), fill=MUTED, anchor="lm")
            else:
                _swipe(d, W, H, m, lang, col)
        p = folder / f"slide_{i + 1:02d}.png"
        im.save(p, optimize=True)
        paths.append(p)
    return paths


# ---------------------------------------------------------------- thumbnail 1280x720
def thumbnail(script, lang, date_label, path, prices=None):
    W, H, m = 1280, 720, 64
    tops = [s for s in script["segments"] if s["kind"] in ("market", "topic")]
    sent = tops[0]["sentiment"] if tops else "neutral"
    col = SENT[sent]
    im = backdrop(W, H, col).copy()
    d = ImageDraw.Draw(im)
    if prices:
        ch = chart(prices, W - 2 * m, 330, col)
        faded = Image.new("RGBA", ch.size, (0, 0, 0, 0))
        faded = Image.blend(faded, ch, 0.45)
        im.paste(faded, (m, 330), faded)
    d.text((m, 78), B["name"].upper(), font=font("x", 36), fill=ACCENT, anchor="lm")
    d.text((W - m, 78), date_label, font=font("s", 32), fill=MUTED, anchor="rm")
    text = (script.get("thumbnail_text") or script["title"]).upper()
    f, lines = fit(text, "x", W - 2 * m, 3, 168, 84)
    y = text_block(d, (m, 150), lines, f, TEXT, gap=1.04)
    d.rounded_rectangle((m, min(y + 16, H - 60), m + 220, min(y + 34, H - 42)), 9, fill=col)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=92)
    return path
