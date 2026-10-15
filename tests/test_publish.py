import datetime as dt
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

from brief import publish as pub

PUB = {"base_url": "https://x.github.io/r/", "title": "GenAI Daily Brief", "author": "Nate",
       "description": "d", "keep_episodes": 3}
NS = {"itunes": pub.ITUNES}


def ep(day, desc="<p>hi &amp; <a href=\"https://e.com?a=1&b=2\">x</a></p>"):
    d = dt.date(2026, 10, day)
    return pub.Episode(d.isoformat(), pub.episode_title(d), desc, 1_000_000, 480)


def test_title_duration_pubdate():
    assert pub.episode_title(dt.date(2026, 10, 15)) == "GenAI Brief: Thu Oct 15"
    assert pub.estimate_duration(1_600_000, "mp3_44100_128") == 100
    assert pub.fmt_duration(3725) == "1:02:05"
    assert pub.pub_date("2026-10-15", "America/Denver") == "Thu, 15 Oct 2026 07:00:00 -0600"


def test_feed_structure_and_order():
    xml = pub.build_feed([ep(14), ep(15)], PUB, "America/Denver")
    root = ET.fromstring(xml)  # well-formed
    ch = root.find("channel")
    assert ch.findtext("title") == "GenAI Daily Brief"
    assert ch.findtext("itunes:block", namespaces=NS) == "yes"
    assert ch.findtext("itunes:explicit", namespaces=NS) == "false"
    assert ch.find("itunes:image", NS).get("href") == "https://x.github.io/r/cover.png"
    items = ch.findall("item")
    assert [i.findtext("guid") for i in items] == ["2026-10-15", "2026-10-14"]  # newest first
    enc = items[0].find("enclosure")
    assert enc.get("url") == "https://x.github.io/r/episodes/2026-10-15.mp3"
    assert enc.get("length") == "1000000" and enc.get("type") == "audio/mpeg"
    assert items[0].find("guid").get("isPermaLink") == "false"
    assert items[0].findtext("itunes:duration", namespaces=NS) == "0:08:00"
    assert "<a href=" in items[0].findtext("description")  # HTML survives the round trip


def test_publish_prunes_and_is_idempotent(tmp_path):
    site = tmp_path / "site"
    for d in (10, 11, 12, 13):
        pub.publish_episode(site, ep(d), b"mp3", PUB, "America/Denver")
    assert sorted(p.name for p in (site / "episodes").iterdir()) == [
        "2026-10-11.mp3", "2026-10-12.mp3", "2026-10-13.mp3"]
    pub.publish_episode(site, ep(13), b"mp3-v2", PUB, "America/Denver")  # rebuild same day
    assert len(pub.load_manifest(site)) == 3
    assert (site / "episodes/2026-10-13.mp3").read_bytes() == b"mp3-v2"
    assert pub.episode_exists(site, "2026-10-13") and not pub.episode_exists(site, "2026-10-10")
    assert ET.fromstring((site / "feed.xml").read_text()).find("channel").findall("item").__len__() == 3
    assert (site / ".nojekyll").exists()


def test_git_roundtrip_single_commit(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    url = bare.as_uri()
    site = tmp_path / "site"
    assert pub.fetch_site(url, site) is False  # branch doesn't exist yet
    for d in (10, 11):
        pub.publish_episode(site, ep(d), b"mp3", PUB, "America/Denver")
        pub.push_site(url, site, f"Episode {d}")
        assert pub.fetch_site(url, site) is True
    assert pub.episode_exists(site, "2026-10-10") and pub.episode_exists(site, "2026-10-11")
    count = subprocess.run(["git", "--git-dir", str(bare), "rev-list", "--count", "gh-pages"],
                           capture_output=True, text=True, check=True).stdout.strip()
    assert count == "1"  # history never accumulates
