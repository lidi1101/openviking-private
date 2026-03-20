# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from typing import Any

import httpx

YOYO_INFO_URI = "viking://yoyo/userinformation/default/userinformation.jsonl"
YOYO_TENDENCY_URI = "viking://yoyo/usertendencies/default/usertendencies.jsonl"


@dataclass(frozen=True)
class SemanticCheck:
    source: str
    keyword: str
    event_types: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QuerySourceCase:
    source: str
    uri: str


@dataclass(frozen=True)
class QueryProfile:
    name: str
    sources: list[QuerySourceCase]
    semantic_checks: list[SemanticCheck] = field(default_factory=list)


def _build_user_uri(user_space: str, source: str) -> str:
    return f"viking://user/{user_space}/memories/localdb/{source}/events.jsonl"


def _build_profile(profile: str, user_space: str, source_override: str | None) -> QueryProfile:
    if profile == "yoyo":
        return QueryProfile(
            name="yoyo",
            sources=[
                QuerySourceCase(source="userinformation", uri=YOYO_INFO_URI),
                QuerySourceCase(source="usertendencies", uri=YOYO_TENDENCY_URI),
            ],
            semantic_checks=[
                SemanticCheck(
                    source="userinformation",
                    keyword="晚课",
                    event_types=["yoyo_user_information"],
                ),
                SemanticCheck(
                    source="usertendencies",
                    keyword="无糖咖啡",
                    event_types=["yoyo_user_tendency"],
                ),
                SemanticCheck(
                    source="usertendencies",
                    keyword="流行音乐",
                    event_types=["yoyo_user_tendency"],
                ),
            ],
        )

    source = source_override or "user_preference"
    return QueryProfile(
        name="user_preference",
        sources=[QuerySourceCase(source=source, uri=_build_user_uri(user_space, source))],
    )


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


