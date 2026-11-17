"""Daily and weekly production: scripts -> voice -> videos, shorts, carousels -> Telegram.

Every step is saved. If something fails, the next (automatic) run resumes from where it
stopped instead of starting over, and what is ready is delivered straight away.

  python -m mp.produce daily
  python -m mp.produce weekly
  python -m mp.produce daily --force          (redo even if already delivered)
  python -m mp.produce daily --offline        (test with tests/sample_*.json, no AI)
"""
import argparse
import os
import sys
import traceback
from datetime import datetime, timedelta

os.environ.setdefault("MP_ROLE", "produce")

from . import draw, llm, news, publish, quota, telegram, video, writer   # noqa: E402
from .core import (CFG, NOTES, OUT, ROOT, SCRIPTS, STATE, clock, local_day, log, now, parse_iso,   # noqa: E402
                   read_json, write_json)

FLAG = {"it": "🇮🇹", "en": "🇬🇧"}
MOOD_IT = {"calm": "pacato", "neutral": "da telegiornale", "urgent": "serio e incalzante", "upbeat": "energico"}
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def date_label(day, lang, weekly):
    d = datetime.strptime(day, "%Y-%m-%d")
    if lang == "it":
        s = d.strftime("%d/%m/%Y")
        return s
    return f"{MONTHS_EN[d.month - 1]} {d.day}, {d.year}"


def load_notes(hours, exclude=()):
    cut = now() - timedelta(hours=hours)
    out = []
    if not NOTES.exists():
        return out
    for folder in sorted(NOTES.iterdir()):
        for f in sorted(folder.glob("*.json")):
            n = read_json(f)
            if not n or n["video_id"] in exclude:
                continue
            when = parse_iso(n.get("published")) or parse_iso(n.get("analysed_at")) or now()
            if when >= cut:
                out.append(n)
    return out


def used_notes(produced, key):
    ids = set()
    for k, rec in produced.items():
        if k.endswith("_daily") and k != key:
            ids.update(rec.get("notes", []))
    return ids


def youtube_text(script):
    return (f"{script['title']}\n\n{script['description']}\n\n"
            f"Tags: {', '.join(script['tags'])}\n")


def deliver_long(lang, kind, day, script, mp4, secs, thumb, n_notes, n_news):
    kind_it = "RECAP SETTIMANALE" if kind == "weekly" else "GIORNALIERO"
    if os.environ.get("MP_PREVIEW"):
        kind_it = "ANTEPRIMA DI PROVA · " + kind_it
    telegram.message(
        f"{FLAG[lang]} <b>{kind_it} · {date_label(day, 'it', False)}</b>\n"
        f"🎬 {telegram.esc(script['title'])}\n"
        f"🎙 Tono della voce: {MOOD_IT[script['mood']]} · {secs / 60:.1f} min · "
        f"{len(script['segments'])} segmenti\n"
        f"📚 Basato su {n_notes} video degli autori e {n_news} notizie", html_mode=True)
    ok = telegram.video(mp4, script["title"], 1920, 1080, secs)
    telegram.photo(thumb, "Miniatura per YouTube")
    telegram.message(
        "<b>Titolo</b>\n<code>" + telegram.esc(script["title"]) + "</code>\n\n"
        "<b>Descrizione</b>\n<code>" + telegram.esc(script["description"]) + "</code>\n\n"
        "<b>Tag</b>\n<code>" + telegram.esc(", ".join(script["tags"])) + "</code>", html_mode=True)
    return ok


