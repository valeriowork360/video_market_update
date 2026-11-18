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

from . import llm, news, publish, quota, telegram, tts, youtube   # noqa: E402
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
            out.append(f"{x['name']} ({m['model']}) ok: {str(d)[:30]}")
        return ", ".join(out)

    def cursor_key():
        import requests
        k = secret("CURSOR_API_KEY")
        if not k:
            return "non presente"
        tries = {"xAI (Grok)": "https://api.x.ai/v1/models", "OpenRouter": "https://openrouter.ai/api/v1/models",
                 "Groq": "https://api.groq.com/openai/v1/models", "OpenAI": "https://api.openai.com/v1/models"}
        for name, url in tries.items():
            try:
                r = requests.get(url, headers={"Authorization": f"Bearer {k}"}, timeout=20)
                if r.ok and name != "OpenRouter":
                    return f"e' una chiave {name}: va rinominata (per xAI: XAI_API_KEY)"
            except Exception:
                pass
        try:
            r = requests.get("https://api.cursor.com/v0/me", headers={"Authorization": f"Bearer {k}"}, timeout=20)
            if r.status_code < 300:
                return "e' una chiave di Cursor: serve solo per Cursor, non puo' scrivere i nostri testi"
        except Exception:
            pass
        raise RuntimeError("non e' riconosciuta da xAI, Groq, OpenAI ne' Cursor")

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

    def instagram(lang):
        def run():
            if not publish.ig_token(lang):
                return f"non configurato (manca il segreto IG_TOKEN_{lang.upper()})"
            user, kind = publish.ig_me(lang)
            if kind and kind.upper() not in ("BUSINESS", "MEDIA_CREATOR", "CREATOR"):
                raise RuntimeError(f"@{user} non e' un account professionale ({kind}): convertilo dalle impostazioni di Instagram")
            return f"@{user} collegato: Reel e caroselli partono da soli"
        return run

    def yt(lang):
        def run():
            if not publish.yt_ready(lang):
                return f"non configurato (YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN_{lang.upper()})"
            name = publish.yt_whoami(lang)
            mode = publish.yt_mode()
            note = {"off": "caricamento spento finche' Google non approva il progetto",
                    "private": "carica in privato (solo prove)", "public": "pubblica in automatico"}[mode]
            return f"canale \"{name}\" collegato; {note}"
        return run

    if os.environ.get("MP_CHECK", "").startswith("voc"):
        return voices()
    only_publish = os.environ.get("MP_CHECK", "").startswith("pub")
    for lang in CFG["languages"]:
        check(f"Instagram {lang.upper()}", instagram(lang))
        check(f"YouTube {lang.upper()}", yt(lang))
    if only_publish:
        return finish()

    check("Chiave Gemini e modelli", gemini_models)
    check("Gemini (testo, modello leggero)", gemini_text)
    check("Gemini (scrittura copioni)", gemini_writer)
    check("AI di riserva", backups)
    check("Chiave CURSOR_API_KEY", cursor_key)
    check("Feed YouTube dei canali", feeds)
    if "sample" in state:
        check("Gemini guarda un video", video_clip)
    check("Notizie RSS", headlines)
    check("Prezzi Yahoo Finance", prices)
    check("Calendario economico", cal)
    check("Voce narrante", voice)
    check("ffmpeg", ffmpeg)

    return finish()


SAMPLE = {
    "it": "Bitcoin scende sotto i 70.000 dollari ed Ethereum perde il 6%. A Wall Street l'S&P 500 e il Nasdaq "
          "chiudono in calo dello 0,4%: Nvidia, Tesla e Apple restano sotto pressione dopo le parole della "
          "Federal Reserve. Secondo molti analisti il rimbalzo va ancora confermato dai volumi.",
    "en": "Bitcoin slips below $70,000 and Ethereum loses 6%. On Wall Street the S&P 500 and the Nasdaq close "
          "down 0.4%: Nvidia, Tesla and Apple stay under pressure after the Federal Reserve's remarks.",
}


def voices():
    """Send the same sentence read by every candidate voice, so the choice is made by ear."""
    import asyncio

    import edge_tts

    from . import speech
    only_current = "attuale" in os.environ.get("MP_CHECK", "")
    tmp = Path(tempfile.mkdtemp())
    listed = asyncio.run(edge_tts.list_voices())
    names = [v["ShortName"] for v in listed]
    sent = 0
    for lang, local in (("it", "it-IT-"), ("en", "en-US-")):
        current = CFG["narrator"]["voices"][lang][0]
        multi = [n for n in names if "Multilingual" in n and not n.startswith(local)]
        if lang == "en":
            pool = [n for n in names if n.startswith(local) and "Multilingual" in n][:3] + [current]
        else:
            prefer = ["en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural",
                      "en-US-AvaMultilingualNeural", "fr-FR-RemyMultilingualNeural"]
            pool = [n for n in names if n.startswith(local)] + [n for n in prefer if n in multi]
        pool = list(dict.fromkeys([current] + pool))[:8]
        if only_current:
            pool = [current]
        if only_current:
            telegram.message(f"🎙 Voce in uso ({lang.upper()}): {current}, velocita' {tts.SPEED}x")
        else:
            telegram.message(f"🎙 Voci a confronto ({lang.upper()}). Stessa frase letta da {len(pool)} voci: "
                             f"dimmi il numero di quella che preferisci. In uso adesso: {current}")
        said = speech.speakable(SAMPLE[lang], lang)
        for i, v in enumerate(pool, 1):
            try:
                wav = tmp / f"{lang}_{i}.wav"
                tts.speak(said, lang, "neutral", wav, voice=v)
                label = f"{lang.upper()} {i} - {v.split('-', 2)[2].replace('Neural', '')}"
                telegram.audio(wav.with_suffix(".mp3"), label, f"Voce {i}: {v}" + (" (in uso)" if v == current else ""))
                log(f"✅ {label}")
                sent += 1
            except Exception as e:
                log(f"❌ voce {v}: {str(e)[:120]}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if sent else 1


def finish():
    q = quota.summary()
    bad = sum(1 for r in rows if r[0] == "❌")
    text = ["🩺 <b>Controllo Market Pulse</b>", ""]
    text += [f"{r[0]} <b>{telegram.esc(r[1])}</b>: {telegram.esc(r[2])}" for r in rows]
    text += ["", f"Richieste AI usate oggi: {telegram.esc(q['requests'])}",
             "Tutto a posto." if not bad else f"{bad} controlli da sistemare."]
    telegram.message("\n".join(text), html_mode=True)
    return 1 if any(r[0] == "❌" and r[1] in ("Chiave Gemini e modelli", "Voce narrante", "ffmpeg") for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
