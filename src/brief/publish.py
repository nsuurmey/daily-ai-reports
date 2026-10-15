"""Build the podcast site (feed.xml + episodes) and publish it to the gh-pages branch."""
from __future__ import annotations

import datetime as dt
import email.utils
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("itunes", ITUNES)
ET.register_namespace("atom", ATOM)

MANIFEST = "episodes.json"


@dataclass
class Episode:
    date: str            # YYYY-MM-DD
    title: str
    description: str     # show notes (HTML)
    bytes: int
    duration: int        # seconds


# --- pure helpers --------------------------------------------------------------

def episode_title(date: dt.date) -> str:
    return f"GenAI Brief: {date.strftime('%a %b')} {date.day}"


def estimate_duration(num_bytes: int, output_format: str = "mp3_44100_128") -> int:
    """Seconds, assuming constant bitrate (ElevenLabs MP3 output is CBR)."""
    m = re.search(r"_(\d+)$", output_format)
    kbps = int(m.group(1)) if m else 128
    return round(num_bytes * 8 / (kbps * 1000))


def fmt_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}"


def pub_date(date_iso: str, tz_name: str, hour: int = 7) -> str:
    d = dt.date.fromisoformat(date_iso)
    return email.utils.format_datetime(dt.datetime(d.year, d.month, d.day, hour, tzinfo=ZoneInfo(tz_name)))


def prune(episodes: list[Episode], keep: int) -> tuple[list[Episode], list[Episode]]:
    """Newest-first list; returns (kept, dropped)."""
    ordered = sorted(episodes, key=lambda e: e.date, reverse=True)
    return ordered[:keep], ordered[keep:]


def build_feed(episodes: list[Episode], pub: dict, tz_name: str) -> str:
    base = pub["base_url"].rstrip("/") + "/"
    rss = ET.Element("rss", {"version": "2.0"})
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = pub["title"]
    ET.SubElement(ch, "link").text = base
    ET.SubElement(ch, "description").text = pub["description"]
    ET.SubElement(ch, "language").text = pub.get("language", "en-us")
    ET.SubElement(ch, f"{{{ATOM}}}link", {"href": base + "feed.xml", "rel": "self",
                                          "type": "application/rss+xml"})
    ET.SubElement(ch, f"{{{ITUNES}}}author").text = pub["author"]
    ET.SubElement(ch, f"{{{ITUNES}}}block").text = "yes"
    ET.SubElement(ch, f"{{{ITUNES}}}explicit").text = "false"
    ET.SubElement(ch, f"{{{ITUNES}}}type").text = "episodic"
    ET.SubElement(ch, f"{{{ITUNES}}}image", {"href": base + "cover.png"})
    ET.SubElement(ch, f"{{{ITUNES}}}category", {"text": "Technology"})
    for ep in sorted(episodes, key=lambda e: e.date, reverse=True):
        it = ET.SubElement(ch, "item")
        ET.SubElement(it, "title").text = ep.title
        ET.SubElement(it, "description").text = ep.description
        ET.SubElement(it, "guid", {"isPermaLink": "false"}).text = ep.date
        ET.SubElement(it, "pubDate").text = pub_date(ep.date, tz_name)
        ET.SubElement(it, "enclosure", {"url": f"{base}episodes/{ep.date}.mp3",
                                        "length": str(ep.bytes), "type": "audio/mpeg"})
        ET.SubElement(it, f"{{{ITUNES}}}duration").text = fmt_duration(ep.duration)
        ET.SubElement(it, f"{{{ITUNES}}}explicit").text = "false"
    ET.indent(rss)
    body = ET.tostring(rss, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'


# --- site directory ------------------------------------------------------------

def load_manifest(site: Path) -> list[Episode]:
    f = site / MANIFEST
    if not f.is_file():
        return []
    return [Episode(**row) for row in json.loads(f.read_text(encoding="utf-8"))]


def episode_exists(site: Path, date_iso: str) -> bool:
    return (site / "episodes" / f"{date_iso}.mp3").is_file()


def publish_episode(site: Path, ep: Episode, mp3: bytes, pub: dict, tz_name: str,
                    cover: Path | None = None) -> list[Episode]:
    """Write the MP3, update the manifest, prune old episodes, rewrite feed.xml."""
    site.mkdir(parents=True, exist_ok=True)
    (site / "episodes").mkdir(exist_ok=True)
    (site / ".nojekyll").touch()
    (site / "episodes" / f"{ep.date}.mp3").write_bytes(mp3)
    if cover and cover.is_file():
        shutil.copyfile(cover, site / "cover.png")
    eps = [e for e in load_manifest(site) if e.date != ep.date] + [ep]
    kept, dropped = prune(eps, pub["keep_episodes"])
    for d in dropped:
        (site / "episodes" / f"{d.date}.mp3").unlink(missing_ok=True)
    (site / MANIFEST).write_text(json.dumps([asdict(e) for e in kept], indent=1), encoding="utf-8")
    (site / "feed.xml").write_text(build_feed(kept, pub, tz_name), encoding="utf-8")
    return kept


# --- git (gh-pages) ------------------------------------------------------------

def _git(args: list[str], cwd: Path, secret: str = "") -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip()
        if secret:
            msg = msg.replace(secret, "***")
        raise RuntimeError(f"git {args[0]} failed: {msg}")
    return r.stdout


def remote_url(repo: str, token: str = "") -> str:
    if repo.startswith(("file://", "/")) or repo.startswith("http"):
        return repo
    auth = f"x-access-token:{token}@" if token else ""
    return f"https://{auth}github.com/{repo}.git"


def fetch_site(url: str, site: Path, branch: str = "gh-pages", secret: str = "") -> bool:
    """Clone the existing branch into site/. Returns False (empty dir) if it doesn't exist yet."""
    if site.exists():
        shutil.rmtree(site)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _git(["clone", "--depth", "1", "--branch", branch, url, str(Path(tmp) / "c")],
                 Path(tmp), secret)
        except RuntimeError as e:
            if "not found" in str(e).lower() or "remote branch" in str(e).lower():
                site.mkdir(parents=True)
                return False
            raise
        shutil.move(str(Path(tmp) / "c"), site)
    shutil.rmtree(site / ".git")
    return True


def push_site(url: str, site: Path, message: str, branch: str = "gh-pages", secret: str = "") -> None:
    """Replace the branch with a single fresh commit so audio never piles up in git history."""
    if (site / ".git").exists():
        shutil.rmtree(site / ".git")
    _git(["init", "-q", "-b", branch], site)
    _git(["add", "-A"], site)
    _git(["-c", "user.name=brief-bot", "-c", "user.email=brief-bot@users.noreply.github.com",
          "commit", "-q", "-m", message], site)
    _git(["push", "--force", url, f"HEAD:{branch}"], site, secret)
    shutil.rmtree(site / ".git")