def make_long(lang, kind, day, ctx, folder, sdir, force):
    path = sdir / f"{lang}.json"
    script = None if force else read_json(path)
    if script:
        log("  copione gia' scritto: lo riuso")
    else:
        notes = [n for n in ctx["notes"] if lang == "it" or n["scope"] != "italy"]
        heads = news.recent(ctx["hours"], lang)
        log(f"  scrivo il copione ({len(notes)} note, {len(heads)} notizie)")
        covered = []            # what the last episodes already told, so stories are not repeated
        for d in sorted(p for p in SCRIPTS.glob("*_daily") if p.name[:10] < day)[-5:]:
            old = read_json(d / f"{lang}.json") or {}
            if old:
                covered.append({"day": d.name[:10], "title": old.get("title"),
                                "topics": [x["heading"] + ": " + " ".join(x["bullets"][:3])
                                           for x in old.get("segments", []) if x["kind"] in ("topic", "market", "curious")]})
        script, meta = writer.long_script(notes, heads, ctx["market"], ctx["calendar"], lang, kind,
                                          date_label(day, lang, kind == "weekly"), ctx.get("week"), covered)
        script["model"] = meta["model"]
        script["n_notes"], script["n_news"] = len(notes), len(heads)
        write_json(path, script)
        log(f"  copione: {script['words']} parole, tono {script['mood']} ({meta['model']})")
    label = date_label(day, lang, kind == "weekly")
    mp4, secs = video.long_video(script, lang, folder, label, weekly=kind == "weekly")
    first = next((s["ticker"] for s in script["segments"] if s["ticker"]), None)
    thumb = draw.thumbnail(script, lang, label, folder / f"thumbnail_{lang}.jpg",
                           video.prices_for(first) or video.prices_for("^GSPC"))
    (folder / f"youtube_{lang}.txt").write_text(youtube_text(script), encoding="utf-8")
    deliver_long(lang, kind, day, script, mp4, secs, thumb, script.get("n_notes", 0), script.get("n_news", 0))
    publish.long_video(f"{day}_{kind}", lang, script, mp4, thumb)
    return script


def video_shorts_for(lang, ctx, sdir, langs):
    """All the shorts of the day for one language: several per creator video.

    One AI call per video writes every language at once and is saved, so the second
    language (and any retry) costs nothing. Returns ([(id, short)], [problems]).
    """
    out, problems = [], []
    cap = CFG["daily"].get("max_shorts_total", 40)
    for note in ctx["notes"]:
        if lang != "it" and note.get("scope") == "italy":
            continue
        path = sdir / f"shorts_{note['video_id']}.json"
        data = read_json(path)
        if data is None:
            want = [l for l in langs if l == "it" or note.get("scope") != "italy"]
            try:
                data, meta = writer.video_shorts(note, want)
                write_json(path, data)
                log(f"  {note['author']}: " + ", ".join(f"{len(v)} short {k}" for k, v in data.items())
                    + f" da \"{note['title'][:50]}\" ({meta['model']})")
            except llm.KeyProblem:
                raise
            except Exception as e:
                problems.append(f"short di {note['author']}: {str(e)[:120]}")
                log(f"  short non scritti per \"{note['title'][:50]}\": {str(e)[:140]}")
                continue
        for i, sh in enumerate(data.get(lang, []), 1):
            out.append((f"{note['video_id']}:{i}", sh))
    return out[:cap], problems


