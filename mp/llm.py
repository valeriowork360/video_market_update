"""One door to every AI model, built for free tiers.

  watch  -> a model that can watch a YouTube video (Gemini only). Uses the "flash-lite"
            family first: ~500 free requests/day, enough for every video we follow.
  write  -> script writing. Uses the smartest "flash" models first (~20 free requests/day
            each, we need 4), then flash-lite, then the optional backup providers.
  light  -> small text jobs (merging notes): flash-lite first.

Every failure moves on to the next model instead of waiting on a broken one:
  503 overloaded      -> one short retry, then next model
  429 per-minute      -> wait what the API asks (max ~1 min), retry once, then next model
  429 per-day / 404   -> model marked finished for today (remembered across runs)
"""
import json
import re
import time

import requests

from . import quota
from .core import CFG, log, secret

AI = CFG["ai"]


class LLMError(Exception):
    """Every model failed: try again at the next run."""


class BadVideoRequest(Exception):
    """Gemini rejected the video parameters (not a quota problem)."""


class VideoUnavailable(LLMError):
    """Gemini cannot open this video right now (live not processed yet, restricted, removed)."""


class KeyProblem(Exception):
    pass


# ---------------------------------------------------------------- Gemini
_client = None
_pools = None


def client():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types
        key = secret("GEMINI_API_KEY")
        if not key:
            raise KeyProblem("GEMINI_API_KEY mancante: aggiungila in Settings > Secrets > Actions")
        _client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=600_000))
    return _client


def _ver(name):
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def pools():
    """Discover today's model names so a Google rename never breaks the bot."""
    global _pools
    if _pools is not None:
        return _pools
    flash, lite = [], []
    try:
        for m in client().models.list():
            n = (m.name or "").split("/")[-1]
            actions = getattr(m, "supported_actions", None) or []
            if actions and "generateContent" not in actions:
                continue
            if re.fullmatch(r"gemini-\d+(\.\d+)?-flash", n):
                flash.append(n)
            elif re.fullmatch(r"gemini-\d+(\.\d+)?-flash-lite", n):
                lite.append(n)
    except KeyProblem:
        raise
    except Exception as e:
        if _is_key_error(str(e)):
            raise KeyProblem(f"Chiave Gemini rifiutata: {str(e)[:160]}")
        log(f"  elenco modelli non disponibile ({str(e)[:100]}): uso quelli predefiniti")
    flash = sorted(set(flash), key=_ver, reverse=True) or list(AI["default_flash"])
    lite = sorted(set(lite), key=_ver, reverse=True) or list(AI["default_lite"])
    flash = [m for m in flash if _ver(m) >= 2.5][:5]
    lite = [m for m in lite if _ver(m) >= 2.5][:4]
    log(f"  modelli Gemini: scrittura {flash} | video {lite}")
    _pools = {"flash": flash, "lite": lite}
    return _pools


def _is_key_error(msg):
    """Only messages that really speak about the key. A bare 403 PERMISSION_DENIED is what
    Gemini answers when it cannot open one specific YouTube video: that is not a key problem."""
    return any(k in msg for k in ("API_KEY_INVALID", "API key not valid", "API key expired",
                                  "API_KEY_SERVICE_BLOCKED", "UNAUTHENTICATED", "API key was reported"))


def _family(model):
    return "lite" if "lite" in model else "flash"


def chain(task):
    p = pools()
    flash, lite = p["flash"], p["lite"]
    if task == "watch":
        # keep the best writer free for scripts: older flash models are the video reserve
        order = lite + list(reversed(flash[1:]))
    elif task == "light":
        order = lite + list(reversed(flash))
    else:
        order = flash + lite
    out = []
    for m in order:
        if quota.exhausted(m):
            continue
        if quota.used(m) >= AI["daily_caps"][_family(m)]:
            continue
        out.append(m)
    return out


def _parse(text):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 and b > a:
            return json.loads(t[a:b + 1])
        raise


def _retry_delay(msg):
    m = re.search(r"retry in ([\d.]+)\s*s", msg) or re.search(r"retryDelay'?\"?:\s*'?\"?(\d+)", msg)
    return min(float(m.group(1)) + 2, 70) if m else 35


def _gemini_once(model, prompt, video, temperature):
    from google.genai import types
    parts = []
    est = 0
    if video:
        meta = {}
        if video.get("fps"):
            meta["fps"] = video["fps"]
        if video.get("start") is not None:
            meta["start_offset"] = f"{int(video['start'])}s"
        if video.get("end") is not None:
            meta["end_offset"] = f"{int(video['end'])}s"
        parts.append(types.Part(file_data=types.FileData(file_uri=video["url"]),
                                video_metadata=types.VideoMetadata(**meta) if meta else None))
        est = int(video.get("est_tokens") or 0)
    parts.append(types.Part(text=prompt))
    est += len(prompt) // 3
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", temperature=temperature,
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW if video else None)
    quota.pace(model, 7 if _family(model) == "lite" else 13, est)
    quota.add_request(model)
    r = client().models.generate_content(
        model=model, contents=[types.Content(role="user", parts=parts)], config=cfg)
    usage = getattr(r, "usage_metadata", None)
    tokens = getattr(usage, "prompt_token_count", 0) or 0
    audio = 0
    for d in (getattr(usage, "prompt_tokens_details", None) or []):
        if "AUDIO" in str(getattr(d, "modality", "")).upper():
            audio = getattr(d, "token_count", 0) or 0
    quota.spent_tokens(model, tokens or est)
    return _parse(r.text), {"provider": "gemini", "model": model, "prompt_tokens": tokens,
                            "audio_tokens": audio}


