"""ElevenLabs text-to-speech with a budget guard, retries and chunking."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests

API = "https://api.elevenlabs.io/v1"
# Boundaries between script sections: a <break .../> line or a blank line.
_SEP = re.compile(r"(\n<break [^>]*/>\n|\n\n)")


class BudgetError(RuntimeError):
    pass


def _headers(api_key: str) -> dict:
    return {"xi-api-key": api_key}


def _fail(what: str, r: requests.Response) -> RuntimeError:
    # Response bodies never echo the key; still truncate.
    return RuntimeError(f"ElevenLabs {what} -> {r.status_code}: {r.text[:300]}")


def remaining_credits(api_key: str, session: requests.Session | None = None) -> tuple[int, int]:
    """Return (remaining, limit) for the current billing cycle."""
    s = session or requests
    r = s.get(f"{API}/user/subscription", headers=_headers(api_key), timeout=30)
    if r.status_code in (401, 403):
        raise RuntimeError(
            f"ElevenLabs refused the subscription check ({r.status_code}). Check the API key "
            "and that it has 'User: Read' permission. " + r.text[:200])
    if not r.ok:
        raise _fail("subscription", r)
    d = r.json()
    used, limit = int(d["character_count"]), int(d["character_limit"])
    return limit - used, limit


def check_budget(script: str, remaining: int, cost_multiplier: float, margin: float) -> int:
    """Raise BudgetError if the script won't fit. Returns the estimated credits needed."""
    needed = int(len(script) * cost_multiplier)
    if remaining < needed * margin:
        raise BudgetError(
            f"Not enough ElevenLabs credits: {remaining:,} remaining, need about "
            f"{needed:,} (+{(margin - 1) * 100:.0f}% margin). Not synthesizing.")
    return needed


def split_script(script: str, max_chars: int) -> list[str]:
    """Split on section boundaries into chunks of at most max_chars (when possible)."""
    if len(script) <= max_chars:
        return [script]
    parts = _SEP.split(script)
    sections = parts[0::2]
    seps = parts[1::2] + [""]
    chunks: list[str] = []
    cur = ""
    for sec, sep in zip(sections, seps):
        piece = sec + sep
        if cur and len(cur) + len(piece) > max_chars:
            chunks.append(cur.rstrip("\n"))
            cur = ""
        cur += piece
    if cur.strip():
        chunks.append(cur.rstrip("\n"))
    return chunks


def synthesize_chunk(text: str, tts_cfg: dict, api_key: str,
                     session: requests.Session | None = None, sleep=time.sleep) -> bytes:
    s = session or requests
    url = f"{API}/text-to-speech/{tts_cfg['voice_id']}"
    body = {
        "text": text,
        "model_id": tts_cfg["model_id"],
        "voice_settings": {"stability": tts_cfg["stability"],
                           "similarity_boost": tts_cfg["similarity_boost"]},
    }
    params = {"output_format": tts_cfg.get("output_format", "mp3_44100_128")}
    last = None
    for attempt in range(4):  # first try + 3 retries
        r = s.post(url, headers=_headers(api_key), params=params, json=body, timeout=180)
        if r.status_code == 429 or r.status_code >= 500:
            last = r
            sleep(2 ** (attempt + 1))
            continue
        if not r.ok:
            raise _fail("text-to-speech", r)
        return r.content
    raise _fail("text-to-speech (gave up after retries)", last)


def join_mp3(parts: list[bytes]) -> bytes:
    if len(parts) == 1:
        return parts[0]
    if shutil.which("ffmpeg"):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            lst = []
            for i, b in enumerate(parts):
                (d / f"{i}.mp3").write_bytes(b)
                lst.append(f"file '{d / f'{i}.mp3'}'")
            (d / "list.txt").write_text("\n".join(lst))
            out = d / "out.mp3"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                            "-i", str(d / "list.txt"), "-c", "copy", str(out)], check=True)
            return out.read_bytes()
    return b"".join(parts)  # MP3 frames concatenate acceptably; ffmpeg is nicer


def synthesize(script: str, tts_cfg: dict, api_key: str,
               session: requests.Session | None = None, sleep=time.sleep) -> bytes:
    if not tts_cfg.get("voice_id"):
        raise RuntimeError("tts.voice_id is empty in config.yaml")
    chunks = split_script(script, tts_cfg["max_chars_per_request"])
    audio = [synthesize_chunk(c, tts_cfg, api_key, session, sleep) for c in chunks]
    return join_mp3(audio)