def make_social(lang, kind, day, script, folder, sdir, force, ctx, st, langs):
    path = sdir / f"{lang}_social.json"
    soc = None if force else read_json(path)
    if not soc:
        log("  scrivo i caroselli")
        soc, meta = writer.derivatives(script, lang, kind)
        write_json(path, soc)
        log(f"  {len(soc['carousels'])} caroselli scritti ({meta['model']})")
    label = date_label(day, lang, False)
    sent = st.setdefault("sent", [])          # what already reached Telegram: never sent twice
    shorts, problems = ([], []) if kind == "weekly" else video_shorts_for(lang, ctx, sdir, langs)
    writer.upgrade({"shorts": [s for _, s in shorts]})
    for n, (sid, s) in enumerate(shorts, 1):
        if f"s:{sid}" in sent and not force:
            continue
        try:
            mp4, secs = video.short_video(s, n, lang, folder / "shorts", label, script["mood"])
            cap = f"{s['title']}\n\n{s['caption']}\n\n{' '.join(s['hashtags'])}"
            (mp4.with_suffix(".txt")).write_text(cap, encoding="utf-8")
            telegram.video(mp4, f"📱 Short {n}/{len(shorts)} · {s.get('origin')} · dal video: "
                                f"{s.get('source_video', '')}\n\n{cap}", 1080, 1920, secs)
            sent.append(f"s:{sid}")
            publish.short(f"{day}_{kind}", lang, n, s, mp4)
        except Exception as e:
            problems.append(f"short {n}: {str(e)[:100]}")
            log(f"    short {n} saltato: {str(e)[:160]}")
    for i, c in enumerate(soc["carousels"], 1):
        if f"c:{i}" in sent and not force:
            continue
        try:
            cf = folder / "carousels" / f"{i:02d}"
            paths = draw.carousel(c, lang, cf, label, video.prices_for(c.get("ticker")))
            cap = f"{c['caption']}\n\n{' '.join(c['hashtags'])}"
            (cf / "caption.txt").write_text(cap, encoding="utf-8")
            telegram.album(paths, f"🖼 Carosello {i}/{len(soc['carousels'])}: {c['topic']}")
            telegram.message("<code>" + telegram.esc(cap) + "</code>", html_mode=True)
            sent.append(f"c:{i}")
            publish.carousel(f"{day}_{kind}", lang, i, c, paths)
        except Exception as e:
            log(f"    carosello {i} saltato: {str(e)[:160]}")
    n_s = sum(1 for x in sent if x.startswith("s:"))
    n_c = sum(1 for x in sent if x.startswith("c:"))
    log(f"  consegnati finora {n_s} short e {n_c} caroselli")
    online = publish.report(f"{day}_{kind}", lang)
    if online:
        telegram.message(online)
    if problems:            # what is missing is retried at the next run; nothing is sent twice
        raise RuntimeError("; ".join(problems[:3]))
    return n_s, n_c


