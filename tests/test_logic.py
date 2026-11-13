"""Offline checks of the decision logic (no network, no AI).  Run:  python -m tests.test_logic"""
import json
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace as NS

os.environ["MP_ROLE"] = "test"
os.environ["GEMINI_API_KEY"] = "test"

from mp import llm, quota, watch, writer   # noqa: E402

TMP = Path(tempfile.mkdtemp())
quota.STATE = TMP
time.sleep = lambda s: None          # no real waiting in tests
quota.pace = lambda *a, **k: None


class Err(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


class FakeModels:
    def __init__(self, behaviour):
        self.behaviour, self.calls = behaviour, []

    def list(self):
        names = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
                 "gemini-3.8-flash-tts", "gemini-3.8-flash-preview-09", "gemini-4-argon", "gemini-flash-latest"]
        return [NS(name="models/" + n, supported_actions=["generateContent"]) for n in names]

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        b = self.behaviour.get(model, "ok")
        if callable(b):
            b = b(contents)
        if isinstance(b, Exception):
            raise b
        text = b if b != "ok" else json.dumps({"ok": True, "model": model})
        return NS(text=text, usage_metadata=NS(prompt_token_count=1000, prompt_tokens_details=[]))


def fresh(behaviour):
    for f in TMP.glob("quota_*.json"):
        f.unlink()
    fm = FakeModels(behaviour)
    llm._client, llm._pools = NS(models=fm), None
    return fm


def test_router():
    fm = fresh({})
    assert llm.pools() == {"flash": ["gemini-3.8-flash", "gemini-3.6-flash"],
                           "lite": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]}
    assert llm.chain("watch") == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash"]
    assert llm.chain("write")[0] == "gemini-3.8-flash"

    # 503 on the best writer -> one retry, then the next model answers
    fm = fresh({"gemini-3.8-flash": Err(503, "503 UNAVAILABLE high demand")})
    d, m = llm.ask("write", lambda n: "x", patience=0)
    assert m["model"] == "gemini-3.6-flash" and fm.calls == ["gemini-3.8-flash"] * 2 + ["gemini-3.6-flash"]

    # daily quota finished -> remembered, never called again today
    fm = fresh({"gemini-3.5-flash-lite": Err(429, "429 RESOURCE_EXHAUSTED quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier")})
    d, m = llm.ask("watch", lambda n: "x", video={"url": "u"}, patience=0)
    assert m["model"] == "gemini-3.1-flash-lite"
    assert quota.exhausted("gemini-3.5-flash-lite") and "gemini-3.5-flash-lite" not in llm.chain("watch")
    fm.calls.clear()
    llm.ask("watch", lambda n: "x", video={"url": "u"}, patience=0)
    assert fm.calls == ["gemini-3.1-flash-lite"]

    # per-minute limit -> wait and retry the same model
    seq = iter([Err(429, "429 RESOURCE_EXHAUSTED Please retry in 12.5s"), "ok"])
    fm = fresh({"gemini-3.8-flash": lambda c: next(seq)})
    d, m = llm.ask("write", lambda n: "x", patience=0)
    assert m["model"] == "gemini-3.8-flash" and len(fm.calls) == 2

    # everything down -> LLMError, and the request cap protects the quota
    fm = fresh({k: Err(503, "503 UNAVAILABLE") for k in
                ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]})
    try:
        llm.ask("write", lambda n: "x", patience=1)
        raise AssertionError("should fail")
    except llm.LLMError:
        pass
    assert len(fm.calls) == 16
    for _ in range(9):
        try:
            llm.ask("write", lambda n: "x", patience=0)
        except llm.LLMError:
            pass
    assert quota.used("gemini-3.8-flash") <= llm.AI["daily_caps"]["flash"]
    assert "gemini-3.8-flash" not in llm.chain("write")

    # broken JSON, then good JSON
    seq2 = iter(["not json", '```json\n{"a": 1}\n```'])
    fresh({"gemini-3.8-flash": lambda c: next(seq2)})
    d, m = llm.ask("write", lambda n: "x", patience=0)
    assert d == {"a": 1}

    # rejected video parameters surface as BadVideoRequest
    fresh({"gemini-3.5-flash-lite": Err(400, "400 INVALID_ARGUMENT fps")})
    try:
        llm.ask("watch", lambda n: "x", video={"url": "u", "fps": 0.2}, patience=0)
        raise AssertionError("should fail")
    except llm.BadVideoRequest:
        pass
    print("router ok")


NOTE = {"market_relevance": 8, "scope": "global", "kind": "market update", "summary": "S.", "digest_it": "D.",
        "author_tone": "cautious", "tone_evidence": "e", "key_points": [{"point": "p", "timestamp": "01:00"}],
        "tickers": ["NVDA"], "predictions": ["x"], "catalysts": [], "rumors": [], "curiosities": [], "promo": False}


