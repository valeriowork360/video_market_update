"""Temporary network probe (run on GitHub to see what YouTube answers from there)."""
import re

import requests

BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.8"}
for cid, tabs in (("UCIb34uXDsfTq4PJKW0eztkA", ("videos", "streams")), ("UC_xMKlHYdRNXLX9XzuOLjsg", ("videos",)), ("UCzqvRwYvABKPwhw8hgH5ugA", ("videos", "streams"))):
    for path in tabs:
        r = requests.get(f"https://www.youtube.com/channel/{cid}/{path}", headers=BROWSER, cookies={"CONSENT": "YES+1", "SOCS": "CAI"}, timeout=30)
        t = r.text
        print(f"=== {cid} /{path} {r.status_code} videoRenderer={t.count('videoRenderer')} lockup={t.count('lockupViewModel')} richItem={t.count('richItemRenderer')} ago={len(re.findall(r' ago\"', t))} upcoming={t.count('UPCOMING')} LIVE={t.count('BADGE_STYLE_TYPE_LIVE_NOW')}", flush=True)
        seen = []
        for m in re.finditer(r'"videoId":"([\w-]{11})"', t):
            v = m.group(1)
            if v in seen:
                continue
            seen.append(v)
            if len(seen) > 3:
                break
            ctx = t[m.start(): m.start() + 6000]
            nxt = re.search(r'"videoId":"(?!%s)[\w-]{11}"' % re.escape(v), ctx)
            if nxt:
                ctx = ctx[: nxt.start()]
            vals = re.findall(r'"(text|content|simpleText|label|style|title|iconType|accessibilityText)":"([^"]{1,90})"', ctx)
            print(f"--- {v} ctx={len(ctx)}", flush=True)
            print("    " + " | ".join(f"{k}={x}" for k, x in vals[:28]), flush=True)
        if path == "videos" and cid.endswith("eztkA"):
            i = t.find('"videoId":"%s"' % seen[0])
            print("RAW:", t[max(0, i - 600): i + 2200].replace("\n", " "), flush=True)
