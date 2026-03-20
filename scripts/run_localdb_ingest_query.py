# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
YOYO_DB_PATH = r"D:\HONOR Share\YOYO History\yoyochat2.db"
USER_PREFERENCE_DB_PATH = r"D:\HONOR Share\YOYO History\UserPreference.db"
YOYO_MAPPING_PATH = str(REPO_ROOT / "examples" / "localdb_yoyo_mapping.yaml")
USER_PREFERENCE_MAPPING_PATH = str(REPO_ROOT / "examples" / "localdb_user_preference_mapping.yaml")


@dataclass(frozen=True)
class ProfileCase:
    name: str
    db_path: str
    config_path: str
    ingest_source: str
    query_profile: str
    query_source: str | None = None


PROFILE_CASES = {
    "yoyo": ProfileCase(
        name="yoyo",
        db_path=YOYO_DB_PATH,
        config_path=YOYO_MAPPING_PATH,
        ingest_source="yoyo_history",
        query_profile="yoyo",
        query_source=None,
    ),
    "user_preference": ProfileCase(
        name="user_preference",
        db_path=USER_PREFERENCE_DB_PATH,
        config_path=USER_PREFERENCE_MAPPING_PATH,
        ingest_source="user_preference",
        query_profile="user_preference",
        query_source="user_preference",
    ),
}


def _expected_output_uris(case: ProfileCase, user_space: str) -> list[str]:
    if case.query_profile == "yoyo":
        return [
            "viking://yoyo/userinformation/default/userinformation.jsonl",
            "viking://yoyo/usertendencies/default/usertendencies.jsonl",
        ]
    source = case.query_source or case.ingest_source
    return [f"viking://user/{user_space}/memories/localdb/{source}/events.jsonl"]


def _print(message: str = "") -> None:
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def _pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _resolve_profiles(args: argparse.Namespace) -> list[ProfileCase]:
    if args.profile == "all":
        return [PROFILE_CASES["yoyo"], PROFILE_CASES["user_preference"]]

    default_case = PROFILE_CASES[args.profile]
    return [
        ProfileCase(
            name=default_case.name,
            db_path=args.db_path or default_case.db_path,
            config_path=args.config_path or default_case.config_path,
            ingest_source=args.source or default_case.ingest_source,
            query_profile=default_case.query_profile,
            query_source=args.source or default_case.query_source,
        )
    ]


