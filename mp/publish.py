"""Automatic publishing through the platforms' own free APIs.

  Instagram  Reels (the shorts) and carousels   -> works as soon as the token is added
  YouTube    long video and Shorts              -> code ready; Google keeps API uploads
                                                   private until it has audited the project,
                                                   so it stays off until config says otherwise

One account per language: every secret ends with _IT or _EN. A platform without its
secrets is simply skipped. Nothing is ever published twice: each item is recorded in
data/state/published.json as soon as the platform confirms it.
"""
import os
import subprocess
import tempfile
import time
from pathlib import Path

import requests
from PIL import Image

from .core import CFG, STATE, log, now, parse_iso, read_json, secret, write_json

P = CFG.get("publish", {})
IG, YT = P.get("instagram", {}), P.get("youtube", {})
LEDGER = STATE / "published.json"
_errors = {}


class Skip(Exception):
    """Not an error: this item is not meant to be published now."""


def active():
    return bool(P.get("enabled", True)) and not any(os.environ.get(k) for k in ("MP_SILENT", "MP_OFFLINE", "MP_PREVIEW"))


def _safe(text):
    """Never let a token reach the (public) logs."""
    text = str(text)
    for k, v in os.environ.items():
        if v and len(v) > 12 and any(t in k for t in ("TOKEN", "SECRET", "KEY")):
            text = text.replace(v, "***")
    return text[:300]


def _http(method, url, **kw):
    kw.setdefault("timeout", 300)
    return requests.request(method, url, **kw)


def _ledger():
    return read_json(LEDGER, {})


def _done(key, item):
    return _ledger().get(key, {}).get(item)


def _record(key, item, value):
    d = _ledger()
    d.setdefault(key, {})[item] = value
    for k in sorted(d)[:-60]:
        d.pop(k)
    write_json(LEDGER, d)


def _count(key, prefix):
    return sum(1 for k in _ledger().get(key, {}) if k.startswith(prefix))


def _attempt(key, lang, item, label, fn):
    """Run one publication with all the guards. Never raises."""
    if not active() or _done(key, item):
        return
    try:
        value = fn()
        _record(key, item, value)
        log(f"    pubblicato: {label}")
        time.sleep(P.get("gap_seconds", 40))
    except Skip as e:
        log(f"    non pubblicato ({label}): {e}")
    except Exception as e:
        msg = _safe(e)
        log(f"    pubblicazione fallita ({label}): {msg}")
        _errors.setdefault((key, lang), []).append(f"{label}: {msg}")


# ================================================================ Instagram
def ig_token(lang):
    return secret(f"IG_TOKEN_{lang.upper()}")


def _ig_base():
    v = str(IG.get("api_version", "") or "")
    return "https://graph.instagram.com" + (f"/{v}" if v else "")


def _ig(lang, method, path, **data):
    r = _http(method, f"{_ig_base()}/{path}", headers={"Authorization": f"Bearer {ig_token(lang)}"},
              **({"params": data} if method == "GET" else {"data": data}))
    try:
        j = r.json()
    except Exception:
        raise RuntimeError(f"Instagram {r.status_code}: {r.text[:160]}")
    if "error" in j:
        e = j["error"]
        raise RuntimeError(f"Instagram: {e.get('error_user_msg') or e.get('message')} (codice {e.get('code')})")
    return j


def ig_me(lang):
    j = _ig(lang, "GET", "me", fields="user_id,username,account_type")
    return j.get("username", "?"), j.get("account_type", "?")


def ig_refresh(lang):
    """Long-lived tokens last 60 days; refreshing extends the same token. Done once a week."""
    meta = read_json(STATE / "publish_meta.json", {})
    last = parse_iso(meta.get(f"ig_refresh_{lang}", ""))
    if last and (now() - last).days < 7:
        return
    try:
        r = _http("GET", "https://graph.instagram.com/refresh_access_token",
                  params={"grant_type": "ig_refresh_token", "access_token": ig_token(lang)}, timeout=60)
        j = r.json()
        if "error" in j:
            raise RuntimeError(j["error"].get("message"))
        meta[f"ig_refresh_{lang}"] = now().isoformat()
        meta[f"ig_expires_{lang}"] = (now().timestamp() + int(j.get("expires_in", 0))) or None
        write_json(STATE / "publish_meta.json", meta)
        log(f"    token Instagram {lang.upper()} rinnovato per altri {int(j.get('expires_in', 0)) // 86400} giorni")
    except Exception as e:
        log(f"    rinnovo token Instagram {lang.upper()} non riuscito: {_safe(e)}")
        _errors.setdefault(("token", lang), []).append(
            f"Il token Instagram {lang.upper()} non si rinnova ({_safe(e)}): rigeneralo dalla pagina dell'app Meta "
            f"e aggiorna il segreto IG_TOKEN_{lang.upper()}.")


