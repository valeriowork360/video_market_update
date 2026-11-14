"""Voice. Edge TTS (free, no key) with word timings for synced captions.

If Edge is down we fall back to Google Translate TTS (gTTS) with estimated timings,
so a voice outage never blocks the day's video.
"""
import asyncio
import os
import subprocess
import time
import wave
from pathlib import Path

from .core import CFG, log

RATE = 44100
PROSODY = {            # narrator mood -> (rate, pitch)
    "calm": (-3, "-2Hz"),
    "neutral": (3, "+0Hz"),
    "urgent": (9, "+1Hz"),
    "upbeat": (7, "+2Hz"),
}


def _run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _to_wav(src, dst, pad=0.45):
    _run(["ffmpeg", "-y", "-i", str(src), "-ar", str(RATE), "-ac", "2",
          "-af", f"apad=pad_dur={pad}", "-c:a", "pcm_s16le", str(dst)])


def wav_seconds(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


async def _edge(text, voice, rate, pitch, mp3):
    import edge_tts
    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    words = []
    with open(mp3, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append({"t": ch["offset"] / 1e7, "d": ch["duration"] / 1e7, "w": ch["text"]})
    return words


def _estimate(text, seconds):
    """Spread words over the audio in proportion to their length."""
    ws = text.split()
    total = sum(len(w) + 1 for w in ws) or 1
    out, t = [], 0.0
    for w in ws:
        d = seconds * (len(w) + 1) / total
        out.append({"t": t, "d": d, "w": w})
        t += d
    return out


def _fake(text, wav):
    secs = max(1.5, len(text.split()) * 0.36)
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"\x00" * int(secs * RATE) * 4)
    return _estimate(text, secs - 0.4)


def speak(text, lang, mood, wav, faster=False):
    """Write `wav` (44.1 kHz stereo) and return word timings [{t, d, w}]."""
    wav = Path(wav)
    wav.parent.mkdir(parents=True, exist_ok=True)
    if os.environ.get("MP_FAKE_TTS"):
        return _fake(text, wav)
    mode = CFG["narrator"].get("mode", "auto")
    pct, pitch = PROSODY.get(mood if mode == "auto" else mode, PROSODY["neutral"])
    rate = f"{pct + (5 if faster else 0):+d}%"
    mp3 = wav.with_suffix(".mp3")
    last = None
    for voice in CFG["narrator"]["voices"][lang]:
        for attempt in range(2):
            try:
                words = asyncio.run(_edge(text, voice, rate, pitch, mp3))
                if mp3.stat().st_size < 2000:
                    raise RuntimeError("audio vuoto")
                _to_wav(mp3, wav)
                if not words:
                    words = _estimate(text, wav_seconds(wav) - 0.45)
                return words
            except Exception as e:
                last = e
                time.sleep(3)
        log(f"    voce {voice} non disponibile ({str(last)[:80]}), provo la successiva")
    try:
        from gtts import gTTS
        gTTS(text, lang=lang).save(str(mp3))
        _to_wav(mp3, wav)
        log("    voce di riserva (gTTS) usata")
        return _estimate(text, wav_seconds(wav) - 0.45)
    except Exception as e:
        raise RuntimeError(f"sintesi vocale non riuscita: edge={str(last)[:80]} gtts={str(e)[:80]}")
