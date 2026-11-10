"""Rendering: voice (edge-tts), charts (yfinance), slides (Pillow), video (ffmpeg)."""
import asyncio
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common import CFG, ROOT

B = CFG["brand"]
FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", str(ROOT / "assets" / "fonts")]
TONE_PROSODY = {"news": ("+4%", "-2Hz"), "energetic": ("+14%", "+3Hz"), "calm": ("-6%", "-4Hz")}
FPS = 25


def font(size, bold=True):
    names = ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for d in FONT_DIRS:
        for n in names:
            p = Path(d) / n
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def sent_color(s):
    return hexrgb(B["bullish"] if s == "bullish" else B["bearish"] if s == "bearish" else B["accent"])


def wrap(draw, text, fnt, max_w):
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=fnt) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_block(draw, xy, text, fnt, max_w, fill, spacing=1.25, max_lines=None):
    x, y = xy
    lines = wrap(draw, text, fnt, max_w)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,") + "…"
    h = fnt.size * spacing
    for ln in lines:
        draw.text((x, y), ln, font=fnt, fill=fill)
        y += h
    return y


# ---------------------------------------------------------------- voice
def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                        "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


async def _tts(text, voice, out, rate, pitch):
    import edge_tts
    words = []
    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary") \
        if "boundary" in edge_tts.Communicate.__init__.__code__.co_varnames \
        else edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    with open(out, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]))
    return words


def tts(text, lang, out):
    """Returns list of (start, end, word). Falls back to silence if TTS is unreachable."""
    rate, pitch = TONE_PROSODY.get(CFG["narrator_tone"], TONE_PROSODY["news"])
    try:
        return asyncio.run(_tts(text, CFG["voices"][lang], str(out), rate, pitch))
    except Exception as e:
        if os.environ.get("ALLOW_SILENT_TTS") != "1":
            raise
        print(f"  TTS non disponibile ({e}); uso audio muto (solo test)")
        secs = max(3, len(text.split()) / 2.6)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{secs:.2f}",
             "-q:a", "9", str(out)])
        return []


def even_words(text, total):
    ws = text.split()
    step = total / max(1, len(ws))
    return [(i * step, (i + 1) * step, w) for i, w in enumerate(ws)]