def _call_json(
    *,
    client: httpx.Client,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _print(f"{method} {path}")
    if params is not None:
        _print("params:")
        _print(_pretty(params))
    if payload is not None:
        _print("json:")
        _print(_pretty(payload))

    response = client.request(method, path, params=params, json=payload)
    _print(f"status_code: {response.status_code}")
    response.raise_for_status()

    body = response.json()
    _print("response:")
    _print(_pretty(body))
    return body


def _health_check(*, client: httpx.Client) -> None:
    _print("\n=== Health Check ===")
    body = _call_json(client=client, method="GET", path="/health")
    if body.get("status") != "ok":
        raise RuntimeError(f"health check failed: {body}")


def _wait_processed(*, client: httpx.Client, timeout: float) -> None:
    _print("\n=== Wait Processed ===")
    body = _call_json(
        client=client,
        method="POST",
        path="/api/v1/system/wait",
        payload={"timeout": timeout},
    )
    if body.get("status") != "ok":
        raise RuntimeError(f"wait_processed failed: {body}")


def _delete_output_uri(*, client: httpx.Client, uri: str, ignore_missing: bool) -> None:
    _print("DELETE /api/v1/fs")
    _print("params:")
    _print(_pretty({"uri": uri}))
    response = client.delete("/api/v1/fs", params={"uri": uri})
    _print(f"status_code: {response.status_code}")
    if response.status_code == 404 and ignore_missing:
        _print("response:")
        _print(_pretty({"status": "skip", "reason": "not found", "uri": uri}))
        return
    response.raise_for_status()
    body = response.json()
    _print("response:")
    _print(_pretty(body))


def _reset_outputs(
    *,
    client: httpx.Client,
    case: ProfileCase,
    user_space: str,
    ignore_missing: bool,
) -> None:
    _print(f"\n=== Reset Outputs: {case.name} ===")
    for uri in _expected_output_uris(case, user_space):
        _delete_output_uri(client=client, uri=uri, ignore_missing=ignore_missing)


def _extract_query_items(body: dict[str, Any], *, case_name: str, action: str) -> list[dict[str, Any]]:
    if body.get("status") != "ok":
        raise RuntimeError(f"[{case_name}] {action} failed: {body}")
    result = body.get("result") or {}
    items = result.get("items") or []
    if not isinstance(items, list):
        raise RuntimeError(f"[{case_name}] {action} returned invalid items payload")
    return [item for item in items if isinstance(item, dict)]


def _run_ingest(
    *,
    client: httpx.Client,
    case: ProfileCase,
    user_space: str,
    dry_run: bool,
) -> dict[str, Any]:
    _print(f"\n=== Ingest: {case.name} ===")
    if not Path(case.db_path).exists():
        raise FileNotFoundError(f"[{case.name}] db not found: {case.db_path}")
    if not Path(case.config_path).exists():
        raise FileNotFoundError(f"[{case.name}] mapping not found: {case.config_path}")

    payload = {
        "db_path": case.db_path,
        "user_space": user_space,
        "source": case.ingest_source,
        "config_path": case.config_path,
        "dry_run": dry_run,
        "redact": True,
    }
    body = _call_json(
        client=client,
        method="POST",
        path="/api/v1/localdb/ingest",
        payload=payload,
    )
    if body.get("status") != "ok":
        raise RuntimeError(f"[{case.name}] ingest failed: {body}")

    result = body.get("result") or {}
    if str(result.get("db_path", "")) != case.db_path:
        raise RuntimeError(
            f"[{case.name}] ingest db_path mismatch: expected {case.db_path}, actual {result.get('db_path')}"
        )
    if int(result.get("failed", 0)) != 0:
        raise RuntimeError(f"[{case.name}] ingest reported failures: {result.get('failed')}")
    return result


def _run_query(
    *,
    client: httpx.Client,
    case: ProfileCase,
    user_space: str,
    read_limit: int,
) -> None:
    _print(f"\n=== Query: {case.name} ===")

    if case.query_profile == "yoyo":
        sources = [
            ("userinformation", "viking://yoyo/userinformation/default/userinformation.jsonl"),
            ("usertendencies", "viking://yoyo/usertendencies/default/usertendencies.jsonl"),
        ]
        semantic_cases = [
            {
                "source": "userinformation",
                "keyword": "晚课",
                "event_types": ["yoyo_user_information"],
                "limit": 3,
            },
            {
                "source": "usertendencies",
                "keyword": "无糖咖啡",
                "event_types": ["yoyo_user_tendency"],
                "limit": 3,
            },
            {
                "source": "usertendencies",
                "keyword": "流行音乐",
                "event_types": ["yoyo_user_tendency"],
                "limit": 3,
            },
        ]
    else:
        source = case.query_source or case.ingest_source
        query_sources = [
            (
                source,
                f"viking://user/{user_space}/memories/localdb/{source}/events.jsonl",
            )
        ]
        semantic_cases = []
        
    if case.query_profile == "yoyo":
        query_sources = [
            ("userinformation", "viking://yoyo/userinformation/default/userinformation.jsonl"),
            ("usertendencies", "viking://yoyo/usertendencies/default/usertendencies.jsonl"),
        ]

    sources_resp = _call_json(
        client=client,
        method="GET",
        path="/api/v1/localdb/sources",
        params={"user_space": user_space},
    )
    listed_sources = (sources_resp.get("result") or []) if sources_resp.get("status") == "ok" else []

    for source, uri in query_sources:
        if source not in listed_sources:
            raise RuntimeError(f"[{case.name}] list_sources did not contain {source}")
        content_resp = _call_json(
            client=client,
            method="GET",
            path="/api/v1/content/read",
            params={"uri": uri, "offset": 0, "limit": read_limit},
        )
        content = str((content_resp or {}).get("result", ""))
        rows = [json.loads(line) for line in content.splitlines() if line.strip()]
        if not rows:
            raise RuntimeError(f"[{case.name}] no jsonl rows found in {uri}")
        first = rows[0]
        first_id = str(first.get("id", ""))
        first_type = str(first.get("type", ""))

        all_query_resp = _call_json(
            client=client,
            method="POST",
            path="/api/v1/localdb/query",
            payload={
                "user_space": user_space,
                "source": source,
                "limit": min(max(len(rows), 1), 20),
            },
        )
        all_items = _extract_query_items(all_query_resp, case_name=case.name, action=f"{source} all query")
        if not all_items:
            raise RuntimeError(f"[{case.name}] {source} all query returned no items")

        id_query_resp = _call_json(
            client=client,
            method="POST",
            path="/api/v1/localdb/query",
            payload={
                "user_space": user_space,
                "source": source,
                "ids": [first_id],
                "limit": 1,
            },
        )
        id_items = _extract_query_items(id_query_resp, case_name=case.name, action=f"{source} id query")
        if not id_items or str(id_items[0].get("id", "")) != first_id:
            raise RuntimeError(f"[{case.name}] {source} id query did not return expected event")

        type_query_resp = _call_json(
            client=client,
            method="POST",
            path="/api/v1/localdb/query",
            payload={
                "user_space": user_space,
                "source": source,
                "event_types": [first_type],
                "limit": 3,
            },
        )
        type_items = _extract_query_items(
            type_query_resp,
            case_name=case.name,
            action=f"{source} type query",
        )
        if not type_items or not all(str(item.get("type", "")) == first_type for item in type_items):
            raise RuntimeError(f"[{case.name}] {source} type query returned unexpected event types")

        event_resp = _call_json(
            client=client,
            method="GET",
            path="/api/v1/localdb/event",
            params={
                "user_space": user_space,
                "source": source,
                "event_id": first_id,
            },
        )
        if event_resp.get("status") != "ok":
            raise RuntimeError(f"[{case.name}] {source} get_event failed: {event_resp}")
        event_result = event_resp.get("result") or {}
        if str(event_result.get("id", "")) != first_id:
            raise RuntimeError(f"[{case.name}] {source} get_event returned unexpected event id")

    for semantic in semantic_cases:
        semantic_resp = _call_json(
            client=client,
            method="POST",
            path="/api/v1/localdb/query",
            payload={
                "user_space": user_space,
                "source": semantic["source"],
                "keyword": semantic["keyword"],
                "event_types": semantic["event_types"],
                "limit": semantic["limit"],
            },
        )
        semantic_items = _extract_query_items(
            semantic_resp,
            case_name=case.name,
            action=f'{semantic["source"]} semantic query {semantic["keyword"]}',
        )
        if not semantic_items:
            raise RuntimeError(
                f'[{case.name}] {semantic["source"]} semantic query returned no hits for {semantic["keyword"]}'
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run real-server LocalDB end-to-end verification: health -> ingest -> wait -> query. "
            "All key HTTP requests and responses are printed to stdout."
        )
    )
    parser.add_argument(
        "--profile",
        choices=["yoyo", "user_preference", "all"],
        default="all",
        help="Built-in end-to-end verification profile.",
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
        help="User space used for ingest/query APIs",
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=120.0,
        help="Timeout in seconds passed to /api/v1/system/wait",
    )
    parser.add_argument(
        "--read-limit",
        type=int,
        default=200000,
        help="Byte limit passed to /api/v1/content/read during query verification",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run ingest in dry-run mode and skip wait/query",
    )
    parser.add_argument(
        "--reset-output",
        action="store_true",
        help="Delete expected output URI(s) before ingest. Recommended for post-restart verification.",
    )
    parser.add_argument(
        "--ignore-missing",
        action="store_true",
        help="When used with --reset-output, skip missing output URI(s) instead of failing.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override db_path for single-profile runs",
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="Override mapping config path for single-profile runs",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Override source for single-profile runs",
    )

    args = parser.parse_args()
    if args.wait_timeout <= 0:
        raise ValueError("--wait-timeout must be > 0")
    if args.read_limit <= 0:
        raise ValueError("--read-limit must be > 0")
    if args.profile == "all" and any([args.db_path, args.config_path, args.source]):
        raise ValueError("--db-path/--config-path/--source only support single-profile runs")

    profiles = _resolve_profiles(args)
    with httpx.Client(
        base_url=args.base_url,
        headers=_headers(args.api_key),
        timeout=180.0,
    ) as client:
        _health_check(client=client)

        results: list[str] = []
        for case in profiles:
            if args.reset_output:
                _reset_outputs(
                    client=client,
                    case=case,
                    user_space=args.user_space,
                    ignore_missing=args.ignore_missing,
                )
            ingest_result = _run_ingest(
                client=client,
                case=case,
                user_space=args.user_space,
                dry_run=args.dry_run,
            )
            results.append(
                f"{case.name}: ingest written={ingest_result.get('written', 0)} "
                f"output_uris={len(ingest_result.get('output_uris') or [])}"
            )

            if args.dry_run:
                continue

            _wait_processed(client=client, timeout=args.wait_timeout)
            _run_query(
                client=client,
                case=case,
                user_space=args.user_space,
                read_limit=args.read_limit,
            )

    _print("\n=== Summary ===")
    for line in results:
        _print(line)
    _print("overall: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
