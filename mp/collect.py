"""Every 4 hours: find new videos of the creators, turn each into a note, save market headlines.

Nothing is lost when the AI is busy: a video stays in the queue and is retried at the next run.
Run with:  python -m mp.collect
"""
import os
import shutil
import sys
import traceback
from datetime import timedelta

os.environ.setdefault("MP_ROLE", "collect")

from . import llm, news, quota, telegram, watch, youtube   # noqa: E402
from .core import CFG, NEWS, NOTES, SCRIPTS, STATE, log, now, read_json, write_json  # noqa: E402

C = CFG["collect"]
TONE_IT = {"very bearish": "🔴 molto ribassista", "bearish": "🔴 ribassista", "cautious": "🟠 prudente",
           "neutral": "⚪ neutrale", "optimistic": "🟢 ottimista", "bullish": "🟢 rialzista",
           "euphoric": "🚀 euforico"}
FINAL = ("done", "gave_up", "expired")


def build_queue(state):
    cutoff = now() - timedelta(hours=C["max_age_hours"])
    queue = []
    for ch in CFG["channels"]:
        vids = youtube.feed(ch)
        fresh = 0
        for v in vids:
            st = state.get(v["id"])
            if st and st["status"] in FINAL:
                continue
            if v["published"] and v["published"] < cutoff:
                if st:
                    st["status"] = "expired"
                continue
            queue.append((ch, v))
            fresh += 1
        log(f"  {ch['name']}: {len(vids)} nel feed, {fresh} da analizzare")
    # fewest attempts first, then newest; respect the per-channel and per-run caps
    queue.sort(key=lambda cv: (state.get(cv[1]["id"], {}).get("attempts", 0),
                               -(cv[1]["published"].timestamp() if cv[1]["published"] else 0)))
    picked, per = [], {}
    for ch, v in queue:
        if per.get(ch["name"], 0) >= C["max_per_channel_per_run"]:
            continue
        per[ch["name"]] = per.get(ch["name"], 0) + 1
        picked.append((ch, v))
        if len(picked) >= C["max_videos_per_run"]:
            break
    return picked, len(queue)


def digest(notes, waiting):
    lines = [f"🆕 <b>{len(notes)} video nuovi analizzati</b>"]
    for n in notes:
        tone = TONE_IT.get(n["author_tone"], n["author_tone"])
        flags = []
        if n["market_relevance"] < 3:
            flags.append("non di mercato: escluso dai video")
        if n["scope"] == "italy":
            flags.append("solo Italia: escluso dall'edizione inglese")
        if n.get("partial"):
            flags.append("analizzata solo la prima parte")
        lines.append("")
        lines.append(f"<b>{telegram.esc(n['author'])}</b> · {tone}")
        lines.append(f"<a href=\"{n['url']}\">{telegram.esc(n['title'])}</a>")
        lines.append(telegram.esc(n["digest_it"] or n["summary"]))
        if n["predictions"]:
            lines.append("🎯 " + telegram.esc(n["predictions"][0]))
        if flags:
            lines.append("<i>" + telegram.esc(" · ".join(flags)) + "</i>")
    if waiting:
        lines += ["", f"⏳ Altri {waiting} video in coda per il prossimo giro."]
    telegram.message("\n".join(lines), html_mode=True)


def prune():
    """Keep the repository small."""
    def old(folder, days, key=lambda p: p.name[:10]):
        cut = (now() - timedelta(days=days)).strftime("%Y-%m-%d")
        for p in (folder.iterdir() if folder.exists() else []):
            if key(p) < cut:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
    old(NOTES, 45)
    old(NEWS, 14)
    old(SCRIPTS, 60)


def main():
    state = read_json(STATE / "videos.json", {})
    log("== Canali ==")
    picked, total = build_queue(state)
    log(f"== Analisi: {len(picked)} video in questo giro ({total} in coda) ==")
    cap = CFG["video"]["daily_hours_cap"] * 3600
    new, gave_up, stopped = [], [], ""
    for ch, v in picked:
        if quota.video_seconds() >= cap:
            stopped = "raggiunto il tetto giornaliero di ore video"
            break
        st = state.setdefault(v["id"], {"status": "pending", "attempts": 0, "channel": ch["name"],
                                        "title": v["title"], "first_seen": now().isoformat()})
        m = youtube.meta(v["id"])
        if m["live"] in ("live", "upcoming"):
            log(f"  {ch['name']}: \"{v['title'][:60]}\" e' una live non ancora finita, rimando")
            continue
        v["duration"] = m["duration"]
        mins = f"{m['duration'] // 60} min" if m["duration"] else "durata sconosciuta"
        log(f"  {ch['name']}: \"{v['title'][:70]}\" ({mins})")
        st["attempts"] += 1
        try:
            note = watch.analyse(v, ch)
        except llm.KeyProblem:
            raise
        except llm.LLMError as e:
            st["last_error"] = str(e)[:200]
            log(f"    rimandato: {st['last_error']}")
            if st["attempts"] >= C["max_attempts"]:
                st["status"] = "gave_up"
                gave_up.append(f"{ch['name']}: {v['title'][:60]}")
            if not llm.chain("watch"):
                stopped = "quota video di oggi finita"
                break
            continue
        day = (v["published"] or now()).strftime("%Y-%m-%d")
        write_json(NOTES / day / f"{v['id']}.json", note)
        st.update(status="done", done_at=now().isoformat())
        st.pop("last_error", None)
        new.append(note)
        log(f"    ok: tono {note['author_tone']}, rilevanza {note['market_relevance']}/10, "
            f"{len(note['key_points'])} punti ({note['model']})")
        write_json(STATE / "videos.json", state)

    log("== Notizie ==")
    added = news.fetch_feeds()

    # forget finished videos after a month
    cut = (now() - timedelta(days=30)).isoformat()
    state = {k: s for k, s in state.items() if (s.get("done_at") or s.get("first_seen") or "") > cut}
    write_json(STATE / "videos.json", state)
    prune()

    waiting = max(0, total - len(new) - len(gave_up))
    q = quota.summary()
    log(f"== Fatto: {len(new)} video nuovi, {waiting} in coda, {added} notizie nuove. "
        f"Richieste AI oggi: {q['requests']} · ore video: {q['video_hours']} ==")
    if stopped:
        log(f"   ({stopped})")
    if new and C.get("telegram_digest", True):
        digest(new, waiting)
    if gave_up:
        telegram.message("⚠️ Non sono riuscito ad analizzare questi video dopo "
                         f"{C['max_attempts']} tentativi:\n- " + "\n- ".join(gave_up))


if __name__ == "__main__":
    try:
        main()
    except llm.KeyProblem as e:
        telegram.message(f"❌ Raccolta ferma: {e}")
        log(f"ERRORE: {e}")
        sys.exit(1)
    except Exception as e:
        traceback.print_exc()
        telegram.message(f"❌ Raccolta interrotta da un errore imprevisto: {str(e)[:300]}\n{telegram.run_link()}")
        sys.exit(1)
