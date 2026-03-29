#!/usr/bin/env python
"""Fetch episode titles from all discovered seasons in a Bilibili bangumi series."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

API_SEASON_URL = "https://api.bilibili.com/pgc/view/web/season"
DEFAULT_BANGUMI_URL = "https://www.bilibili.com/bangumi/play/ss25469"
DEFAULT_TITLES_TEMPLATE = Path(__file__).with_name("titles.json")


@dataclass
class EpisodeRecord:
    season_id: int
    season_title: str
    section_title: str
    ep_id: int
    ep_no: str
    title: str
    long_title: str
    full_title: str
    link: str


def parse_season_id(value: str) -> int:
    value = value.strip()
    if value.isdigit():
        return int(value)

    ss_match = re.search(r"ss(\d+)", value)
    if ss_match:
        return int(ss_match.group(1))

    parsed = urlparse(value)
    if parsed.query:
        q_match = re.search(r"(?:^|&)season_id=(\d+)(?:&|$)", parsed.query)
        if q_match:
            return int(q_match.group(1))

    raise ValueError(f"Cannot parse season id from input: {value}")


class BiliClient:
    def __init__(self, referer_url: str, timeout: int = 20, retry: int = 3) -> None:
        self.timeout = timeout
        self.retry = retry
        self.session = requests.Session()
        self.session.headers.update(
            {
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                "referer": referer_url,
                "origin": "https://www.bilibili.com",
                "accept": "application/json, text/plain, */*",
            }
        )

    def get_season(self, season_id: int) -> dict[str, Any]:
        params = {"season_id": season_id}
        last_error: Exception | None = None

        for idx in range(1, self.retry + 1):
            try:
                response = self.session.get(API_SEASON_URL, params=params, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                if payload.get("code") != 0:
                    raise RuntimeError(
                        f"API returned code={payload.get('code')} message={payload.get('message')}"
                    )
                result = payload.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError("Unexpected payload: missing result object")
                return result
            except Exception as exc:  # pylint: disable=broad-except
                last_error = exc
                if idx < self.retry:
                    time.sleep(1.2 * idx)
                else:
                    break

        raise RuntimeError(f"Failed to fetch season_id={season_id}: {last_error}") from last_error


def build_full_title(ep_no: str, long_title: str) -> str:
    number = ep_no.strip()
    detail = long_title.strip()
    if number and detail:
        return f"Episode {number}: {detail}"
    return detail or number


def should_use_titles_template(input_value: str) -> bool:
    value = input_value.strip()
    if not value.startswith(("http://", "https://")):
        return False

    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if host not in {"www.bilibili.com", "bilibili.com"}:
        return False

    return parsed.path.rstrip("/") == "/bangumi/play/ss25469"


def extract_episodes(season_data: dict[str, Any], include_section: bool = False) -> list[EpisodeRecord]:
    season_id = int(season_data.get("season_id", 0))
    season_title = str(season_data.get("season_title", "")).strip()
    rows: list[EpisodeRecord] = []

    for ep in season_data.get("episodes", []) or []:
        ep_no = str(ep.get("title", "")).strip()
        long_title = str(ep.get("long_title", "")).strip()
        rows.append(
            EpisodeRecord(
                season_id=season_id,
                season_title=season_title,
                section_title="main",
                ep_id=int(ep.get("ep_id") or ep.get("id") or 0),
                ep_no=ep_no,
                title=ep_no,
                long_title=long_title,
                full_title=build_full_title(ep_no, long_title),
                link=str(ep.get("link", "")),
            )
        )

    if include_section:
        for sec in season_data.get("section", []) or []:
            sec_title = str(sec.get("title", "")).strip() or "section"
            for ep in sec.get("episodes", []) or []:
                ep_no = str(ep.get("title", "")).strip()
                long_title = str(ep.get("long_title", "")).strip()
                rows.append(
                    EpisodeRecord(
                        season_id=season_id,
                        season_title=season_title,
                        section_title=sec_title,
                        ep_id=int(ep.get("ep_id") or ep.get("id") or 0),
                        ep_no=ep_no,
                        title=ep_no,
                        long_title=long_title,
                        full_title=build_full_title(ep_no, long_title),
                        link=str(ep.get("link", "")),
                    )
                )

    return rows


def save_json(records: list[EpisodeRecord], path: Path, use_template: bool = False) -> None:
    template_books: list[dict[str, Any]] = []
    if use_template and DEFAULT_TITLES_TEMPLATE.exists():
        try:
            template_payload = json.loads(DEFAULT_TITLES_TEMPLATE.read_text(encoding="utf-8"))
            books_value = template_payload.get("books", template_payload.get("episodes", []))
            if isinstance(books_value, list):
                template_books = [b for b in books_value if isinstance(b, dict)]
        except Exception:
            template_books = []

    books: list[dict[str, Any]] = []
    group_index: dict[tuple[int, str], int] = {}

    for record in records:
        group_key = (record.season_id, record.season_title)
        if group_key not in group_index:
            idx = len(books)
            group_index[group_key] = idx
            template_title = ""
            if idx < len(template_books):
                template_title = str(template_books[idx].get("title", "")).strip()
            title = record.season_title.strip() or template_title or f"Book {idx + 1}"
            books.append({"title": title, "chapters": []})

        idx = group_index[group_key]
        chapter = record.long_title.strip() or record.full_title.strip() or record.ep_no.strip()
        if not chapter and idx < len(template_books):
            template_chapters = template_books[idx].get("chapters", [])
            if isinstance(template_chapters, list):
                chapter_idx = len(books[idx]["chapters"])
                if chapter_idx < len(template_chapters):
                    chapter = str(template_chapters[chapter_idx]).strip()
        books[idx]["chapters"].append(chapter)

    # Force first 5 groups to use template titles and template chapter counts.
    for idx in range(min(5, len(books), len(template_books))):
        template_title = str(template_books[idx].get("title", "")).strip()
        if template_title:
            books[idx]["title"] = template_title

        template_chapters = template_books[idx].get("chapters", [])
        if not isinstance(template_chapters, list):
            continue

        current_chapters = books[idx]["chapters"]
        adjusted_chapters: list[str] = []
        for chapter_idx, template_value in enumerate(template_chapters):
            website_value = (
                str(current_chapters[chapter_idx]).strip()
                if chapter_idx < len(current_chapters)
                else ""
            )
            template_fallback = str(template_value).strip()
            adjusted_chapters.append(website_value or template_fallback)
        books[idx]["chapters"] = adjusted_chapters

    payload = {"episodes": books}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_csv(records: list[EpisodeRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(EpisodeRecord.__annotations__.keys()))
        writer.writeheader()
        writer.writerows([r.__dict__ for r in records])


def discover_all_seasons(client: BiliClient, root_season_id: int) -> dict[int, dict[str, Any]]:
    """
    Discover all season ids connected via each season's `seasons` list.
    This avoids any fixed count (for example 12 seasons) and auto-expands when new seasons appear.
    """
    queue: deque[int] = deque([root_season_id])
    seen: set[int] = set()
    season_map: dict[int, dict[str, Any]] = {}

    while queue:
        sid = queue.popleft()
        if sid in seen:
            continue
        seen.add(sid)

        data = client.get_season(sid)
        season_map[sid] = data

        for season in data.get("seasons", []) or []:
            next_sid = int(season.get("season_id", 0))
            if next_sid > 0 and next_sid not in seen:
                queue.append(next_sid)

    return season_map


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch all episode titles for all discovered seasons in a Bilibili bangumi series."
    )
    parser.add_argument(
        "-u",
        "--url",
        default=DEFAULT_BANGUMI_URL,
        help=(
            "Bilibili bangumi page URL or season_id. "
            f"Default: {DEFAULT_BANGUMI_URL}"
        ),
    )
    parser.add_argument("--include-section", action="store_true", help="Include extras from section list.")
    parser.add_argument("--json", default="episode_titles.json", help="Output JSON path.")
    parser.add_argument(
        "--csv",
        default=None,
        help="Optional CSV output path. Disabled by default.",
    )
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds.")
    parser.add_argument("--retry", type=int, default=3, help="Retry count for each request.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_value = args.url
    root_season_id = parse_season_id(input_value)
    referer = (
        input_value
        if input_value.startswith("http://") or input_value.startswith("https://")
        else f"https://www.bilibili.com/bangumi/play/ss{root_season_id}"
    )

    client = BiliClient(referer_url=referer, timeout=args.timeout, retry=args.retry)
    season_map = discover_all_seasons(client, root_season_id)
    sorted_ids = sorted(season_map.keys())
    use_template = should_use_titles_template(input_value)

    all_records: list[EpisodeRecord] = []
    print(f"Discovered {len(sorted_ids)} seasons from root season_id={root_season_id}.")

    for sid in sorted_ids:
        data = season_map[sid]
        rows = extract_episodes(data, include_section=args.include_section)
        all_records.extend(rows)
        print(
            f"- season_id={sid:<6} "
            f"season_title={data.get('season_title', '')} "
            f"episodes={len(data.get('episodes', []))}"
        )

    json_path = Path(args.json)
    csv_path = Path(args.csv) if args.csv else None
    json_path.parent.mkdir(parents=True, exist_ok=True)
    save_json(all_records, json_path, use_template=use_template)
    if csv_path is not None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        save_csv(all_records, csv_path)

    print(f"\nTotal records: {len(all_records)}")
    print(f"JSON saved: {json_path.resolve()}")
    if csv_path is not None:
        print(f"CSV  saved: {csv_path.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as err:  # pylint: disable=broad-except
        print(f"ERROR: {err}", file=sys.stderr)
        raise SystemExit(1) from err