def derive_keyword(item: dict[str, Any]) -> str:
    attrs = item.get("attrs") if isinstance(item.get("attrs"), dict) else {}
    candidates = [
        str(attrs.get("title", "")).strip(),
        str(item.get("text", "")).strip(),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        parts = [part.strip() for part in candidate.split("|") if part.strip()]
        for part in parts:
            if len(part) >= 2:
                return part[:32]
        return candidate[:32]
    return ""


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

    def _query(self, source: str, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "user_space": self.args.user_space,
            "source": source,
            "limit": 10,
        }
        body.update(overrides)
        return self.post("/api/v1/localdb/query", body).get("result") or {}

    def _get_event(self, source: str, event_id: str) -> dict[str, Any] | None:
        return self.get(
            "/api/v1/localdb/event",
            {
                "user_space": self.args.user_space,
                "source": source,
                "event_id": event_id,
            },
        ).get("result")

    def validate_source(self, source_case: QuerySourceCase, expected_items: list[dict[str, Any]]) -> None:
        expected_total = len(expected_items)
        first = expected_items[0]
        first_id = str(first.get("id", ""))
        first_type = str(first.get("type", ""))
        first_text = str(first.get("text", ""))
        keyword = derive_keyword(first)

        all_result = self._query(source_case.source, limit=max(expected_total, 1))
        id_result = self._query(source_case.source, ids=[first_id], limit=1)
        type_result = self._query(source_case.source, event_types=[first_type], limit=3)
        no_evidence_result = self._query(
            source_case.source,
            ids=[first_id],
            include_evidence=False,
            limit=1,
        )
        page_one = self._query(source_case.source, offset=0, limit=1)
        page_two = self._query(source_case.source, offset=1, limit=1) if expected_total > 1 else {}
        keyword_result = self._query(source_case.source, keyword=keyword, limit=3) if keyword else {}
        full = self._get_event(source_case.source, first_id)

        info(
            f"source={source_case.source} total={all_result.get('total', 0)} "
            f"first={first_title(all_result.get('items') or expected_items)}"
        )
        if keyword:
            info(f"source={source_case.source} keyword={keyword!r} hits={keyword_result.get('total', 0)}")

        assert_true(expected_total > 0, f"{source_case.uri} returned no parsed JSONL rows.")
        assert_true(
            int(all_result.get("total", 0)) == expected_total,
            (
                f"{source_case.source} total mismatch: expected {expected_total}, "
                f"actual {all_result.get('total', 0)}"
            ),
        )
        assert_true((all_result.get("items") or []), f"{source_case.source} query returned no items.")
        assert_true(int(id_result.get("total", 0)) >= 1, f"{source_case.source} ids query returned no hits.")
        assert_true(
            str(((id_result.get("items") or [{}])[0]).get("id", "")) == first_id,
            f"{source_case.source} ids query did not return the expected first id.",
        )
        assert_true(
            int(type_result.get("total", 0)) >= 1,
            f"{source_case.source} event_types query returned no hits.",
        )
        assert_true(
            all(str(item.get("type", "")) == first_type for item in (type_result.get("items") or [])),
            f"{source_case.source} event_types filter returned mixed types.",
        )

        no_evidence_items = no_evidence_result.get("items") or []
        assert_true(no_evidence_items, f"{source_case.source} include_evidence=False returned no items.")
        assert_true(
            all(not item.get("evidence") for item in no_evidence_items),
            f"{source_case.source} include_evidence=False did not strip evidence.",
        )

        page_one_items = page_one.get("items") or []
        assert_true(page_one_items, f"{source_case.source} first page was empty.")
        if expected_total > 1:
            page_two_items = page_two.get("items") or []
            assert_true(page_two_items, f"{source_case.source} second page was empty.")
            assert_true(
                str(page_one_items[0].get("id", "")) != str(page_two_items[0].get("id", "")),
                f"{source_case.source} pagination did not advance to a different item.",
            )

        if keyword:
            assert_true(
                int(keyword_result.get("total", 0)) >= 1,
                f"{source_case.source} keyword query returned no hits for {keyword!r}.",
            )

        assert_true(full is not None, f"{source_case.source} get_event returned no record.")
        assert_true(str((full or {}).get("id", "")) == first_id, f"{source_case.source} get_event id mismatch.")
        if first_text:
            assert_true(
                str((full or {}).get("text", "")) == first_text,
                f"{source_case.source} get_event text mismatch.",
            )

        passed(
            f"{source_case.source}: total={expected_total}, type={first_type}, "
            f"keyword={keyword or '<none>'}"
        )

    def validate_semantic_checks(self, profile: QueryProfile) -> None:
        if not profile.semantic_checks:
            return

        step(4, "Validate Profile-Specific Keywords")
        for check in profile.semantic_checks:
            result = self._query(
                check.source,
                keyword=check.keyword,
                event_types=check.event_types,
                limit=3,
            )
            items = result.get("items") or []
            info(f"source={check.source} semantic_keyword={check.keyword!r} hits={result.get('total', 0)}")
            assert_true(
                int(result.get("total", 0)) >= 1,
                f'{check.source} query_events(keyword="{check.keyword}") returned no hits.',
            )
            if check.event_types:
                assert_true(
                    all(str(item.get("type", "")) in set(check.event_types) for item in items),
                    f"{check.source} semantic hits were not all in expected event_types.",
                )
            passed(f"{check.source}: semantic keyword {check.keyword!r} validated")

    def run_profile(self, profile: QueryProfile) -> None:
        step(1, f"Health Check ({profile.name})")
        health = self.get("/health")
        assert_true(health.get("status") == "ok", "Health check did not return status=ok.")
        passed(f"Health endpoint returned status=ok at {self.args.base_url}")

        step(2, f"Read Raw JSONL ({profile.name})")
        raw_items: dict[str, list[dict[str, Any]]] = {}
        for source_case in profile.sources:
            response = self.get(
                "/api/v1/content/read",
                {"uri": source_case.uri, "offset": 0, "limit": self.args.read_limit},
            )
            content = str(response.get("result", ""))
            items = parse_jsonl(content)
            assert_true(items, f"{source_case.uri} returned no parsed JSONL rows.")
            raw_items[source_case.source] = items
            passed(f"{source_case.source}: rows={len(items)} uri={source_case.uri}")

        step(3, f"Validate localdb query APIs ({profile.name})")
        sources_resp = self.get("/api/v1/localdb/sources", {"user_space": self.args.user_space})
        sources = sources_resp.get("result") or []
        info(f"sources={sources}")
        for source_case in profile.sources:
            assert_true(source_case.source in sources, f"list_sources did not contain {source_case.source}")
            self.validate_source(source_case, raw_items[source_case.source])

        self.validate_semantic_checks(profile)


def _resolve_profiles(args: argparse.Namespace) -> list[QueryProfile]:
    if args.profile == "all":
        return [
            _build_profile("yoyo", args.user_space, None),
            _build_profile("user_preference", args.user_space, args.source),
        ]
    return [_build_profile(args.profile, args.user_space, args.source)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify OpenViking LocalDB query chain for built-in profiles. "
            "Use --profile yoyo, --profile user_preference, or --profile all."
        )
    )
    parser.add_argument(
        "--profile",
        choices=["yoyo", "user_preference", "all"],
        default="yoyo",
        help="Built-in query verification profile.",
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
        "--source",
        default=None,
        help="Override source for user_preference profile. Default is user_preference.",
    )
    parser.add_argument(
        "--read-limit",
        type=int,
        default=200000,
        help="Byte limit passed to /api/v1/content/read",
    )

    args = parser.parse_args()
    if args.read_limit <= 0:
        raise ValueError("--read-limit must be > 0")

    verifier = QueryVerifier(args)
    profiles = _resolve_profiles(args)
    for profile in profiles:
        verifier.run_profile(profile)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