def ass_captions(words, path, w, h, size, margin_v, per=4):
    def t(s):
        hh, rem = divmod(s, 3600)
        mm, ss = divmod(rem, 60)
        return f"{int(hh)}:{int(mm):02d}:{ss:05.2f}"
    acc = B["accent"].lstrip("#")
    acc_bgr = acc[4:6] + acc[2:4] + acc[0:2]
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,DejaVu Sans,{size},&H00FFFFFF,&H00{acc_bgr},&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{max(3, size // 14)},0,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for i in range(0, len(words), per):
        chunk = words[i:i + per]
        end = words[i + per][0] if i + per < len(words) else chunk[-1][1] + 0.3
        txt = " ".join(c[2] for c in chunk).replace("{", "").replace("}", "")
        lines.append(f"Dialogue: 0,{t(chunk[0][0])},{t(end)},Cap,,0,0,0,,{txt.upper()}")
    Path(path).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- charts
_chart_cache = {}


def chart(ticker, out, w, h):
    """3-month price chart. Returns path or None."""
    if not ticker or ticker == "null":
        return None
    key = (ticker, w, h)
    if key in _chart_cache:
        return _chart_cache[key]
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import yfinance as yf
        df = yf.download(ticker, period="3mo", interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        close = df["Close"].squeeze()
        up = close.iloc[-1] >= close.iloc[0]
        col = B["bullish"] if up else B["bearish"]
        chg = (close.iloc[-1] / close.iloc[0] - 1) * 100
        fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
        fig.patch.set_alpha(0)
        ax = fig.add_axes([0.06, 0.12, 0.9, 0.72])
        ax.set_facecolor((0, 0, 0, 0))
        ax.plot(close.index, close.values, color=col, lw=4)
        ax.fill_between(close.index, close.values, close.min(), color=col, alpha=0.15)
        for s in ax.spines.values():
            s.set_visible(False)
        import matplotlib.dates as mdates
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        ax.tick_params(colors="#9AA4AF", labelsize=h // 30)
        ax.grid(axis="y", color="#2A323C", lw=1)
        fig.text(0.06, 0.9, f"{ticker}  {close.iloc[-1]:,.2f}   {chg:+.1f}% (3M)", color=col,
                 fontsize=h // 18, weight="bold")
        fig.savefig(out, transparent=True)
        plt.close(fig)
        _chart_cache[key] = str(out)
        return str(out)
    except Exception as e:
        print(f"  grafico {ticker} non disponibile: {e}")
        return None


# ---------------------------------------------------------------- slides
def base(w, h):
    img = Image.new("RGB", (w, h), hexrgb(B["background"]))
    d = ImageDraw.Draw(img)
    for i in range(h):  # subtle vertical gradient
        a = int(18 * i / h)
        d.line([(0, i), (w, i)], fill=tuple(min(255, c + a) for c in hexrgb(B["background"])))
    return img, d


def brand_bar(d, w, h, label, scale=1.0):
    acc = hexrgb(B["accent"])
    d.rectangle([0, 0, w, int(10 * scale)], fill=acc)
    d.text((int(60 * scale), int(36 * scale)), B["name"].upper(), font=font(int(34 * scale)), fill=acc)
    f = font(int(28 * scale), False)
    tw = d.textlength(label, font=f)
    d.text((w - tw - int(60 * scale), int(40 * scale)), label, font=f, fill=hexrgb("#9AA4AF"))


def slide_long(seg, out, tmp, date_label):
    W, H = 1920, 1080
    img, d = base(W, H)
    brand_bar(d, W, H, date_label)
    col = sent_color(seg.get("sentiment"))
    d.rectangle([80, 150, 92, 260], fill=col)
    y = draw_block(d, (120, 140), seg.get("heading", ""), font(78), 1650, hexrgb(B["text"]), max_lines=2)
    ch = chart(seg.get("ticker"), Path(tmp) / f"c_{seg.get('ticker')}_{W}.png", 1000, 620)
    text_w = 700 if ch else 1650
    y += 40
    for b in seg.get("bullets", [])[:5]:
        d.ellipse([122, y + 22, 138, y + 38], fill=col)
        y = draw_block(d, (165, y), b, font(44, False), text_w - 60, hexrgb(B["text"]), max_lines=2) + 22
    if ch:
        c = Image.open(ch).convert("RGBA")
        img.paste(c, (860, 290), c)
    src = seg.get("sources") or []
    if src:
        d.text((120, H - 150), "Fonti: " + ", ".join(src)[:120], font=font(30, False), fill=hexrgb("#9AA4AF"))
    img.save(out)


def slide_short(sh, out, tmp):
    W, H = 1080, 1920
    img, d = base(W, H)
    brand_bar(d, W, H, "", 1.3)
    col = sent_color(sh.get("sentiment"))
    d.rounded_rectangle([60, 200, W - 60, 560], radius=36, fill=tuple(int(c * 0.25) for c in col))
    draw_block(d, (100, 240), sh.get("hook", ""), font(72), W - 200, hexrgb(B["text"]), max_lines=4)
    ch = chart(sh.get("ticker"), Path(tmp) / f"c_{sh.get('ticker')}_{W}.png", 960, 640)
    if ch:
        c = Image.open(ch).convert("RGBA")
        img.paste(c, (60, 640), c)
    img.save(out)


def carousel(car, folder, lang):
    W, H = 1080, 1350
    folder.mkdir(parents=True, exist_ok=True)
    slides = car.get("slides", [])
    paths = []
    for i, s in enumerate(slides, 1):
        img, d = base(W, H)
        brand_bar(d, W, H, f"{i}/{len(slides)}")
        acc = hexrgb(B["accent"])
        if i == 1:
            ft, fb = font(100), font(48, False)
        else:
            ft, fb = font(74), font(56, False)
        nt = min(5, len(wrap(d, s.get("title", ""), ft, W - 210)))
        nb = min(10, len(wrap(d, s.get("body", ""), fb, W - 160)))
        block = nt * ft.size * 1.25 + 60 + nb * fb.size * 1.4
        y0 = max(160, int((H - block) / 2) - 40)  # vertically centred
        d.rectangle([80, y0 + 10, 96, y0 + 10 + int(ft.size * 1.25 * nt) - 20], fill=acc)
        y = draw_block(d, (130, y0), s.get("title", ""), ft, W - 210, hexrgb(B["text"]), max_lines=5)
        draw_block(d, (80, y + 60), s.get("body", ""), fb, W - 160,
                   acc if i == 1 else hexrgb("#D5DBE1"), spacing=1.4, max_lines=10)
        if i == 1:
            d.text((80, H - 130), "Scorri →" if lang == "it" else "Swipe →", font=font(44), fill=acc)
        if i == len(slides):
            d.text((80, H - 130), "Non è consulenza finanziaria" if lang == "it" else "Not financial advice",
                   font=font(28, False), fill=hexrgb("#9AA4AF"))
        p = folder / f"slide_{i:02d}.png"
        img.save(p)
        paths.append(p)
    return paths


# ---------------------------------------------------------------- video
def clip(image, audio, words, out, w, h, cap_size, cap_margin, zoom=True):
    dur = duration(audio)
    words = words or even_words("", 0)
    ass = Path(out).with_suffix(".ass")
    ass_captions(words, ass, w, h, cap_size, cap_margin)
    frames = int(dur * FPS) + FPS
    vf = (f"scale={int(w * 1.1)}:-2,zoompan=z='min(zoom+0.0004,1.08)':d={frames}:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={FPS}," if zoom else f"scale={w}:{h},")
    vf += f"subtitles='{ass}',format=yuv420p"
    run(["ffmpeg", "-y", "-loop", "1", "-i", str(image), "-i", str(audio), "-vf", vf,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-t", f"{dur + 0.4:.2f}",
         "-shortest", str(out)])
    return out


def concat(parts, out):
    lst = Path(out).with_suffix(".txt")
    lst.write_text("".join(f"file '{Path(p).resolve()}'\n" for p in parts))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
         "-movflags", "+faststart", str(out)])
    lst.unlink()


def narrate(text, lang, base_path):
    audio = Path(str(base_path) + ".mp3")
    words = tts(text, lang, audio)
    if not words:
        words = even_words(text, duration(audio))
    return audio, words


def long_video(pkg, lang, folder, date_label):
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "_tmp"
    tmp.mkdir(exist_ok=True)
    parts = []
    for i, seg in enumerate(pkg["segments"]):
        print(f"    segmento {i + 1}/{len(pkg['segments'])}: {seg.get('heading')}")
        img = tmp / f"seg{i:02d}.png"
        slide_long(seg, img, tmp, date_label)
        audio, words = narrate(seg["narration"], lang, tmp / f"seg{i:02d}")
        parts.append(clip(img, audio, words, tmp / f"seg{i:02d}.mp4", 1920, 1080, 46, 50))
    out = folder / f"long_{lang}.mp4"
    concat(parts, out)
    return out


def shorts(pkg, lang, folder):
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "_tmp"
    tmp.mkdir(exist_ok=True)
    outs = []
    for i, sh in enumerate(pkg.get("shorts", []), 1):
        print(f"    short {i}: {sh.get('hook')}")
        img = tmp / f"short{i:02d}.png"
        slide_short(sh, img, tmp)
        text = f"{sh.get('hook', '')}. {sh['narration']}"
        audio, words = narrate(text, lang, tmp / f"short{i:02d}")
        out = folder / f"short_{lang}_{i:02d}.mp4"
        clip(img, audio, words, out, 1080, 1920, 84, 330, zoom=False)
        (folder / f"short_{lang}_{i:02d}.txt").write_text(
            sh.get("caption", "") + "\n\n" + " ".join(sh.get("hashtags", [])), encoding="utf-8")
        outs.append(out)
    return outs
