"""Fixed synthetic HTTP fixtures for the four selected sources; never used in live mode."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from pydantic import JsonValue, TypeAdapter

from .local_sources import obj
from .models import RetrievalFailure
from .web_transport import WebPage


class FixtureWebClient:
    def __init__(self, path: Path) -> None:
        self.data = TypeAdapter(dict[str, JsonValue]).validate_json(
            path.read_text(encoding="utf-8")
        )

    async def request_async(
        self,
        url: str,
        *,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> WebPage:
        parts = urlsplit(url)
        if parts.path in self.data:
            value = self.data[parts.path]
        elif "/search/positions" in url:
            value = self.data["zhaopin"]
        elif "pc-search-job" in url:
            value = self.data["liepin"]
        elif "jobsearch/v5/search" in url:
            value = self.data["jobsdb"]
        elif parts.path == "/interns":
            value = self.data["shixiseng"]
        else:
            raise RetrievalFailure("SEARCH_RESPONSE_FORMAT", "No synthetic fixture for this URL.")
        query = (
            json.dumps(body, ensure_ascii=False)
            if body
            else str(
                parse_qs(parts.query).get("keywords", parse_qs(parts.query).get("keyword", []))
            )
        )
        direction = (
            "Business Analyst"
            if "商业分析" in query or "Business Analyst" in query
            else "Data Analyst"
        )
        if parts.path not in self.data:
            # Simulate the website's keyword search over test records.
            value = json.loads(json.dumps(value))
            if isinstance(value, dict):
                if "zhaopin" in parts.netloc:
                    container, key = obj(value.get("data")), "list"
                elif "liepin" in parts.netloc:
                    container, key = obj(obj(value.get("data")).get("data")), "jobCardList"
                else:
                    container, key = value, "data"
                records = container.get(key)
                if isinstance(records, list):
                    container[key] = [r for r in records if direction in json.dumps(r)]
            elif isinstance(value, str):
                word = "商业分析" if direction == "Business Analyst" else "数据分析"
                value = "".join(
                    card
                    for card in re.findall(r"<div class=\"intern-wrap\".*?</div>", value)
                    if word in card
                )
        number = parse_qs(parts.query).get("page", ["1"])[0]
        if number != "1" and parts.path == "/interns":
            value = "<main>暂无相关职位</main>"
        elif number != "1" and "jobsearch" in parts.path:
            value = {"data": []}
        # Other fixtures repeat page 1 deliberately to exercise repeat protection.
        return WebPage(
            value if isinstance(value, str) else json.dumps(value),
            datetime(2026, 10, 1, tzinfo=UTC),
        )
