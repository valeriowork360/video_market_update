"""Animated shorts (1080x1920, 30 fps), drawn frame by frame.

Every short is a sequence of BEATS (hook, context, twist, stakes, payoff). Each beat has its
own big on-screen punchline that animates in, a key figure that counts up, word-by-word
captions, a chart line that draws itself, and a colour that says which channel the idea
comes from.
"""
import re
import subprocess

from PIL import Image, ImageDraw, ImageFilter

from .core import CFG, clean, log
from .draw import B, BG, L, MUTED, NAMES, PANEL, SENT, TEXT, _fmt, chart, font, mix, rgb, wrap

W, H, FPS = 1080, 1920, 30
M = 72
DARK = (7, 9, 13)


def origin_color(origin):
    for ch in CFG["channels"]:
        if ch["name"] == origin and ch.get("color"):
            return rgb(ch["color"])
    return rgb(CFG.get("publish_colors", {}).get("news", "#A9B6C6"))


def ease(p):
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3


def back(p):
    """Ease-out with a small overshoot: the 'pop'."""
    p = max(0.0, min(1.0, p)) - 1
    return 1 + 2.2 * p ** 3 + 1.2 * p ** 2


def _background(col):
    """Dark field with coloured glows and a fine grid; larger than the frame so it can drift."""
    w, h = 150, 240
    small = Image.new("RGB", (w, h), DARK)
    px = small.load()
    blobs = [(120, 30, 95, 0.55), (20, 150, 90, 0.38), (110, 225, 70, 0.30)]
    for y in range(h):
        for x in range(w):
            a = 0.0
            for bx, by, r, k in blobs:
                dist = ((x - bx) ** 2 + (y - by) ** 2) ** 0.5 / r
                a += k * max(0.0, 1 - dist) ** 2
            px[x, y] = mix(DARK, col, min(a, 0.7))
    big = small.resize((1500, 2400), Image.BICUBIC).filter(ImageFilter.GaussianBlur(40))
    d = ImageDraw.Draw(big)
    line = mix(DARK, col, 0.16)
    for x in range(0, 1500, 100):
        d.line((x, 0, x, 2400), fill=line, width=1)
    for y in range(0, 2400, 100):
        d.line((0, y, 1500, y), fill=line, width=1)
    return big


