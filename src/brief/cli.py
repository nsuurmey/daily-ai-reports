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
from . import tts
from .fetch_notion import Item, fetch_items


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="brief", description="GenAI Daily Brief -> podcast")
    p.add_argument("--date", help="YYYY-MM-DD (default: today in the configured time zone)")
    p.add_argument("--dry-run", action="store_true", help="print script + show notes; no audio, no publishing")
    p.add_argument("--check-budget", action="store_true", help="show remaining ElevenLabs credits and exit")
    p.add_argument("--out-dir", default="out", help="where to write the MP3 (default: out/)")
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

    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        print("ELEVENLABS_API_KEY is not set (put it in .env or the environment).", file=sys.stderr)
        return 2
    t = cfg["tts"]
    remaining, _ = tts.remaining_credits(key)
    try:
        needed = tts.check_budget(script, remaining, t["cost_multiplier"], t["budget_margin"])
    except tts.BudgetError as e:
        print(str(e), file=sys.stderr)
        return 1
    audio = tts.synthesize(script, t, key)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{date.isoformat()}.mp3"
    path.write_bytes(audio)
    after, _ = tts.remaining_credits(key)
    print(f"Wrote {path} ({len(audio) / 1e6:.2f} MB)")
    print(f"Characters sent: {len(script):,} (estimated credits {needed:,}); "
          f"credits used this run: {remaining - after:,}; remaining: {after:,}")
    return 0