def offline_ctx(kind):
    return {"notes": [{"video_id": "sample", "author": "MindTheChart", "title": "Video di prova",
                       "scope": "global"}], "market": [], "calendar": [], "hours": 30}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["daily", "weekly"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--lang")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--day", help="YYYY-MM-DD: the day this episode belongs to (default: today)")
    a = ap.parse_args()
    kind, day = a.kind, a.day or local_day()
    key = f"{day}_{kind}"
    if a.offline:
        os.environ["MP_OFFLINE"] = "1"
    # trial runs record nothing, so the scheduled edition is untouched:
    #   MP_SILENT  = nothing is sent          MP_PREVIEW = sent to Telegram, marked as a preview
    silent = bool(os.environ.get("MP_SILENT") or os.environ.get("MP_PREVIEW"))
    ledger = OUT / "produced_trial.json" if (a.offline or silent) else STATE / "produced.json"
    produced = {} if (a.offline or silent) else read_json(ledger, {})
    rec = produced.setdefault(key, {"langs": {}, "notes": []})
    langs = [a.lang] if a.lang else CFG["languages"]
    todo = [l for l in langs if a.force or not (rec["langs"].get(l, {}).get("long") and rec["langs"].get(l, {}).get("social"))]
    if not todo:
        log(f"{key}: gia' consegnato, niente da fare")
        return 0
    tries = 0
    if not (a.offline or silent):
        c = clock()
        tries = c.get("produce_tries", {}).get(key, 0) + 1
        clock(last_produce_try=now().isoformat(), produce_tries={key: tries})
    folder, sdir = OUT / key, SCRIPTS / key
    if a.offline or silent:
        sdir = OUT / key / "_scripts"
    if a.offline:
        for l in todo:
            write_json(sdir / f"{l}.json", read_json(ROOT / "tests" / f"sample_{l}.json"))
            write_json(sdir / f"{l}_social.json", read_json(ROOT / "tests" / f"sample_{l}_social.json"))
        write_json(sdir / "shorts_sample.json",
                   {l: read_json(ROOT / "tests" / f"sample_{l}_social.json")["shorts"] for l in CFG["languages"]})
        ctx = offline_ctx(kind)
    else:
        weekly = kind == "weekly"
        hours = 24 * 7 if weekly else 48
        notes = load_notes(hours, () if weekly else used_notes(produced, key))
        notes = [n for n in notes if n.get("market_relevance", 5) >= 3]
        if weekly:
            notes = sorted(notes, key=lambda n: -n["market_relevance"])[:30]
        log("== Contesto di mercato ==")
        ctx = {"notes": notes, "hours": 24 * 7 if weekly else 30,
               "market": news.snapshot(), "calendar": news.calendar_events()}
        if weekly:
            week = []
            for k in sorted(p.name for p in SCRIPTS.glob("*_daily")):
                if k[:10] >= local_day(-7):
                    s = read_json(SCRIPTS / k / "en.json") or read_json(SCRIPTS / k / "it.json")
                    if s:
                        week.append({"day": k[:10], "title": s["title"],
                                     "topics": [x["heading"] for x in s["segments"]]})
            ctx["week"] = week
        heads = news.recent(ctx["hours"], "it")
        log(f"  {len(notes)} note degli autori, {len(heads)} notizie")
        if not notes and not heads:
            telegram.message(f"ℹ️ {kind}: nessun video nuovo e nessuna notizia raccolta, oggi non produco nulla.")
            return 0
        if not rec["notes"]:
            rec["notes"] = [n["video_id"] for n in notes]

    problems = []
    for lang in todo:
        log(f"== {lang.upper()} ==")
        st = rec["langs"].setdefault(lang, {})
        publish.prepare(lang)
        try:
            if a.force or not st.get("long") or not read_json(sdir / f"{lang}.json"):
                script = make_long(lang, kind, day, ctx, folder / lang, sdir, a.force)
                st["long"] = True
                st["title"] = script["title"]
                write_json(ledger, produced)
            else:
                script = read_json(sdir / f"{lang}.json")
            if a.force or not st.get("social"):
                st["shorts"], st["carousels"] = make_social(lang, kind, day, script, folder / lang, sdir, a.force,
                                                            ctx, st, CFG["languages"])
                st["social"] = True
                write_json(ledger, produced)
        except llm.KeyProblem as e:
            problems.append(f"{lang}: {e}")
            break
        except Exception as e:
            traceback.print_exc()
            problems.append(f"{lang}: {str(e)[:220]}")
        write_json(ledger, produced)

    # keep the ledger small
    for k in sorted(produced)[:-40]:
        produced.pop(k)
    write_json(ledger, produced)

    done = [l for l in todo if rec["langs"].get(l, {}).get("long") and rec["langs"].get(l, {}).get("social")]
    q = quota.summary()
    log(f"== Fine: completate {done}, problemi {len(problems)}. Richieste AI oggi: {q['requests']} ==")
    if problems and tries not in (0, 1, 4, 8):
        log("   (avviso Telegram gia' mandato a un tentativo precedente)")
        return 1
    if problems:
        telegram.message("⚠️ Produzione " + ("settimanale" if kind == "weekly" else "giornaliera")
                         + " incompleta:\n- " + "\n- ".join(problems)
                         + "\n\nQuello che e' pronto ti e' gia' arrivato. Il resto viene ritentato "
                           "in automatico piu' tardi, ripartendo da dove si e' fermato.\n" + telegram.run_link())
        return 1
    link = telegram.run_link()
    telegram.message(f"✅ {'Recap settimanale' if kind == 'weekly' else 'Giornaliero'} completo "
                     f"({', '.join(x.upper() for x in done)}). Tutti i file originali: {link}" if link
                     else "✅ Produzione completata.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        traceback.print_exc()
        telegram.message(f"❌ Produzione interrotta da un errore imprevisto: {str(e)[:300]}\n{telegram.run_link()}")
        sys.exit(1)
