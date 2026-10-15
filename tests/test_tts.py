import pytest

from brief import tts

T = {"voice_id": "v", "model_id": "m", "stability": 0.5, "similarity_boost": 0.75,
     "output_format": "mp3_44100_128", "max_chars_per_request": 60}


class R:
    def __init__(self, status, content=b"", js=None, text=""):
        self.status_code, self.content, self._js, self.text = status, content, js, text
        self.ok = status < 400

    def json(self):
        return self._js


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return self.responses.pop(0)

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.responses.pop(0)


def test_budget_guard():
    assert tts.check_budget("x" * 1000, 5000, 1.0, 1.1) == 1000
    with pytest.raises(tts.BudgetError):
        tts.check_budget("x" * 1000, 1050, 1.0, 1.1)
    with pytest.raises(tts.BudgetError):  # 2x model doesn't fit
        tts.check_budget("x" * 1000, 1500, 2.0, 1.1)


def test_remaining_credits_and_permission_error():
    s = FakeSession([R(200, js={"character_count": 1000, "character_limit": 363000})])
    assert tts.remaining_credits("k", s) == (362000, 363000)
    s = FakeSession([R(401, text="missing permissions")])
    with pytest.raises(RuntimeError, match="User: Read"):
        tts.remaining_credits("k", s)


def test_split_on_section_boundaries():
    sec = ["A" * 20, "B" * 20, "C" * 20, "D" * 20]
    script = "\n<break time=\"1.5s\" />\n".join(sec)
    chunks = tts.split_script(script, 90)  # each section + break tag is 42 chars
    assert len(chunks) == 2 and all(len(c) <= 90 for c in chunks)
    assert chunks[0].startswith("A") and chunks[1].endswith("D" * 20)
    assert tts.split_script("short", 50) == ["short"]


def test_retry_then_success_and_no_retry_on_4xx():
    s = FakeSession([R(429), R(503), R(200, b"mp3")])
    sleeps = []
    assert tts.synthesize_chunk("hi", T, "k", s, sleeps.append) == b"mp3"
    assert sleeps == [2, 4]
    assert s.calls[0][0].endswith("/text-to-speech/v")
    assert s.calls[0][1]["json"]["model_id"] == "m"
    with pytest.raises(RuntimeError, match="400"):
        tts.synthesize_chunk("hi", T, "k", FakeSession([R(400, text="bad")]), lambda _: None)


def test_gives_up_after_three_retries():
    s = FakeSession([R(500)] * 4)
    with pytest.raises(RuntimeError, match="gave up"):
        tts.synthesize_chunk("hi", T, "k", s, lambda _: None)
    assert len(s.calls) == 4


def test_synthesize_multi_chunk_joins(monkeypatch):
    monkeypatch.setattr(tts.shutil, "which", lambda _: None)
    script = "A" * 40 + "\n\n" + "B" * 40
    s = FakeSession([R(200, b"1"), R(200, b"2")])
    assert tts.synthesize(script, T, "k", s, lambda _: None) == b"12"
