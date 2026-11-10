"""Daily or weekly production.

  python pipeline/produce.py daily
  python pipeline/produce.py weekly
  python pipeline/produce.py daily --package test/sample_package.json   (offline test)
"""
import argparse
from datetime import datetime, timedelta

import deliver
import render
from common import CFG, OUT, now, notes_between, news_between, read_json, today_str, write_json
from write import build


def recent_notes(hours):
    start = (now() - timedelta(hours=hours)).isoformat()
    ns = notes_between(today_str(-(hours // 24 + 1)), today_str())
    return [n for n in ns if n.get("analysed_at", "") >= start]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["daily", "weekly"])
    ap.add_argument("--package", help="use a ready-made script JSON instead of calling Gemini")
    ap.add_argument("--lang", help="only this language")
    a = ap.parse_args()

    hours = 24 * 7 if a.kind == "weekly" else 24
    date = today_str()
    folder = OUT / f"{date}_{a.kind}"
    langs = [a.lang] if a.lang else CFG["languages"]

    notes = news = None
    if not a.package:
        notes = recent_notes(hours)
        news = news_between(today_str(-(hours // 24)), today_str())
        print(f"Video analizzati nel periodo: {len(notes)} — notizie: {len(news)}")
        if not notes:
            deliver.message(f"ℹ️ {a.kind}: nessun video nuovo dai canali seguiti, niente da produrre.")
            return

    report = []
    for lang in langs:
        print(f"== {lang.upper()} ==")
        pkg = read_json(a.package) if a.package else build(notes, news, lang, a.kind)
        lf = folder / lang
        write_json(lf / "script.json", pkg)
        label = datetime.strptime(date, "%Y-%m-%d").strftime("%d/%m/%Y")
        if a.kind == "weekly":
            label = ("Settimana al " if lang == "it" else "Week to ") + label

        print("  video lungo…")
        long_path = render.long_video(pkg, lang, lf, label)
        (lf / "youtube.txt").write_text(
            f"{pkg.get('title', '')}\n\n{pkg.get('description', '')}\n\nTags: {', '.join(pkg.get('tags', []))}",
            encoding="utf-8")

        shorts = []
        if a.kind == "daily":
            print("  short…")
            shorts = render.shorts(pkg, lang, lf / "shorts")

        print("  caroselli…")
        cars = []
        for i, car in enumerate(pkg.get("carousels", []), 1):
            cf = lf / "carousels" / f"{i:02d}"
            paths = render.carousel(car, cf, lang)
            (cf / "caption.txt").write_text(
                car.get("caption", "") + "\n\n" + " ".join(car.get("hashtags", [])), encoding="utf-8")
            cars.append((car, paths))

        report.append((lang, pkg, long_path, shorts, cars))

    # ---- deliver for approval
    for lang, pkg, long_path, shorts, cars in report:
        flag = "🇮🇹" if lang == "it" else "🇬🇧"
        deliver.message(f"{flag} {a.kind.upper()} {date}\n🎬 {pkg.get('title', '')}\n\n"
                        f"{len(shorts)} short · {len(cars)} caroselli\n{deliver.run_link()}")
        deliver.video(long_path, pkg.get("title", ""))
        for s in shorts:
            deliver.video(s, s.with_suffix(".txt").read_text(encoding="utf-8"))
        for car, paths in cars:
            deliver.album(paths, car.get("caption", ""))
    print(f"Fatto. Output in {folder}")


if __name__ == "__main__":
    main()
