# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

DEFAULT_URIS = [
    "viking://yoyo/userinformation/default/userinformation.jsonl",
    "viking://yoyo/usertendencies/default/usertendencies.jsonl",
]
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "examples" / "localdb_yoyo_mapping.yaml"


def _print(message: str = "") -> None:
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def _headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _delete_uri(
    *,
    client: httpx.Client,
    uri: str,
    ignore_missing: bool,
) -> None:
    response = client.delete("/api/v1/fs", params={"uri": uri})
    if response.status_code == 404 and ignore_missing:
        _print(f"SKIP  not found: {uri}")
        return
    response.raise_for_status()
    _print(f"OK    deleted: {uri}")


def _ingest(
    *,
    client: httpx.Client,
    db_path: str,
    user_space: str,
    source: str,
    config_path: str,
    dry_run: bool,
) -> dict[str, Any]:
    payload = {
        "db_path": db_path,
        "user_space": user_space,
        "source": source,
        "config_path": config_path,
        "dry_run": dry_run,
        "redact": True,
    }
    response = client.post("/api/v1/localdb/ingest", json=payload)
    response.raise_for_status()
    return response.json()


def _read_uri(
    *,
    client: httpx.Client,
    uri: str,
    limit: int,
) -> str:
    response = client.get(
        "/api/v1/content/read",
        params={"uri": uri, "offset": 0, "limit": limit},
    )
    response.raise_for_status()
    payload = response.json()
    return str(payload.get("result", ""))


def _parse_jsonl(content: str) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_no}: invalid json: {exc.msg}")
            continue
        if not isinstance(data, dict):
            errors.append(f"line {line_no}: expected json object")
            continue
        items.append(data)
    return items, errors


def _print_summary(uri: str, content: str, preview_rows: int, raw_preview: bool) -> None:
    items, errors = _parse_jsonl(content)
    type_counts = Counter(str(item.get("type", "")) for item in items)
    _print(f"=== {uri} ===")
    _print(f"rows={len(items)} invalid={len(errors)}")
    if type_counts:
        _print(f"types={dict(type_counts)}")

    for idx, item in enumerate(items[:preview_rows], start=1):
        attrs = item.get("attrs") if isinstance(item.get("attrs"), dict) else {}
        time_obj = item.get("time") if isinstance(item.get("time"), dict) else {}
        title = str(attrs.get("title", "")).strip()
        text = str(item.get("text", "")).strip()
        ts = str(time_obj.get("ts", "")).strip()
        _print(f"sample[{idx}] ts={ts} title={title or text}")
        if raw_preview:
            _print(json.dumps(item, ensure_ascii=False))

    if len(items) > preview_rows:
        _print(f"... truncated, showing first {preview_rows} parsed rows")
    if errors:
        _print(f"errors={errors[:3]}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-click YOYO refresh: reset target JSONL files, ingest caller-provided SQLite, then print summaries."
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
        help="User space for the ingest request",
    )
    parser.add_argument(
        "--source",
        default="yoyo_history",
        help="Source value for the ingest request",
    )
    parser.add_argument(
        "--db-path",
        required=True,
        help="SQLite db_path forwarded to /api/v1/localdb/ingest",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Mapping config path",
    )
    parser.add_argument(
        "--preview-rows",
        type=int,
        default=3,
        help="Number of parsed rows to summarize per output file",
    )
    parser.add_argument(
        "--read-limit",
        type=int,
        default=200000,
        help="Byte limit passed to /api/v1/content/read",
    )
    parser.add_argument(
        "--raw-preview",
        action="store_true",
        help="Also print raw JSON for preview rows",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Skip deleting existing YOYO JSONL files before ingest",
    )
    parser.add_argument(
        "--ignore-missing",
        action="store_true",
        help="Do not fail if a target URI does not exist during reset",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run ingest in dry-run mode after optional reset",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="HTTP timeout in seconds for reset/ingest/read requests",
    )

    args = parser.parse_args()

    if args.preview_rows < 0:
        raise ValueError("--preview-rows must be >= 0")
    if args.read_limit <= 0:
        raise ValueError("--read-limit must be > 0")

    with httpx.Client(
        base_url=args.base_url,
        headers=_headers(args.api_key),
        timeout=args.timeout,
    ) as client:
        if not args.no_reset:
            _print("== Reset ==")
            for uri in DEFAULT_URIS:
                _delete_uri(client=client, uri=uri, ignore_missing=args.ignore_missing)

        _print()
        _print("== Ingest ==")
        result = _ingest(
            client=client,
            db_path=args.db_path,
            user_space=args.user_space,
            source=args.source,
            config_path=args.config,
            dry_run=args.dry_run,
        )
        _print(json.dumps(result, ensure_ascii=False, indent=2))

        if args.dry_run:
            return 0

        _print()
        _print("== Summary ==")
        report = result.get("result") or {}
        output_uris = report.get("output_uris") or DEFAULT_URIS
        for uri in output_uris:
            content = _read_uri(client=client, uri=uri, limit=args.read_limit)
            _print_summary(uri, content, args.preview_rows, args.raw_preview)
            _print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
