"""Fetch one day's brief rows from the Notion log database."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import requests

API = "https://api.notion.com/v1"


@dataclass
class Item:
    insight: str
    type: str = ""
    evidence: str = ""
    domain: str = ""
    brief_text: str = ""
    source: str = ""
    page_id: str = ""


@dataclass
class Fetched:
    items: list[Item] = field(default_factory=list)


def _plain(rich: list[dict]) -> str:
    return "".join(t.get("plain_text", "") for t in rich or [])


def prop_text(prop: dict | None) -> str:
    """Flatten any Notion property value to plain text."""
    if not prop:
        return ""
    kind = prop.get("type")
    val = prop.get(kind)
    if val is None:
        return ""
    if kind in ("title", "rich_text"):
        return _plain(val)
    if kind in ("select", "status"):
        return val.get("name", "")
    if kind == "multi_select":
        return ", ".join(o.get("name", "") for o in val)
    if kind in ("url", "email", "phone_number"):
        return val or ""
    if kind == "number":
        return str(val)
    if kind == "date":
        return val.get("start", "")
    if kind == "formula":
        inner = val.get(val.get("type"))
        return "" if inner is None else str(inner)
    return ""


def page_to_item(page: dict, props: dict[str, str], body_fallback: str = "") -> Item:
    p = page.get("properties", {})
    brief = prop_text(p.get(props["brief_text"])).strip() or body_fallback.strip()
    return Item(
        insight=prop_text(p.get(props["insight"])).strip(),
        type=prop_text(p.get(props["type"])).strip(),
        evidence=prop_text(p.get(props["evidence"])).strip(),
        domain=prop_text(p.get(props["domain"])).strip(),
        brief_text=brief,
        source=prop_text(p.get(props["source"])).strip(),
        page_id=page.get("id", ""),
    )


def first_paragraph(blocks: list[dict]) -> str:
    for b in blocks:
        if b.get("type") == "paragraph":
            text = _plain(b["paragraph"].get("rich_text"))
            if text.strip():
                return text
    return ""


class NotionClient:
    def __init__(self, token: str, api_version: str, session: requests.Session | None = None):
        self.s = session or requests.Session()
        self.s.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": api_version,
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, url: str, **kw) -> dict:
        for attempt in range(4):
            r = self.s.request(method, url, timeout=30, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            if not r.ok:
                # Notion error bodies never contain the token.
                raise RuntimeError(f"Notion {method} {url} -> {r.status_code}: {r.text[:500]}")
            return r.json()
        raise RuntimeError(f"Notion {method} {url} kept failing after retries")

    def query_day(self, cfg: dict, date_iso: str) -> list[dict]:
        n = cfg["notion"]
        if n["query_mode"] == "data_source":
            url = f"{API}/data_sources/{n['data_source_id']}/query"
        else:
            url = f"{API}/databases/{n['database_id']}/query"
        body = {
            "filter": {"property": n["properties"]["date"], "date": {"equals": date_iso}},
            "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
            "page_size": 100,
        }
        pages: list[dict] = []
        while True:
            data = self._request("POST", url, json=body)
            pages.extend(data["results"])
            if not data.get("has_more"):
                return pages
            body["start_cursor"] = data["next_cursor"]

    def body_first_paragraph(self, page_id: str) -> str:
        data = self._request("GET", f"{API}/blocks/{page_id}/children", params={"page_size": 25})
        return first_paragraph(data["results"])


def fetch_items(cfg: dict, token: str, date_iso: str) -> list[Item]:
    client = NotionClient(token, cfg["notion"]["api_version"])
    props = cfg["notion"]["properties"]
    items = []
    for page in client.query_day(cfg, date_iso):
        item = page_to_item(page, props)
        if not item.brief_text:  # pre-Phase-0 rows: fall back to the page body
            item.brief_text = client.body_first_paragraph(page["id"]).strip()
        items.append(item)
    return items