def _git(*args, env=None):
    r = subprocess.run(["git", *args], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]}: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def host(files, tag):
    """Instagram downloads media from a public address: park the files on the repository's
    'media' branch (replaced at every use, so the repository does not grow) and return URLs."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise Skip("fuori da GitHub non c'e' un indirizzo pubblico per i file")
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"))
        names = []
        for i, f in enumerate(files):
            blob = _git("hash-object", "-w", str(f))
            name = f"{tag}/{i + 1:02d}{Path(f).suffix}"
            _git("update-index", "--add", "--cacheinfo", f"100644,{blob},{name}", env=env)
            names.append(name)
        tree = _git("write-tree", env=env)
        commit = _git("-c", "user.name=market-pulse-bot", "-c", "user.email=bot@users.noreply.github.com",
                      "commit-tree", tree, "-m", f"media {tag}")
    _git("push", "-f", "-q", "origin", f"{commit}:refs/heads/media")
    urls = [f"https://raw.githubusercontent.com/{repo}/{commit}/{n}" for n in names]
    for _ in range(12):                      # wait until GitHub actually serves them
        try:
            if _http("GET", urls[-1], timeout=30, stream=True).status_code == 200:
                return urls
        except Exception:
            pass
        time.sleep(5)
    raise RuntimeError("i file caricati su GitHub non sono ancora raggiungibili")


def _ig_wait(lang, container, minutes=6):
    for _ in range(minutes * 6):
        j = _ig(lang, "GET", container, fields="status_code,status")
        code = j.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram ha rifiutato il file: {j.get('status') or code}")
        time.sleep(10)
    raise RuntimeError("Instagram non ha finito di elaborare il file in tempo")


def _caption(text):
    words, tags = [], 0
    for w in text.split(" "):
        if w.startswith("#"):
            tags += 1
            if tags > 28:
                continue
        words.append(w)
    return " ".join(words)[:2150]


def ig_carousel(lang, images, caption, tag):
    with tempfile.TemporaryDirectory() as tmp:
        jpgs = []
        for i, p in enumerate(list(images)[:10]):
            j = Path(tmp) / f"{i:02d}.jpg"
            Image.open(p).convert("RGB").save(j, quality=93)
            jpgs.append(j)
        urls = host(jpgs, tag)
    kids = [_ig(lang, "POST", "me/media", image_url=u, is_carousel_item="true")["id"] for u in urls]
    box = _ig(lang, "POST", "me/media", media_type="CAROUSEL", children=",".join(kids),
              caption=_caption(caption))["id"]
    _ig_wait(lang, box)
    return _ig(lang, "POST", "me/media_publish", creation_id=box)["id"]


def ig_reel(lang, mp4, caption, tag):
    mp4 = Path(mp4)
    try:        # direct upload to Meta: no public address needed
        box = _ig(lang, "POST", "me/media", media_type="REELS", upload_type="resumable",
                  caption=_caption(caption), share_to_feed="true")
        uri = box.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{IG.get('api_version') or 'v23.0'}/{box['id']}"
        with open(mp4, "rb") as f:
            r = _http("POST", uri, data=f, headers={"Authorization": f"OAuth {ig_token(lang)}", "offset": "0",
                                                    "file_size": str(mp4.stat().st_size)})
        if not r.ok or not r.json().get("success", True):
            raise RuntimeError(f"caricamento diretto rifiutato: {r.text[:140]}")
        cid = box["id"]
    except Skip:
        raise
    except Exception as e:      # second way: let Instagram fetch it from a public address
        log(f"    caricamento diretto non riuscito ({_safe(e)[:120]}): provo dall'indirizzo pubblico")
        url = host([mp4], tag)[0]
        cid = _ig(lang, "POST", "me/media", media_type="REELS", video_url=url,
                  caption=_caption(caption), share_to_feed="true")["id"]
    _ig_wait(lang, cid)
    return _ig(lang, "POST", "me/media_publish", creation_id=cid)["id"]


# ================================================================ YouTube
def yt_ready(lang):
    return all(secret(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", f"YT_REFRESH_TOKEN_{lang.upper()}"))


def yt_mode():
    m = str(YT.get("mode", "off")).lower()
    return m if m in ("off", "private", "public") else "off"


def _yt_access(lang):
    r = _http("POST", "https://oauth2.googleapis.com/token", timeout=60, data={
        "grant_type": "refresh_token", "client_id": secret("YT_CLIENT_ID"),
        "client_secret": secret("YT_CLIENT_SECRET"),
        "refresh_token": secret(f"YT_REFRESH_TOKEN_{lang.upper()}")})
    j = r.json()
    if "access_token" not in j:
        raise RuntimeError(f"YouTube: accesso rifiutato ({j.get('error_description') or j.get('error')}). "
                           f"Rigenera YT_REFRESH_TOKEN_{lang.upper()}.")
    return j["access_token"]


def yt_whoami(lang):
    r = _http("GET", "https://www.googleapis.com/youtube/v3/channels", timeout=60,
              params={"part": "snippet", "mine": "true"},
              headers={"Authorization": f"Bearer {_yt_access(lang)}"})
    items = r.json().get("items") or []
    if not items:
        raise RuntimeError(f"YouTube: nessun canale collegato a questo accesso ({r.text[:120]})")
    return items[0]["snippet"]["title"]


def yt_upload(lang, mp4, title, description, tags, short=False, thumb=None):
    mode = yt_mode()
    if mode == "off":
        raise Skip("YouTube e' spento in config.yaml finche' Google non approva il progetto")
    mp4 = Path(mp4)
    token = _yt_access(lang)
    if short and "#shorts" not in (title + description).lower():
        description = description + "\n\n#Shorts"
    kept, size = [], 0
    for t in tags or []:
        size += len(t) + 3
        if size < 450:
            kept.append(t)
    body = {"snippet": {"title": title[:100], "description": description[:4900], "tags": kept,
                        "categoryId": str(YT.get("category_id", 25)),
                        "defaultLanguage": lang, "defaultAudioLanguage": lang},
            "status": {"privacyStatus": mode, "selfDeclaredMadeForKids": False}}
    auth = {"Authorization": f"Bearer {token}"}
    r = _http("POST", "https://www.googleapis.com/upload/youtube/v3/videos",
              params={"uploadType": "resumable", "part": "snippet,status"}, json=body,
              headers={**auth, "X-Upload-Content-Type": "video/mp4",
                       "X-Upload-Content-Length": str(mp4.stat().st_size)})
    if r.status_code != 200 or "Location" not in r.headers:
        raise RuntimeError(f"YouTube non ha accettato il video: {r.text[:200]}")
    with open(mp4, "rb") as f:
        up = _http("PUT", r.headers["Location"], data=f, headers={**auth, "Content-Type": "video/mp4"}, timeout=1800)
    if up.status_code not in (200, 201):
        raise RuntimeError(f"YouTube: caricamento interrotto ({up.status_code}: {up.text[:160]})")
    vid = up.json()["id"]
    if thumb:
        try:
            with open(thumb, "rb") as f:
                _http("POST", "https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
                      params={"videoId": vid}, data=f, headers={**auth, "Content-Type": "image/jpeg"})
        except Exception:
            pass
    return vid


# ================================================================ what goes where
def long_video(key, lang, script, mp4, thumb):
    if yt_ready(lang) and yt_mode() != "off":
        _attempt(key + "_" + lang, lang, "yt:long", "YouTube, video lungo",
                 lambda: yt_upload(lang, mp4, script["title"], script["description"], script["tags"], thumb=thumb))


def short(key, lang, i, s, mp4):
    k = key + "_" + lang
    text = f"{s['caption']}\n\n{' '.join(s['hashtags'])}"
    if ig_token(lang):
        def reel():
            if _count(k, "ig:reel") >= IG.get("reels_per_day", 3):
                raise Skip("raggiunto il numero di Reel al giorno (config.yaml)")
            return ig_reel(lang, mp4, f"{s['title']}\n\n{text}", f"{k}/reel{i}")
        _attempt(k, lang, f"ig:reel{i}", f"Instagram, Reel {i}", reel)
    if yt_ready(lang) and yt_mode() != "off":
        def yshort():
            if _count(k, "yt:short") >= YT.get("shorts_per_day", 3):
                raise Skip("raggiunto il numero di Shorts al giorno (config.yaml)")
            return yt_upload(lang, mp4, s["title"], text, [h.lstrip("#") for h in s["hashtags"]], short=True)
        _attempt(k, lang, f"yt:short{i}", f"YouTube, Short {i}", yshort)


def carousel(key, lang, i, c, images):
    k = key + "_" + lang
    if ig_token(lang):
        def car():
            if _count(k, "ig:car") >= IG.get("carousels_per_day", 2):
                raise Skip("raggiunto il numero di caroselli al giorno (config.yaml)")
            return ig_carousel(lang, images, f"{c['caption']}\n\n{' '.join(c['hashtags'])}", f"{k}/car{i}")
        _attempt(k, lang, f"ig:car{i}", f"Instagram, carosello {i}", car)


def prepare(lang):
    if active() and ig_token(lang):
        ig_refresh(lang)


def report(key, lang):
    """One Telegram-ready summary of what went online for this edition, or '' if nothing is set up."""
    if not active() or not (ig_token(lang) or yt_ready(lang)):
        return ""
    got = _ledger().get(key + "_" + lang, {})
    n = lambda p: sum(1 for x in got if x.startswith(p))    # noqa: E731
    lines = [f"📤 Pubblicazione automatica {lang.upper()}"]
    if ig_token(lang):
        lines.append(f"Instagram: {n('ig:reel')} Reel, {n('ig:car')} caroselli")
    if yt_ready(lang):
        if yt_mode() == "off":
            lines.append("YouTube: in attesa dell'approvazione di Google (spento)")
        else:
            lines.append(f"YouTube: {n('yt:long')} video lungo, {n('yt:short')} Shorts ({yt_mode()})")
    bad = _errors.pop((key + "_" + lang, lang), []) + _errors.pop(("token", lang), [])
    if bad:
        lines += ["", "Non riusciti:"] + [f"- {b}" for b in bad[:6]]
    return "\n".join(lines)
