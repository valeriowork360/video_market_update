"""Temporary probe: run the real channel reader on GitHub and print what it sees."""
from mp import youtube
from mp.core import CFG

for ch in CFG["channels"]:
    v, src = youtube.feed(ch)
    print(f"=== {ch['name']}: {len(v)} video, fonti {src}", flush=True)
    for x in v[:4] + v[12:14]:
        print(f"   {x['id']} dur={x['duration']} pub={str(x['published'])[:16]} exact={x['exact']} live={x['live']} | {x['title'][:60]}", flush=True)
