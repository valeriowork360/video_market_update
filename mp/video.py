"""Assemble videos: voice -> timed frames -> one ffmpeg encode per video (exact audio/video sync)."""
import re
import shutil
import subprocess
import wave
from pathlib import Path

from . import draw, news, tts
from .core import CFG, log, slug

FPS = 24
_hist = {}


def prices_for(ticker):
    if not ticker:
        return None
    if ticker not in _hist:
        _hist[ticker] = news.history(ticker)
    return _hist[ticker]


def chunks(words, max_chars, max_words):
    """Group timed words into caption chunks, breaking at punctuation when possible."""
    out, cur = [], []
    for w in words:
        trial = " ".join(x["w"] for x in cur + [w])
        if cur and (len(trial) > max_chars or len(cur) >= max_words):
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?;:]$", w["w"]) and len(cur) >= 2:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [{"t": c[0]["t"], "text": " ".join(x["w"] for x in c)} for c in out]


def _concat_wavs(paths, dst):
    with wave.open(str(dst), "wb") as out:
        for i, p in enumerate(paths):
            with wave.open(str(p), "rb") as w:
                if i == 0:
                    out.setparams(w.getparams())
                out.writeframes(w.readframes(w.getnframes()))


def _encode(frames, audio, dst, tmp):
    """frames: [(image_path, seconds)]"""
    lst = tmp / "frames.txt"
    lines = []
    for p, dur in frames:
        lines += [f"file '{p.as_posix()}'", f"duration {max(dur, 0.04):.3f}"]
    lines.append(f"file '{frames[-1][0].as_posix()}'")
    lst.write_text("\n".join(lines), encoding="utf-8")
    total = sum(max(d, 0.04) for _, d in frames)
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio),
           "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
           "-tune", "stillimage", "-c:a", "aac", "-b:a", "128k", "-t", f"{total:.3f}",
           "-movflags", "+faststart", str(dst)]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr.decode(errors="ignore")[-400:])


def long_video(script, lang, folder, date_label, weekly=False):
    """Returns (mp4_path, seconds)."""
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "_tmp_long"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    segs = script["segments"]
    voiced = []
    for i, s in enumerate(segs):
        wav = tmp / f"seg{i:02d}.wav"
        words = tts.speak(s["narration"], lang, script["mood"], wav)
        voiced.append((wav, words, tts.wav_seconds(wav)))
    total = sum(v[2] for v in voiced)
    frames, elapsed, n = [], 0.0, 0
    for i, (s, (wav, words, dur)) in enumerate(zip(segs, voiced)):
        scene = draw.LongScene(s, i + 1, len(segs), lang, date_label, prices_for(s["ticker"]), weekly)
        nb = len(s["bullets"])
        reveal = [dur * 0.9 * (k + 0.35) / max(nb, 1) for k in range(nb)]
        caps = chunks(words, 46, 8) if CFG.get("captions", True) else []
        times = sorted({0.0, *[round(t, 3) for t in reveal], *[round(c["t"], 3) for c in caps]})
        times = [t for t in times if t < dur - 0.05]
        for j, t in enumerate(times):
            end = times[j + 1] if j + 1 < len(times) else dur
            shown = sum(1 for r in reveal if r <= t + 1e-6)
            cap = next((c["text"] for c in reversed(caps) if c["t"] <= t + 1e-6), "")
            p = tmp / f"f{n:05d}.jpg"
            scene.frame(shown, cap, (elapsed + t) / total).save(p, quality=90)
            frames.append((p, end - t))
            n += 1
        elapsed += dur
    audio = tmp / "audio.wav"
    _concat_wavs([v[0] for v in voiced], audio)
    name = "weekly" if weekly else "daily"
    dst = folder / f"{name}_{lang}_{slug(script['title'], 50)}.mp4"
    _encode(frames, audio, dst, tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    log(f"    video lungo: {total / 60:.1f} min, {n} quadri, {dst.stat().st_size / 1e6:.1f} MB")
    return dst, total


def short_video(short, idx, lang, folder, date_label, mood):
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"_tmp_short{idx}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    wav = tmp / "voice.wav"
    words = tts.speak(short["narration"], lang, mood, wav, faster=True)
    dur = tts.wav_seconds(wav)
    scene = draw.ShortScene(short, lang, date_label, prices_for(short["ticker"]))
    caps = chunks(words, 18, 3)
    times = sorted({0.0, *[round(c["t"], 3) for c in caps]})
    times = [t for t in times if t < dur - 0.05]
    frames = []
    for j, t in enumerate(times):
        end = times[j + 1] if j + 1 < len(times) else dur
        cap = next((c["text"] for c in reversed(caps) if c["t"] <= t + 1e-6), "")
        p = tmp / f"f{j:05d}.jpg"
        scene.frame(cap, t / dur).save(p, quality=90)
        frames.append((p, end - t))
    dst = folder / f"short_{idx:02d}_{lang}_{slug(short['title'] or short['hook'], 40)}.mp4"
    _encode(frames, wav, dst, tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    return dst, dur
