"""Health check: tests every piece once and sends the report to Telegram.

Run from GitHub: Actions > "0 - Controllo" > Run workflow.
"""
import os
import shutil
import tempfile
import time
import traceback
from pathlib import Path

os.environ.setdefault("MP_ROLE", "doctor")

from . import llm, news, quota, telegram, tts, youtube   # noqa: E402
from .core import CFG, log, secret   # noqa: E402

rows = []


def check(name, fn):
    t = time.time()
    try:
        detail = fn()
        rows.append(("✅", name, detail))
    except Exception as e:
        traceback.print_exc()
        rows.append(("❌", name, str(e)[:200]))
    log(f"{rows[-1][0]} {name}: {rows[-1][2]}  ({time.time() - t:.0f}s)")


def main():
    state = {}

    def gemini_models():
        p = llm.pools()
        return f"scrittura {p['flash'][:3]}, video {p['lite'][:2]}"

    def gemini_text():
        d, m = llm.ask("light", lambda n: 'Return the JSON object {"ok": true, "word": "ciao"}', patience=0)
        return f"{m['model']} risponde: {d}"

    def gemini_writer():
        d, m = llm.ask("write", lambda n: 'Return the JSON object {"ok": true}', patience=0)
        return f"{m['model']} risponde"

    def backups():
        b = [x["name"] for x in llm.backups()]
        if not b:
            return "nessuna chiave di riserva (facoltativa): MISTRAL_API_KEY o GROQ_API_KEY"
        out = []
        for x in llm.backups():
            d, m = llm._backup_once(x, 'Return the JSON object {"ok": true}', 0.2)
            out.append(f"{x['name']} ({m['model']}) ok")
        return ", ".join(out)

    def feeds():
        tot, empty, srcs = 0, [], set()
        for ch in CFG["channels"]:
            v, src = youtube.feed(ch)
            tot += len(v)
            srcs.add(src)
            if not v:
                empty.append(ch["name"])
            elif "sample" not in state:
                ok = [x for x in v if x["live"] not in ("live", "upcoming") and (x["duration"] or 0) > 120]
                if ok:
                    state["sample"] = (ch, ok[0])
        if empty:
            raise RuntimeError(f"nessun video letto per: {empty}")
        return f"{len(CFG['channels'])} canali, {tot} video visti (fonti: {', '.join(sorted(srcs))})"

    def video_clip():
        from . import watch
        ch, v = state["sample"]
        v = dict(v)
        (d, m), fps_ok = watch._call(v, ch, 0, 90, "\nYou are given only the first 90 seconds.\n")
        return (f"{m['model']} ha guardato 90s di \"{v['title'][:40]}\": tono {d.get('author_tone')}, "
                f"fps ridotto {'accettato' if fps_ok else 'NON accettato'}, "
                f"token {m['prompt_tokens']} (audio {m['audio_tokens']})")

    def headlines():
        n = news.fetch_feeds()
        return f"{n} titoli nuovi"

    def prices():
        s = news.snapshot()
        if not s:
            raise RuntimeError("Yahoo Finance non risponde: i video usciranno senza grafici e senza prezzi")
        return f"{len(s)} prezzi, es. {s[0]['name']} {s[0]['last']} ({s[0]['change_1d_pct']:+.2f}%)"

    def cal():
        return f"{len(news.calendar_events())} eventi in arrivo"

    def voice():
        tmp = Path(tempfile.mkdtemp())
        out = []
        for lang, text in (("it", "Prova della voce narrante in italiano."), ("en", "Narrator voice test in English.")):
            w = tts.speak(text, lang, "neutral", tmp / f"{lang}.wav")
            out.append(f"{lang} {tts.wav_seconds(tmp / f'{lang}.wav'):.1f}s/{len(w)} parole")
        shutil.rmtree(tmp, ignore_errors=True)
        return ", ".join(out)

    def ffmpeg():
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg mancante")
        return "presente"

    check("Chiave Gemini e modelli", gemini_models)
    check("Gemini (testo, modello leggero)", gemini_text)
    check("Gemini (scrittura copioni)", gemini_writer)
    check("AI di riserva", backups)
    check("Feed YouTube dei canali", feeds)
    if "sample" in state:
        check("Gemini guarda un video", video_clip)
    check("Notizie RSS", headlines)
    check("Prezzi Yahoo Finance", prices)
    check("Calendario economico", cal)
    check("Voce narrante", voice)
    check("ffmpeg", ffmpeg)

    q = quota.summary()
    bad = sum(1 for r in rows if r[0] == "❌")
    text = ["🩺 <b>Controllo Market Pulse</b>", ""]
    text += [f"{r[0]} <b>{telegram.esc(r[1])}</b>: {telegram.esc(r[2])}" for r in rows]
    text += ["", f"Richieste AI usate oggi: {telegram.esc(q['requests'])}",
             "Tutto a posto." if not bad else f"{bad} controlli da sistemare."]
    if not secret("TELEGRAM_BOT_TOKEN"):
        log("TELEGRAM_BOT_TOKEN mancante")
    telegram.message("\n".join(text), html_mode=True)
    return 1 if any(r[0] == "❌" and r[1] in ("Chiave Gemini e modelli", "Voce narrante", "ffmpeg") for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