def _gemini(task, prompt, video, temperature):
    """Walk the chain once. Returns (data, meta) or raises LLMError."""
    last = "nessun modello Gemini disponibile oggi (quota giornaliera finita)"
    for model in chain(task):
        for attempt in (1, 2):
            try:
                return _gemini_once(model, prompt, video, temperature)
            except json.JSONDecodeError as e:
                last = f"{model}: risposta non valida ({e})"
                log(f"    {last}")
                continue
            except Exception as e:
                msg = str(e)
                code = getattr(e, "code", None) or 0
                last = f"{model}: {msg[:160]}"
                if _is_key_error(msg):
                    raise KeyProblem(f"Chiave Gemini rifiutata: {msg[:160]}")
                if code == 403 or "PERMISSION_DENIED" in msg:
                    if video:
                        raise VideoUnavailable("Gemini non riesce ad aprire questo video adesso "
                                               "(live appena finita, video riservato o rimosso)")
                    log(f"    {model}: non consentito con questa chiave -> modello successivo")
                    break
                if code == 429 or "RESOURCE_EXHAUSTED" in msg:
                    daily = "PerDay" in msg or "per day" in msg.lower() or "limit: 0" in msg
                    if daily:
                        log(f"    {model}: quota di oggi finita -> modello successivo")
                        quota.mark_exhausted(model, "quota giornaliera")
                        break
                    if attempt == 1:
                        d = _retry_delay(msg)
                        log(f"    {model}: limite al minuto, attendo {d:.0f}s")
                        time.sleep(d)
                        continue
                    log(f"    {model}: ancora limitato -> modello successivo")
                    break
                if code == 404 or "NOT_FOUND" in msg:
                    quota.mark_exhausted(model, "non disponibile")
                    break
                if code == 400 or "INVALID_ARGUMENT" in msg:
                    if video:
                        raise BadVideoRequest(msg[:300])
                    log(f"    {model}: richiesta rifiutata ({msg[:120]})")
                    break
                # 500 / 503 / timeouts / connection drops
                if attempt == 1:
                    log(f"    {model}: sovraccarico ({msg[:80]}), riprovo tra 10s")
                    time.sleep(10)
                    continue
                log(f"    {model}: ancora sovraccarico -> modello successivo")
                break
    raise LLMError(last)


# ---------------------------------------------------------------- backup providers
_backup_model = {}


def backups():
    return [b for b in AI.get("backups", []) if secret(b["secret"])]


def _pick_model(b):
    if b["name"] in _backup_model:
        return _backup_model[b["name"]]
    chosen = b["models"][0]
    try:
        r = requests.get(b["base_url"] + "/models", timeout=30,
                         headers={"Authorization": f"Bearer {secret(b['secret'])}"})
        ids = [m.get("id", "") for m in r.json().get("data", [])]
        hit = [m for m in b["models"] if m in ids]
        if hit:
            chosen = hit[0]
        elif ids:
            chat = [i for i in ids if not re.search(r"whisper|tts|guard|embed|moderation|ocr|voxtral", i)]
            big = [i for i in chat if re.search(r"large|120b|70b|medium", i)]
            chosen = (big or chat or ids)[0]
    except Exception as e:
        log(f"    {b['name']}: elenco modelli non letto ({str(e)[:80]})")
    _backup_model[b["name"]] = chosen
    return chosen


def _backup_once(b, prompt, temperature):
    model = _pick_model(b)
    body = {"model": model, "temperature": temperature, "max_tokens": b.get("max_tokens", 4000),
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": "You answer with one valid JSON object only."},
                         {"role": "user", "content": prompt}]}
    for attempt in (1, 2):
        r = requests.post(b["base_url"] + "/chat/completions", json=body, timeout=240,
                          headers={"Authorization": f"Bearer {secret(b['secret'])}"})
        if r.status_code == 429 and attempt == 1:
            d = min(float(r.headers.get("retry-after", 30) or 30) + 2, 70)
            log(f"    {b['name']}: limite, attendo {d:.0f}s")
            time.sleep(d)
            continue
        if not r.ok:
            raise LLMError(f"{b['name']} {r.status_code}: {r.text[:160]}")
        return _parse(r.json()["choices"][0]["message"]["content"]), \
            {"provider": b["name"], "model": model, "prompt_tokens": 0, "audio_tokens": 0}
    raise LLMError(f"{b['name']}: limite di richieste")


# ---------------------------------------------------------------- public
def ask(task, make_prompt, video=None, temperature=0.5, patience=1):
    """Return (json, meta).

    make_prompt(max_chars) builds the prompt within a size budget, so small free
    providers get a shorter version of the same request. `patience` is how many times
    to walk the whole chain again (after a pause) before giving up.
    """
    last = None
    for round_ in range(patience + 1):
        if round_:
            log("    tutti i modelli occupati: pausa di 90s e nuovo giro")
            time.sleep(90)
        try:
            return _gemini(task, make_prompt(400_000), video, temperature)
        except (BadVideoRequest, KeyProblem, VideoUnavailable):
            raise
        except LLMError as e:
            last = e
        if video:
            continue
        for b in backups():
            try:
                out = _backup_once(b, make_prompt(b.get("max_chars", 20000)), temperature)
                log(f"    scritto con la riserva {b['name']} ({out[1]['model']})")
                return out
            except Exception as e:
                last = e
                log(f"    riserva {b['name']} fallita: {str(e)[:140]}")
    raise LLMError(str(last))
