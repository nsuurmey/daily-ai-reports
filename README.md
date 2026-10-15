# GenAI Daily Brief → Private Podcast

Turns each day's GenAI brief (logged in Notion) into a podcast episode.
See the PRD for the full plan. **Status: Phases 1-3 built (script, audio, feed + hosting); automation still to come.**

## Try it

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cp .env.example .env          # then paste your NOTION_TOKEN
.venv/bin/python -m brief --date 2026-10-15 --dry-run
```

`--dry-run` prints exactly what would be spoken, plus the show notes. It never
calls ElevenLabs, so it costs nothing. No Notion token yet? Try the offline
sample: `--from-json tests/fixtures/items.json`.

## Notion setup (once)
1. notion.so/profile/integrations → New internal integration → copy the token into `.env`.
2. Open the "GenAI Daily Brief Log" database → ••• → Connections → add the integration.
3. Phase 0 must be done: the database needs a `Brief text` property.
   Rows without it fall back to the first paragraph of the page body.

## Tweaking
Everything adjustable is in `config.yaml` (time zone, Notion property names,
pause style, intro/outro wording). If Notion calls fail with a "database vs data
source" error, switch `notion.query_mode` / `api_version` there.

## Tests
`.venv/bin/pytest`

## Making audio (spends ElevenLabs credits)
```bash
.venv/bin/python -m brief --check-budget            # free: shows remaining credits
.venv/bin/python -m brief --date 2026-10-16         # writes out/2026-10-16.mp3
```
The run stops, without spending anything, if the credits left are less than the
script length x the model's cost x 1.1. Change the voice or model in
`config.yaml` (`tts.voice_id`, `tts.model_id`, `tts.cost_multiplier`).
Your ElevenLabs key needs *Text to Speech: Access* and *User: Read*.

## Publishing the feed
```bash
# reuse an MP3 you already made (spends no credits), build the site folder locally:
.venv/bin/python -m brief --date 2026-10-16 --audio out/2026-10-16-eleven_multilingual_v2.mp3 --publish
# ...and also push it live to the gh-pages branch (needs GITHUB_TOKEN with write access):
.venv/bin/python -m brief --date 2026-10-16 --audio out/<file>.mp3 --publish --push
```
The feed lives at https://nsuurmey.github.io/daily-ai-reports/feed.xml once
Settings -> Pages is set to the `gh-pages` branch. The last 30 episodes are
kept, and `gh-pages` is rewritten as a single commit each time so audio never
piles up in git history. The cover art is `assets/cover.png`
(regenerate with `python tools/make_cover.py`, needs `pip install pillow`).
