"""Deterministic spoken-script and show-notes builder. Pure functions, no I/O, no LLM."""
from __future__ import annotations

import datetime as dt
import html
import re

from .fetch_notion import Item

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_ORD_IRREGULAR = {"one": "first", "two": "second", "three": "third", "five": "fifth",
                  "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}


def number_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] + (f"-{_ONES[o]}" if o else "")
    return str(n)  # briefs never get here


def ordinal_words(n: int) -> str:
    words = number_words(n)
    head, sep, last = words.rpartition("-")
    if last in _ORD_IRREGULAR:
        last = _ORD_IRREGULAR[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    elif last.endswith("t") and last in ("eight",):
        last += "h"
    else:
        last += "th"
    return head + sep + last


# --- cleanup -----------------------------------------------------------------

_REPLACEMENTS = [
    (re.compile(r"\bw/(?=\s|$)"), "with"),
    (re.compile(r"\be\.g\.,?", re.I), "for example,"),
    (re.compile(r"\bi\.e\.,?", re.I), "that is,"),
    (re.compile(r"\bvs\.?(?=\s)", re.I), "versus"),
    (re.compile(r"~\s*"), "about "),
    (re.compile(r"\s*%"), " percent"),
]


def clean_text(text: str) -> str:
    """Make text safe to read aloud: no markdown, URLs or symbols."""
    t = text or ""
    t = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", t)        # images
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)          # [text](url) -> text
    t = re.sub(r"https?://\S+|www\.\S+", "", t)              # bare URLs
    t = re.sub(r"`+", "", t)
    t = re.sub(r"(\*\*|__)(.+?)\1", r"\2", t)
    t = re.sub(r"(?<!\w)[*_](\S.*?)[*_](?!\w)", r"\1", t)
    t = t.replace("*", "")
    t = re.sub(r"^\s{0,3}(#{1,6}|[-+•]|\d+\.)\s+", "", t, flags=re.M)  # headings/bullets
    for pattern, repl in _REPLACEMENTS:
        t = pattern.sub(repl, t)
    t = re.sub(r"\(\s*\)", "", t)                            # parens emptied by URL removal
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s*\n\s*", " ", t)
    return t.strip()


def _sentence(text: str) -> str:
    """Ensure text ends in terminal punctuation (without doubling it up)."""
    text = text.strip()
    if not text:
        return ""
    return text if text[-1] in ".!?" else text + "."


# --- script ------------------------------------------------------------------

def count_phrase(n: int) -> str:
    if n <= 0:
        return "No items today."
    if n <= 2:
        return f"Just {number_words(n)} today. A thin day."
    return f"{number_words(n).capitalize()} items today."


def intro(date: dt.date, n: int, template: str) -> str:
    return template.format(
        weekday=date.strftime("%A"),
        month=date.strftime("%B"),
        day_ordinal=ordinal_words(date.day),
        count_phrase=count_phrase(n),
    )


def item_block(index: int, item: Item) -> str:
    lines = [f"Item {number_words(index)}. {_sentence(clean_text(item.insight))}"]
    meta = [clean_text(x) for x in (item.type, item.evidence)]
    meta = [m for m in meta if m]
    domain = clean_text(item.domain)
    line = ", ".join(meta)
    if domain:
        line = f"{line}, from {domain}" if line else f"From {domain}"
    if line:
        lines.append(_sentence(line))
    body = _sentence(clean_text(item.brief_text))
    if body:
        lines.append(body)
    return "\n".join(lines)


def pause(style: str, seconds: float) -> str:
    if style == "break_tag":
        return f'\n<break time="{seconds:g}s" />\n'
    return "\n\n"


def build_script(date: dt.date, items: list[Item], script_cfg: dict) -> str:
    sep = pause(script_cfg.get("pause_style", "paragraph"), script_cfg.get("pause_seconds", 1.5))
    parts = [intro(date, len(items), script_cfg["intro_template"])]
    parts += [item_block(i, it) for i, it in enumerate(items, 1)]
    parts.append(script_cfg["outro"])
    return sep.join(p.strip() for p in parts) + "\n"


# --- show notes --------------------------------------------------------------

def build_show_notes(date: dt.date, items: list[Item]) -> str:
    esc = html.escape
    out = [f"<p>GenAI brief for {esc(date.strftime('%A, %B'))} {date.day}.</p>", "<ol>"]
    for it in items:
        title = esc(clean_text(it.insight))
        head = f'<a href="{esc(it.source, quote=True)}">{title}</a>' if it.source else title
        meta = " · ".join(esc(x) for x in (it.type, it.evidence, it.domain) if x)
        out.append(f"<li><strong>{head}</strong>" + (f"<br/>{meta}" if meta else "") + "</li>")
    out.append("</ol>")
    return "\n".join(out)
