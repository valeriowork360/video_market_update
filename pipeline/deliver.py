"""Send finished media to your phone via a Telegram bot (free) for approval."""
import json
import os
from pathlib import Path

import requests

LIMIT = 49 * 1024 * 1024  # Telegram bot upload limit ~50 MB


def _api(method, **kw):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return None
    url = f"https://api.telegram.org/bot{tok}/{method}"
    files = kw.pop("files", None)
    r = requests.post(url, data={"chat_id": chat, **kw}, files=files, timeout=300)
    if not r.ok:
        print(f"  Telegram {method}: {r.status_code} {r.text[:200]}")
    return r


def message(text):
    return _api("sendMessage", text=text[:4000], disable_web_page_preview="true")


def video(path, caption=""):
    p = Path(path)
    if p.stat().st_size > LIMIT:
        message(f"📦 {p.name} è troppo grande per Telegram: scaricalo dagli Artifacts della run su GitHub.")
        return
    with open(p, "rb") as f:
        _api("sendVideo", caption=caption[:1000], supports_streaming="true", files={"video": f})


def album(paths, caption=""):
    paths = list(paths)[:10]
    media, files = [], {}
    for i, p in enumerate(paths):
        files[f"f{i}"] = open(p, "rb")
        m = {"type": "photo", "media": f"attach://f{i}"}
        if i == 0:
            m["caption"] = caption[:1000]
        media.append(m)
    try:
        _api("sendMediaGroup", media=json.dumps(media), files=files)
    finally:
        for f in files.values():
            f.close()


def run_link():
    repo, rid = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    return f"https://github.com/{repo}/actions/runs/{rid}" if repo and rid else ""
