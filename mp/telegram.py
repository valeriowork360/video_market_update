"""Delivery to your phone through your Telegram bot."""
import html
import json
import os
import time
from pathlib import Path

import requests

from .core import log, secret

LIMIT = 49 * 1024 * 1024       # bots can upload up to ~50 MB


def _api(method, files=None, **data):
    tok, chat = secret("TELEGRAM_BOT_TOKEN"), secret("TELEGRAM_CHAT_ID")
    if os.environ.get("MP_SILENT") or not tok or not chat:
        log(f"  [telegram non inviato] {method}: {str(data.get('text') or data.get('caption') or '')[:90]}")
        return None
    for attempt in range(4):
        try:
            if files:
                for f in files.values():
                    f.seek(0)
            r = requests.post(f"https://api.telegram.org/bot{tok}/{method}",
                              data={"chat_id": chat, **data}, files=files, timeout=600)
            if r.status_code == 429:
                wait = r.json().get("parameters", {}).get("retry_after", 5)
                time.sleep(min(wait + 1, 60))
                continue
            if not r.ok:
                log(f"  telegram {method}: {r.status_code} {r.text[:160]}")
                if r.status_code == 400 and data.get("parse_mode"):
                    data.pop("parse_mode")      # bad formatting: resend as plain text
                    continue
            time.sleep(1.2)
            return r
        except Exception as e:
            log(f"  telegram {method}: {str(e)[:120]}")
            time.sleep(5)
    return None


def message(text, html_mode=False):
    out = None
    text = text.strip()
    while text:
        part, text = text[:3900], text[3900:]
        kw = {"parse_mode": "HTML"} if html_mode else {}
        out = _api("sendMessage", text=part, disable_web_page_preview="true", **kw)
    return out


def esc(s):
    return html.escape(str(s or ""), quote=False)


def video(path, caption="", width=None, height=None, seconds=None):
    p = Path(path)
    if p.stat().st_size > LIMIT:
        message(f"📦 {p.name} supera i 50 MB di Telegram: scaricalo da GitHub > Actions > "
                f"ultima run > Artifacts.\n{run_link()}")
        return False
    kw = {"caption": caption[:1000], "supports_streaming": "true"}
    if width:
        kw.update(width=width, height=height)
    if seconds:
        kw["duration"] = int(seconds)
    with open(p, "rb") as f:
        r = _api("sendVideo", files={"video": f}, **kw)
    return bool(r and r.ok)


def photo(path, caption=""):
    with open(path, "rb") as f:
        r = _api("sendPhoto", files={"photo": f}, caption=caption[:1000])
    return bool(r and r.ok)


def album(paths, caption=""):
    paths = list(paths)[:10]
    files = {f"f{i}": open(p, "rb") for i, p in enumerate(paths)}
    media = [{"type": "photo", "media": f"attach://f{i}"} for i in range(len(paths))]
    media[0]["caption"] = caption[:1000]
    try:
        r = _api("sendMediaGroup", files=files, media=json.dumps(media))
    finally:
        for f in files.values():
            f.close()
    return bool(r and r.ok)


def run_link():
    repo, rid = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    return f"https://github.com/{repo}/actions/runs/{rid}" if repo and rid else ""
