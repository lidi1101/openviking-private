# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import os
from typing import Any

import httpx

INFO_URI = "viking://yoyo/userinformation/default/userinformation.jsonl"
TENDENCY_URI = "viking://yoyo/usertendencies/default/usertendencies.jsonl"
INFO_SOURCE = "userinformation"
TENDENCY_SOURCE = "usertendencies"

KEYWORD_NAME = "\u738b\u4e3d"
KEYWORD_WEDNESDAY = "\u665a\u8bfe"
KEYWORD_COFFEE = "\u65e0\u7cd6\u5496\u5561"
KEYWORD_MUSIC = "\u6d41\u884c\u97f3\u4e50"


def step(number: int, title: str) -> None:
    print(f"\n=== Step {number}: {title} ===", flush=True)


def info(message: str) -> None:
    print(f"INFO  {message}", flush=True)


def passed(message: str) -> None:
    print(f"PASS  {message}", flush=True)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        items.append(json.loads(raw))
    return items


def first_title(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    attrs = items[0].get("attrs")
    if isinstance(attrs, dict):
        title = str(attrs.get("title", "")).strip()
        if title:
            return title
    return str(items[0].get("text", "")).strip()


class QueryVerifier:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.headers = {}
        if args.api_key:
            self.headers["Authorization"] = f"Bearer {args.api_key}"

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with httpx.Client(base_url=self.args.base_url, headers=self.headers, timeout=120.0) as client:
            response = client.get(path, params=params)
            response.raise_for_status()
            return response.json()

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(base_url=self.args.base_url, headers=self.headers, timeout=120.0) as client:
            response = client.post(path, json=body)
            response.raise_for_status()
            return response.json()

    def validate_query_api(self, expected_counts: dict[str, int]) -> dict[str, Any]:
        sources_resp = self.get("/api/v1/localdb/sources", {"user_space": self.args.user_space})
        sources = sources_resp.get("result") or []

        info_all = (
            self.post(
                "/api/v1/localdb/query",
                {
                    "user_space": self.args.user_space,
                    "source": INFO_SOURCE,
                    "limit": max(expected_counts[INFO_SOURCE], 1),
                },
            ).get("result")
            or {}
        )
        tendency_all = (
            self.post(
                "/api/v1/localdb/query",
                {
                    "user_space": self.args.user_space,
                    "source": TENDENCY_SOURCE,
                    "limit": max(expected_counts[TENDENCY_SOURCE], 1),
                },
            ).get("result")
            or {}
        )
        name_hit = (
            self.post(
                "/api/v1/localdb/query",
                {
                    "user_space": self.args.user_space,
                    "source": INFO_SOURCE,
                    "event_types": ["yoyo_user_information"],
                    "keyword": KEYWORD_NAME,
                    "limit": 3,
                    "include_evidence": False,
                },
            ).get("result")
            or {}
        )
        wednesday_hit = (
            self.post(
                "/api/v1/localdb/query",
                {
                    "user_space": self.args.user_space,
                    "source": INFO_SOURCE,
                    "event_types": ["yoyo_user_information"],
                    "keyword": KEYWORD_WEDNESDAY,
                    "limit": 3,
                },
            ).get("result")
            or {}
        )
        coffee_hit = (
            self.post(
                "/api/v1/localdb/query",
                {
                    "user_space": self.args.user_space,
                    "source": TENDENCY_SOURCE,
                    "event_types": ["yoyo_user_tendency"],
                    "keyword": KEYWORD_COFFEE,
                    "limit": 3,
                },
            ).get("result")
            or {}
        )
        music_hit = (
            self.post(
                "/api/v1/localdb/query",
                {
                    "user_space": self.args.user_space,
                    "source": TENDENCY_SOURCE,
                    "event_types": ["yoyo_user_tendency"],
                    "keyword": KEYWORD_MUSIC,
                    "limit": 3,
                },
            ).get("result")
            or {}
        )

        coffee_items = coffee_hit.get("items") or []
        coffee_full = None
        if coffee_items:
            coffee_full = self.get(
                "/api/v1/localdb/event",
                {
                    "user_space": self.args.user_space,
                    "source": TENDENCY_SOURCE,
                    "event_id": coffee_items[0]["id"],
                },
            ).get("result")

        return {
            "sources": sources,
            "info_total": int(info_all.get("total", 0)),
            "tendency_total": int(tendency_all.get("total", 0)),
            "name_total": int(name_hit.get("total", 0)),
            "name_items": name_hit.get("items") or [],
            "name_types": [item.get("type") for item in (name_hit.get("items") or [])],
            "name_evidence": [item.get("evidence") for item in (name_hit.get("items") or [])],
            "wednesday_total": int(wednesday_hit.get("total", 0)),
            "wednesday_items": wednesday_hit.get("items") or [],
            "coffee_total": int(coffee_hit.get("total", 0)),
            "coffee_items": coffee_items,
            "coffee_types": [item.get("type") for item in coffee_items],
            "music_total": int(music_hit.get("total", 0)),
            "music_items": music_hit.get("items") or [],
            "music_types": [item.get("type") for item in (music_hit.get("items") or [])],
            "coffee_full_id": str((coffee_full or {}).get("id", "")),
            "coffee_full_text": str((coffee_full or {}).get("text", "")),
        }

    def run(self) -> None:
        step(1, "Health Check")
        health = self.get("/health")
        assert_true(health.get("status") == "ok", "Health check did not return status=ok.")
        passed(f"Health endpoint returned status=ok at {self.args.base_url}")

        step(2, "Read Raw YOYO JSONL")
        expected_counts: dict[str, int] = {}
        for source, uri in [(INFO_SOURCE, INFO_URI), (TENDENCY_SOURCE, TENDENCY_URI)]:
            response = self.get("/api/v1/content/read", {"uri": uri, "offset": 0, "limit": self.args.read_limit})
            content = str(response.get("result", ""))
            items = parse_jsonl(content)
            assert_true(items, f"{uri} returned no parsed JSONL rows.")
            expected_counts[source] = len(items)
            passed(f"{source}: rows={len(items)}")

        step(3, "Validate openviking.db.query")
        query_result = self.validate_query_api(expected_counts)

        info(f"sources={query_result['sources']}")
        info(
            f"totals: {INFO_SOURCE}={query_result['info_total']}, "
            f"{TENDENCY_SOURCE}={query_result['tendency_total']}"
        )
        info(f"hit[{KEYWORD_NAME}]={query_result['name_total']} first={first_title(query_result['name_items'])}")
        info(
            f"hit[{KEYWORD_WEDNESDAY}]={query_result['wednesday_total']} "
            f"first={first_title(query_result['wednesday_items'])}"
        )
        info(
            f"hit[{KEYWORD_COFFEE}]={query_result['coffee_total']} "
            f"first={first_title(query_result['coffee_items'])}"
        )
        info(
            f"hit[{KEYWORD_MUSIC}]={query_result['music_total']} "
            f"first={first_title(query_result['music_items'])}"
        )
        if query_result["coffee_full_id"]:
            info(f"get_event id={query_result['coffee_full_id']} text={query_result['coffee_full_text']}")

        assert_true(INFO_SOURCE in query_result["sources"], f"list_sources did not contain {INFO_SOURCE}")
        assert_true(
            TENDENCY_SOURCE in query_result["sources"],
            f"list_sources did not contain {TENDENCY_SOURCE}",
        )
        assert_true(
            query_result["info_total"] == expected_counts[INFO_SOURCE],
            f"{INFO_SOURCE} total mismatch: expected {expected_counts[INFO_SOURCE]}, actual {query_result['info_total']}",
        )
        assert_true(
            query_result["tendency_total"] == expected_counts[TENDENCY_SOURCE],
            f"{TENDENCY_SOURCE} total mismatch: expected {expected_counts[TENDENCY_SOURCE]}, actual {query_result['tendency_total']}",
        )
        assert_true(query_result["name_total"] >= 1, f'query_events(keyword="{KEYWORD_NAME}") returned no hits.')
        assert_true(
            query_result["wednesday_total"] >= 1,
            f'query_events(keyword="{KEYWORD_WEDNESDAY}") returned no hits.',
        )
        assert_true(
            query_result["coffee_total"] >= 1,
            f'query_events(keyword="{KEYWORD_COFFEE}") returned no hits.',
        )
        assert_true(
            query_result["music_total"] >= 1,
            f'query_events(keyword="{KEYWORD_MUSIC}") returned no hits.',
        )
        assert_true(
            sorted(set(query_result["name_types"])) == ["yoyo_user_information"],
            f"{KEYWORD_NAME} hits were not all yoyo_user_information.",
        )
        assert_true(
            sorted(set(query_result["coffee_types"])) == ["yoyo_user_tendency"],
            f"{KEYWORD_COFFEE} hits were not all yoyo_user_tendency.",
        )
        assert_true(
            sorted(set(query_result["music_types"])) == ["yoyo_user_tendency"],
            f"{KEYWORD_MUSIC} hits were not all yoyo_user_tendency.",
        )
        assert_true(
            all(not evidence for evidence in query_result["name_evidence"]),
            f"include_evidence=False did not strip evidence from {KEYWORD_NAME} hits.",
        )
        assert_true(
            query_result["coffee_full_id"] != "",
            f"get_event returned no record for {KEYWORD_COFFEE} hit.",
        )
        assert_true(
            KEYWORD_COFFEE in query_result["coffee_full_text"],
            f"get_event result text did not contain {KEYWORD_COFFEE}.",
        )
        passed(
            "db.query validated: "
            f"info_total={query_result['info_total']}, "
            f"tendency_total={query_result['tendency_total']}, "
            f"coffee_total={query_result['coffee_total']}, "
            f"music_total={query_result['music_total']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify OpenViking LocalDB query chain for the fixed YOYO JSONL files."
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:1933",
        help="OpenViking server base url",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENVIKING_API_KEY"),
        help="API key (or set env OPENVIKING_API_KEY)",
    )
    parser.add_argument(
        "--user-space",
        default="default/default",
        help="User space passed into localdb query APIs",
    )
    parser.add_argument(
        "--read-limit",
        type=int,
        default=200000,
        help="Byte limit passed to /api/v1/content/read",
    )

    args = parser.parse_args()
    QueryVerifier(args).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
