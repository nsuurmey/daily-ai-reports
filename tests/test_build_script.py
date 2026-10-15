import datetime as dt
import json
from pathlib import Path

from brief.build_script import (build_script, build_show_notes, clean_text,
                                count_phrase, number_words, ordinal_words)
from brief.fetch_notion import Item, first_paragraph, page_to_item, prop_text

CFG = {
    "pause_style": "break_tag", "pause_seconds": 1.5,
    "intro_template": "GenAI brief for {weekday}, {month} {day_ordinal}. {count_phrase}",
    "outro": "That's the brief. Sources are in the show notes.",
}
ITEMS = [Item(**r) for r in json.loads((Path(__file__).parent / "fixtures/items.json").read_text())]
D = dt.date(2026, 10, 15)


def test_ordinals():
    assert [ordinal_words(n) for n in (1, 2, 3, 5, 8, 9, 12, 15, 20, 21, 22, 30, 31)] == [
        "first", "second", "third", "fifth", "eighth", "ninth", "twelfth", "fifteenth",
        "twentieth", "twenty-first", "twenty-second", "thirtieth", "thirty-first"]
    assert number_words(4) == "four"


def test_count_phrase():
    assert count_phrase(4) == "Four items today."
    assert count_phrase(1) == "Just one today. A thin day."
    assert count_phrase(2) == "Just two today. A thin day."


def test_clean_text():
    out = clean_text("**Bold** and `code` [link](https://a.b/c) see https://x.y ~50% vs. old, e.g. RAG w/ tools")
    assert "http" not in out and "*" not in out and "`" not in out and "[" not in out
    assert out == "Bold and code link see about 50 percent versus old, for example, RAG with tools"


def test_script_full():
    s = build_script(D, ITEMS, CFG)
    assert s.startswith("GenAI brief for Thursday, October fifteenth. Three items today.")
    assert s.index("Item one.") < s.index("Item two.") < s.index("Item three.")
    assert s.count('<break time="1.5s" />') == 4  # intro|1|2|3|outro
    assert "Item two. A study finds LLM judges drift with long contexts." in s  # no doubled period
    assert "Research, Peer-reviewed, from Evaluation." in s
    assert "Agreement with humans fell 12 percent past 32k tokens." in s
    assert "http" not in s and "**" not in s
    assert s.rstrip().endswith("Sources are in the show notes.")


def test_script_thin_day_and_paragraph_style():
    cfg = {**CFG, "pause_style": "paragraph"}
    s = build_script(D, ITEMS[:1], cfg)
    assert "Just one today. A thin day." in s
    assert "<break" not in s and "\n\n" in s


def test_show_notes_links_and_escaping():
    n = build_show_notes(D, ITEMS)
    assert '<a href="https://example.com/docs?a=1&amp;b=2">' in n
    assert "Tooling · Vendor docs · Cost optimization" in n
    assert "<a" not in n.split("Open-weights")[1].split("</li>")[0]  # no source -> no link


def test_prop_text_variants():
    assert prop_text({"type": "title", "title": [{"plain_text": "A"}, {"plain_text": "B"}]}) == "AB"
    assert prop_text({"type": "select", "select": {"name": "X"}}) == "X"
    assert prop_text({"type": "select", "select": None}) == ""
    assert prop_text({"type": "multi_select", "multi_select": [{"name": "a"}, {"name": "b"}]}) == "a, b"
    assert prop_text({"type": "url", "url": "https://z"}) == "https://z"
    assert prop_text(None) == ""


def test_page_to_item_and_body_fallback():
    props = {"insight": "Insight", "type": "Type", "evidence": "Evidence", "domain": "Domain",
             "brief_text": "Brief text", "source": "Source"}
    page = {"id": "abc", "properties": {
        "Insight": {"type": "title", "title": [{"plain_text": "Head"}]},
        "Brief text": {"type": "rich_text", "rich_text": []},
        "Source": {"type": "url", "url": "https://s"}}}
    it = page_to_item(page, props, body_fallback="Body para.")
    assert (it.insight, it.brief_text, it.source) == ("Head", "Body para.", "https://s")
    blocks = [{"type": "heading_2", "heading_2": {}},
              {"type": "paragraph", "paragraph": {"rich_text": []}},
              {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "First."}]}}]
    assert first_paragraph(blocks) == "First."


def test_show_notes_headline_is_clean():
    n = build_show_notes(D, ITEMS)
    assert "**" not in n and "w/" not in n
