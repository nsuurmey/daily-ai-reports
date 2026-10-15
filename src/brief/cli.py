from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from .build_script import build_script, build_show_notes
from .config import load_config, load_dotenv
from . import publish as pub
from . import tts
from .fetch_notion import Item, fetch_items


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="brief", description="GenAI Daily Brief -> podcast")
    p.add_argument("--date", help="YYYY-MM-DD (default: today in the configured time zone)")
    p.add_argument("--dry-run", action="store_true", help="print script + show notes; no audio, no publishing")
    p.add_argument("--check-budget", action="store_true", help="show remaining ElevenLabs credits and exit")
    p.add_argument("--out-dir", default="out", help="where to write the MP3 (default: out/)")
    p.add_argument("--model", help="override tts.model_id for this run (e.g. eleven_multilingual_v2)")
    p.add_argument("--cost-multiplier", type=float, help="override tts.cost_multiplier for this run")
    p.add_argument("--audio", help="use this existing MP3 instead of synthesizing (no credits spent)")
    p.add_argument("--publish", action="store_true", help="add the episode to the site folder and rebuild feed.xml")
    p.add_argument("--push", action="store_true", help="with --publish: force-push the site to the gh-pages branch")
    p.add_argument("--site-dir", default="site", help="local working copy of the gh-pages branch")
    p.add_argument("--config", help="path to config.yaml")
    p.add_argument("--from-json", help="read items from a JSON file instead of Notion (offline testing)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    load_dotenv()
    cfg = load_config(args.config)
    if args.check_budget:
        key = os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            print("ELEVENLABS_API_KEY is not set.", file=sys.stderr)
            return 2
        remaining, limit = tts.remaining_credits(key)
        print(f"ElevenLabs credits: {remaining:,} remaining of {limit:,}")
        return 0
    tz = ZoneInfo(cfg["timezone"])
    date = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(tz).date()

    if args.from_json:
        with open(args.from_json, encoding="utf-8") as f:
            items = [Item(**row) for row in json.load(f)]
    else:
        token = os.environ.get("NOTION_TOKEN")
        if not token:
            print("NOTION_TOKEN is not set (put it in .env or the environment).", file=sys.stderr)
            return 2
        items = fetch_items(cfg, token, date.isoformat())

    if not items:
        print(f"No brief rows found for {date.isoformat()}.")
        return 0

    script = build_script(date, items, cfg["script"])
    notes = build_show_notes(date, items)

    print(f"=== SPOKEN SCRIPT ({date.isoformat()}) ===\n{script}")
    print(f"=== SHOW NOTES ===\n{notes}\n")
    print(f"=== {len(items)} items, {len(script)} characters ===")

    if args.dry_run:
        return 0

    if args.audio:
        audio = Path(args.audio).read_bytes()
        print(f"Using existing audio {args.audio} ({len(audio) / 1e6:.2f} MB); no credits spent.")
    else:
        audio = synthesize_audio(args, cfg, script, date)
        if audio is None:
            return 1
    if not args.publish:
        return 0
    return publish_site(args, cfg, date, notes, audio)


def synthesize_audio(args, cfg, script: str, date: dt.date):
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        print("ELEVENLABS_API_KEY is not set (put it in .env or the environment).", file=sys.stderr)
        return None
    t = dict(cfg["tts"])
    if args.model:
        t["model_id"] = args.model
    if args.cost_multiplier:
        t["cost_multiplier"] = args.cost_multiplier
    remaining, _ = tts.remaining_credits(key)
    try:
        needed = tts.check_budget(script, remaining, t["cost_multiplier"], t["budget_margin"])
    except tts.BudgetError as e:
        print(str(e), file=sys.stderr)
        return None
    audio = tts.synthesize(script, t, key)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    suffix = f"-{args.model}" if args.model else ""
    path = out / f"{date.isoformat()}{suffix}.mp3"
    path.write_bytes(audio)
    after, _ = tts.remaining_credits(key)
    print(f"Wrote {path} ({len(audio) / 1e6:.2f} MB)")
    print(f"Characters sent: {len(script):,} (estimated credits {needed:,}); "
          f"credits used this run: {remaining - after:,}; remaining: {after:,}")
    return audio


def publish_site(args, cfg, date: dt.date, notes: str, audio: bytes) -> int:
    p = cfg["publish"]
    site = Path(args.site_dir)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PUSH_TOKEN") or ""
    url = pub.remote_url(p["repo"], token)
    existed = pub.fetch_site(url, site, p["branch"], token)
    print(f"{'Fetched existing' if existed else 'No existing'} {p['branch']} branch.")
    ep = pub.Episode(
        date=date.isoformat(), title=pub.episode_title(date), description=notes, bytes=len(audio),
        duration=pub.estimate_duration(len(audio), cfg["tts"].get("output_format", "mp3_44100_128")))
    kept = pub.publish_episode(site, ep, audio, p, cfg["timezone"], Path(p["cover"]))
    print(f"Site built in {site}/ with {len(kept)} episode(s); feed: {p['base_url']}feed.xml")
    if args.push:
        if not token:
            print("--push needs GITHUB_TOKEN (or GH_PUSH_TOKEN) with write access to the repo.", file=sys.stderr)
            return 2
        pub.push_site(url, site, f"Episode {ep.date}", p["branch"], token)
        print(f"Pushed to {p['branch']}.")
    return 0
