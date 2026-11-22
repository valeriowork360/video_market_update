"""Shorts and a carousel for every creator video, made as soon as the video is found.

Runs right after the collection. For each new note: one AI call writes all the shorts
(one per salient part) and one carousel, in every language; then they are rendered and
sent to Telegram (and published where configured). What was sent is recorded, so a retry
only completes what is missing.

  python -m mp.social            python -m mp.social --offline   (test, no AI)
"""
import os
import sys
import time
import traceback

os.environ.setdefault("MP_ROLE", "social")

from . import draw, llm, produce, publish, telegram, video, writer   # noqa: E402
from .core import CFG, OUT, ROOT, SCRIPTS, STATE, local_day, log, read_json, write_json   # noqa: E402

MOOD = {"very bearish": "urgent", "bearish": "urgent", "optimistic": "upbeat", "bullish": "upbeat",
        "euphoric": "upbeat"}
BUDGET = 50 * 60            # seconds per run; the rest waits for the next run


def one_video(note, st, offline):
    vid = note["video_id"]
    langs = [l for l in CFG["languages"] if l == "it" or note.get("scope") != "italy"]
    path = (OUT if offline or os.environ.get("MP_SILENT") else SCRIPTS) / "social" / f"{vid}.json"
    data = read_json(path)
    if data is None:
        data, meta = writer.video_shorts(note, langs)
        write_json(path, data)
        log(f"  scritti: " + ", ".join(f"{len(data.get(l, []))} short {l}" for l in langs)
            + f", {len(data.get('carousels', {}))} caroselli ({meta['model']})")
    origin = (data.get(langs[0]) or [{}])[0].get("origin") or note["author"]
    day, mood, sent, problems = local_day(), MOOD.get(note.get("author_tone"), "neutral"), st["sent"], []
    for lang in langs:
        shorts = writer.upgrade({"shorts": data.get(lang, [])})["shorts"]
        label = produce.date_label(day, lang, False)
        folder = OUT / "social" / vid / lang
        todo = [i for i in range(1, len(shorts) + 1) if f"{lang}:s{i}" not in sent]
        car = data.get("carousels", {}).get(lang)
        if todo or (car and f"{lang}:c" not in sent):  # the carousel video follows the carousel
            telegram.message(f"{produce.FLAG[lang]} <b>{telegram.esc(origin)}</b> · nuovo video\n"
                             f"{telegram.esc(note['title'])}\n{len(shorts)} short"
                             + (" e 1 carosello" if car else ""), html_mode=True)
        for i in todo:
            s = shorts[i - 1]
            try:
                mp4, secs = video.short_video(s, i, lang, folder, label, mood)
                cap = f"{s['title']}\n\n{s['caption']}\n\n{' '.join(s['hashtags'])}"
                mp4.with_suffix(".txt").write_text(cap, encoding="utf-8")
                telegram.video(mp4, f"📱 Short {i}/{len(shorts)} · {origin}\n\n{cap}", 1080, 1920, secs)
                sent.append(f"{lang}:s{i}")
                publish.short(f"{day}_social", lang, f"{vid}-{i}", s, mp4)
            except Exception as e:
                problems.append(f"short {lang} {i}: {str(e)[:90]}")
                log(f"    short {lang} {i} saltato: {str(e)[:160]}")
        if car and f"{lang}:c" not in sent:
            try:
                paths = draw.carousel(car, lang, folder / "carousel", label, video.prices_for(car.get("ticker")))
                cap = f"{car['caption']}\n\n{' '.join(car['hashtags'])}"
                (folder / "carousel" / "caption.txt").write_text(cap, encoding="utf-8")
                telegram.album(paths, f"🖼 Carosello · {origin}: {car['topic']}")
                telegram.message("<code>" + telegram.esc(cap) + "</code>", html_mode=True)
                sent.append(f"{lang}:c")
                publish.carousel(f"{day}_social", lang, vid, car, paths)
            except Exception as e:
                problems.append(f"carosello {lang}: {str(e)[:90]}")
                log(f"    carosello {lang} saltato: {str(e)[:160]}")
        if car and CFG.get("carousel_video", True) and f"{lang}:c" in sent and f"{lang}:cv" not in sent:
            try:
                mp4, secs = video.carousel_video(car, lang, folder / "carousel", label, mood,
                                                 video.prices_for(car.get("ticker")), origin)
                cap = f"{car['topic']}\n\n{car['caption']}\n\n{' '.join(car['hashtags'])}"
                mp4.with_suffix(".txt").write_text(cap, encoding="utf-8")
                telegram.video(mp4, f"🎞 Video del carosello · {origin}\n\n{cap}", 1080, 1920, secs)
                sent.append(f"{lang}:cv")
            except Exception as e:
                problems.append(f"video carosello {lang}: {str(e)[:90]}")
                log(f"    video carosello {lang} saltato: {str(e)[:160]}")
        online = publish.report(f"{day}_social", lang)
        if online and (todo or car):
            log("  " + online.replace("\n", " | "))
    return problems


def main():
    offline = "--offline" in sys.argv
    trial = offline or bool(os.environ.get("MP_SILENT"))
    spath = (OUT / "social_trial.json") if trial else (STATE / "social.json")
    state = {} if trial else read_json(spath, {})
    if offline:
        os.environ["MP_OFFLINE"] = "1"
        write_json(OUT / "social" / "sample.json",
                   {**{l: read_json(ROOT / "tests" / f"sample_{l}_social.json")["shorts"] for l in CFG["languages"]},
                    "carousels": {l: read_json(ROOT / "tests" / f"sample_{l}_social.json")["carousels"][0]
                                  for l in CFG["languages"]}})
        notes = [{"video_id": "sample", "author": "MindTheChart", "title": "Video di prova", "scope": "global",
                  "author_tone": "cautious", "market_relevance": 9}]
    else:
        notes = [n for n in produce.load_notes(36) if n.get("market_relevance", 5) >= 3]
    todo = [n for n in notes if not state.get(n["video_id"], {}).get("done")]
    log(f"== Short e caroselli: {len(todo)} video da lavorare ==")
    start, failed = time.time(), []
    for note in todo:
        if time.time() - start > BUDGET:
            log("  tempo esaurito per questo giro: il resto al prossimo")
            break
        st = state.setdefault(note["video_id"], {"sent": [], "tries": 0, "title": note["title"][:80]})
        st["tries"] += 1
        log(f"  {note['author']}: \"{note['title'][:70]}\"")
        try:
            problems = one_video(note, st, offline)
        except llm.KeyProblem:
            raise
        except Exception as e:
            if not isinstance(e, llm.LLMError):
                traceback.print_exc()
            problems = [str(e)[:140]]
            log(f"    rimandato: {problems[0]}")
        st["done"] = not problems or st["tries"] >= 4
        if problems and st["done"]:
            failed.append(f"{note['author']}: {note['title'][:50]} ({problems[0]})")
        for k in sorted(state, key=lambda k: state[k].get("title", ""))[:-300]:
            state.pop(k)
        write_json(spath, state)
    if failed:
        telegram.message("⚠️ Short non completati dopo 4 tentativi:\n- " + "\n- ".join(failed))
    log(f"== Fatto in {int(time.time() - start)}s ==")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        traceback.print_exc()
        telegram.message(f"❌ Short e caroselli interrotti: {str(e)[:300]}\n{telegram.run_link()}")
        sys.exit(1)
