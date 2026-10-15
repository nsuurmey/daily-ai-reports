# GenAI Daily Brief → Private Podcast

Turns each day's GenAI brief (logged in Notion) into a podcast episode.
See the PRD for the full plan. **Status: Phase 1 (fetch + script, no audio).**

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