def test_watch():
    calls = []

    def fake_ask(task, make, video=None, temperature=0.5, patience=1):
        calls.append((task, video))
        if task == "light":
            return dict(NOTE, summary="merged"), {"model": "lite", "prompt_tokens": 0, "audio_tokens": 0}
        span = (video["end"] or 0) - (video["start"] or 0)
        audio = min(span, max(0, state["real"] - (video["start"] or 0))) * 32 if state["real"] else 0
        return dict(NOTE), {"model": "lite", "prompt_tokens": 0, "audio_tokens": audio}

    state = {"real": 0}
    watch.llm.ask = fake_ask
    ch = {"name": "A"}
    # known length, 100 minutes -> 40 + 40 + 20, then one merge
    v = {"id": "x", "title": "t", "url": "u", "duration": 6000, "published": None}
    n = watch.analyse(v, ch)
    spans = [(c[1]["start"], c[1]["end"]) for c in calls if c[0] == "watch"]
    assert spans == [(None, 2400), (2400, 4800), (4800, 6000)], spans
    assert n["summary"] == "merged" and not n["partial"]
    # short video with known length -> one call, no offsets
    calls.clear()
    watch.analyse(dict(v, duration=600), ch)
    assert [(c[1]["start"], c[1]["end"]) for c in calls] == [(None, None)]
    # longer than the cap -> analysed up to max_minutes and flagged partial
    calls.clear()
    n = watch.analyse(dict(v, duration=4 * 3600), ch)
    assert n["partial"] and calls[-2][1]["end"] == watch.V["max_minutes"] * 60
    # unknown length: stops when the audio shows the video ended (55 minutes)
    calls.clear()
    state["real"] = 55 * 60
    n = watch.analyse(dict(v, duration=None), ch)
    spans = [(c[1]["start"], c[1]["end"]) for c in calls if c[0] == "watch"]
    assert spans == [(None, 2400), (2400, 4800)], spans
    print("watch ok")


def test_writer():
    notes = [dict(NOTE, author=f"A{i}", title="T" * 80, summary="S" * 500, video_id=str(i),
                  key_points=[{"point": "P" * 120, "timestamp": ""}] * 8) for i in range(12)]
    news = [{"title": f"Headline {i} " + "h" * 60, "source": "CNBC", "summary": "s" * 200} for i in range(80)]
    big = writer._fit(notes, news, 400_000)
    small = writer._fit(notes, news, 6000)
    assert len(big[0]) + len(big[1]) > 20000 and len(small[0]) + len(small[1]) <= 6000

    sample = json.loads((Path(__file__).parent / "sample_it.json").read_text(encoding="utf-8"))
    for seg in sample["segments"]:
        seg["narration"] = seg["narration"] + " " + seg["narration"]
    seen = {}

    def fake_ask(task, make, video=None, temperature=0.5, patience=1):
        seen["full"], seen["small"] = make(400_000), make(11_000)
        return sample, {"model": "m"}

    writer.llm.ask = fake_ask
    s, _ = writer.long_script(notes, news, [{"name": "S&P 500", "last": 1}], [], "it", "daily", "13/11/2026")
    assert len(seen["small"]) <= 11_500 and "@@" not in seen["full"] and "Italian" in seen["full"]
    assert s["mood"] == "urgent" and len(s["segments"]) == 5

    soc = json.loads((Path(__file__).parent / "sample_it_social.json").read_text(encoding="utf-8"))
    writer.llm.ask = lambda *a, **k: (soc, {"model": "m"})
    d, _ = writer.derivatives(s, "it", "daily")
    assert len(d["shorts"]) == 2 and len(d["carousels"]) == 1 and d["shorts"][0]["hashtags"][0].startswith("#")
    w, _ = writer.derivatives(s, "it", "weekly")
    assert w["shorts"] == []
    print("writer ok")


def test_channel_page():
    from mp import youtube
    card = ('"lockupViewModel":{"contentImage":{"thumbnailBadgeViewModel":{"text":"%s"}},"contentId":"%s",'
            '"metadata":{"lockupMetadataViewModel":{"title":{"content":"%s"},"rows":[{"text":{"content":"4.4K"}},'
            '{"text":{"content":"%s"}}]}}}')
    html = ("x" + card % ("25:43", "aNNrh4GJGuA", "Bitcoin \\u0026 Stocks", "2h ago")
            + card % ("1:31:05", "e36oHWwLK34", "Live recap", "Streamed 2d ago")
            + '"lockupViewModel":{"contentId":"PLAYLIST0001","metadata":{"lockupMetadataViewModel":{"title":{"content":"Playlist"}}}}')
    v = youtube.parse_tab(html)
    assert [(x["id"], x["duration"], x["age"]) for x in v] == [("aNNrh4GJGuA", 1543, 7200), ("e36oHWwLK34", 5465, 172800)], v
    assert v[0]["title"] == "Bitcoin & Stocks"
    print("channel page ok")


if __name__ == "__main__":
    test_channel_page()
    test_router()
    test_watch()
    test_writer()
    print("TUTTO OK")