def _layer(text, f, fill, hot=None):
    """One line of text as an RGBA image; figures take the `hot` colour."""
    w = int(f.getlength(text)) + 24
    im = Image.new("RGBA", (w, int(f.size * 1.28)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x, space = 4, f.getlength(" ")
    for word in text.split(" "):
        d.text((x, 0), word, font=f, fill=(hot if hot and re.search(r"\d|%|\$|€", word) else fill) + (255,))
        x += f.getlength(word) + space
    return im


def _put(im, layer, x, y, a=1.0):
    if a <= 0.02:
        return
    if a >= 0.99:
        im.paste(layer, (int(x), int(y)), layer)
    else:
        im.paste(layer, (int(x), int(y)), layer.getchannel("A").point(lambda v: int(v * a)))


def _fit_lines(text, weight, max_w, max_lines, size, min_size):
    while True:
        f = font(weight, size)
        lines = wrap(text, f, max_w)
        if (len(lines) <= max_lines and all(f.getlength(x) <= max_w for x in lines)) or size <= min_size:
            return f, lines[:max_lines]
        size -= 8


def countup(fig, p, lang):
    """'-7,1%' at progress p -> '-3,6%': the figure runs up to its value."""
    m = re.search(r"\d[\d.,]*\d|\d", fig or "")
    if not m or p >= 0.999:
        return fig
    raw = m.group(0)
    dec_sep, th_sep = (",", ".") if lang == "it" else (".", ",")
    try:
        whole, _, frac = raw.replace(th_sep, "").partition(dec_sep)
        val = float(whole + "." + (frac or "0"))
    except ValueError:
        return fig
    s = f"{val * p:,.{len(frac)}f}"
    if lang == "it":
        s = s.translate(str.maketrans(",.", ".,"))
    if th_sep not in raw:
        s = s.replace(th_sep, "")
    return fig[:m.start()] + s + fig[m.end():]


def _chunks(words):
    out, cur = [], []
    for w in words:
        if cur and (len(" ".join(x["w"] for x in cur + [w])) > 20 or len(cur) >= 3):
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?;:]$", w["w"]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _captions(d, chunk, t, col):
    if not chunk:
        return
    size = 76
    while True:
        f = font("x", size)
        space = f.getlength(" ")
        widths = [f.getlength(w["w"]) for w in chunk]
        total = sum(widths) + space * (len(chunk) - 1)
        if total <= W - 150 or size <= 48:
            break
        size -= 6
    x, y = (W - total) / 2, 1400
    pad = 26
    d.rounded_rectangle((x - pad - 6, y - 22, x + total + pad + 6, y + size + 34), 30, fill=DARK)
    active = max((i for i, w in enumerate(chunk) if w["t"] <= t + 1e-3), default=0)
    for i, (w, wd) in enumerate(zip(chunk, widths)):
        if i == active:
            d.rounded_rectangle((x - 12, y - 6, x + wd + 12, y + size + 18), 16, fill=col)
            d.text((x, y), w["w"], font=f, fill=DARK)
        else:
            d.text((x, y), w["w"], font=f, fill=TEXT if i < active else mix(TEXT, DARK, 0.45))
        x += wd + space


class Short:
    def __init__(self, short, lang, color, words, dur, prices=None):
        self.s, self.lang, self.col, self.dur, self.prices = short, lang, color, dur, prices
        self.bg = _background(color)
        beats, starts, k = short["beats"], [], 0
        for b in beats:
            starts.append(words[min(k, len(words) - 1)]["t"] if words else 0.0)
            k += len(b["say"].split())
        starts[0] = 0.0
        self.beats, self.starts = beats, starts
        self.chunks = _chunks(words)
        self.cache = {}
        tape = f"{B['name'].upper()}   •   {clean(short['title']).upper()}   •   "
        f = font("b", 30)
        tw = int(f.getlength(tape))
        self.tape = Image.new("RGB", (tw, 58), mix(DARK, color, 0.22))
        ImageDraw.Draw(self.tape).text((0, 29), tape, font=f, fill=mix(TEXT, color, 0.35), anchor="lm")
        if prices:
            up = prices[-1] >= prices[0]
            self.ccol = SENT["bullish"] if up else SENT["bearish"]
            self.chart = chart(prices, W - 2 * M - 80, 170, self.ccol)

    def _beat_layers(self, i):
        if i in self.cache:
            return self.cache[i]
        b = self.beats[i]
        hook = i == 0
        fill = DARK if hook else TEXT
        max_w = W - 2 * M - (40 if hook else 0)
        f, lines = _fit_lines(clean(b["show"]).upper(), "x", max_w, 4 if hook else 3,
                              184 if hook else (108 if self.prices else 132), 76)
        layers = [_layer(x, f, fill, None if hook else self.col) for x in lines]
        self.cache[i] = (f, layers)
        return self.cache[i]

    def _chart_card(self, im, d, tb):
        y0, y1 = 1010, 1300
        a = ease(tb / 0.35)
        off = (1 - a) * 60
        d.rounded_rectangle((M, y0 + off, W - M, y1 + off), 32, fill=mix(DARK, PANEL, 0.9))
        name = NAMES.get(self.s["ticker"], str(self.s["ticker"]).replace("^", "").replace("-USD", ""))
        d.text((M + 36, y0 + 44 + off), name, font=font("s", 34), fill=MUTED, anchor="lm")
        chg = (self.prices[-1] / self.prices[0] - 1) * 100
        lab = f"{chg:+.1f}%  {L[self.lang]['months']}"
        d.text((W - M - 36, y0 + 44 + off), lab.replace(".", ",") if self.lang == "it" else lab,
               font=font("x", 34), fill=self.ccol, anchor="rm")
        reveal = ease((tb - 0.15) / 1.3)
        cw = max(2, int(self.chart.width * reveal))
        part = self.chart.crop((0, 0, cw, self.chart.height))
        im.paste(part, (M + 40, int(y0 + 90 + off)), part)

    def frame(self, t):
        i = max(k for k, s in enumerate(self.starts) if s <= t + 1e-6)
        tb = t - self.starts[i]
        b, col, hook, last = self.beats[i], self.col, i == 0, i == len(self.beats) - 1
        if hook:
            im = Image.new("RGB", (W, H), col)
            d = ImageDraw.Draw(im)
            stripe = mix(col, DARK, 0.10)
            shift = int(t * 160) % 240
            for x in range(-H, W + 240, 240):          # moving diagonal bands
                d.polygon([(x + shift, 0), (x + shift + 90, 0), (x + shift + 90 - H * 0.5, H),
                           (x + shift - H * 0.5, H)], fill=stripe)
        else:
            import math
            ox = int(210 + 190 * math.sin(t * 0.55))
            oy = int(240 + 220 * math.cos(t * 0.4))
            im = self.bg.crop((ox, oy, ox + W, oy + H))
            d = ImageDraw.Draw(im)

        # story-style progress and the running tape
        n = len(self.beats)
        seg = (W - 2 * M - 10 * (n - 1)) / n
        for k in range(n):
            x0 = M + k * (seg + 10)
            end = self.starts[k + 1] if k + 1 < n else self.dur
            p = 1.0 if k < i else (min(1.0, (t - self.starts[k]) / max(end - self.starts[k], 0.1)) if k == i else 0.0)
            d.rounded_rectangle((x0, 120, x0 + seg, 132), 6, fill=mix(DARK, TEXT, 0.25) if not hook else mix(col, DARK, 0.3))
            if p > 0:
                d.rounded_rectangle((x0, 120, x0 + seg * p, 132), 6, fill=TEXT if not hook else DARK)
        off = int(t * 110) % self.tape.width
        for x in range(-off, W, self.tape.width):
            im.paste(self.tape, (x, 168))

        # key figure, counting up
        y = 330 if not hook else 0
        fig = clean(b.get("figure") or "")
        f, layers = self._beat_layers(i)
        if hook:
            block = len(layers) * int(f.size * 1.06) + (250 if fig else 0)
            y = 300 + max(0, (980 - block) // 2)
        if fig:
            ff, _ = _fit_lines(fig, "x", W - 2 * M, 1, 230 if hook else (180 if self.prices else 250), 110)
            d.text((M, y), countup(fig, ease(tb / 0.7), self.lang), font=ff, fill=DARK if hook else col)
            y += int(ff.size * 1.12)
        # punchline: lines pop in one after the other
        zoom = 1 + 0.22 * (1 - ease(tb / 0.28)) if hook else 1.0
        for k, layer in enumerate(layers):
            p = (tb - 0.05 - k * 0.09) / 0.32
            if p <= 0:
                break
            e = back(p)
            lay = layer
            if zoom > 1.01:
                lay = layer.resize((int(layer.width * zoom), int(layer.height * zoom)), Image.BILINEAR)
            _put(im, lay, M - (1 - e) * 140, y, min(1.0, p * 1.6))
            y += int(f.size * 1.06)
        if not hook:
            d.rounded_rectangle((M, y + 22, M + 170 * ease(tb / 0.5), y + 36), 7, fill=col)
        if self.prices and not hook:
            self._chart_card(im, d, t - self.starts[1])
        elif last:
            pulse = 1 + 0.04 * abs(((t * 2) % 2) - 1)
            f3 = font("x", int(40 * pulse))
            lab = (B.get("handle") or "").strip() or L[self.lang]["follow"]
            tw = f3.getlength(lab) + 90
            d.rounded_rectangle(((W - tw) / 2, 1130, (W + tw) / 2, 1230), 50, fill=col)
            d.text((W / 2, 1180), lab, font=f3, fill=DARK, anchor="mm")

        chunk = next((c for c in reversed(self.chunks) if c[0]["t"] <= t + 1e-3), self.chunks[0] if self.chunks else None)
        _captions(d, chunk, t, col)

        # a colour band sweeps the screen at every beat change
        if i > 0 and tb < 0.24:
            p = tb / 0.24
            d.rectangle((0, H * p - 40, W, H * p + 340 * (1 - p)), fill=col if i > 1 else DARK)
        return im


def render(short, lang, color, words, dur, audio, dst, prices=None):
    sc = Short(short, lang, color, words, dur, prices)
    cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(audio), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-t", f"{dur:.3f}", "-movflags", "+faststart", str(dst)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for n in range(int(dur * FPS)):
            p.stdin.write(sc.frame(n / FPS).tobytes())
        p.stdin.close()
    except BrokenPipeError:
        pass
    err = p.stderr.read().decode(errors="ignore")
    if p.wait() != 0:
        raise RuntimeError("ffmpeg: " + err[-300:])
    log(f"    short animato: {dur:.0f}s, {int(dur * FPS)} fotogrammi")
