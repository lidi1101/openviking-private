# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

import httpx


def _print(s: str) -> None:
    sys.stdout.write(s + "\n")
    sys.stdout.flush()


def _detect_candidate_mapping(db_path: str) -> Tuple[str, str, str, str]:
    """Best-effort mapping detection.

    Returns: (table, pk_col, time_col, text_col)

    This is ONLY for verification convenience. It does not do sampling preview.
    """
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        tables = [
            r[0]
            for r in cur.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
            ).fetchall()
        ]
        if not tables:
            raise RuntimeError("No tables found in sqlite db")

        # Prefer common names
        preferred = [
            "messages",
            "message",
            "chat_messages",
            "chat_message",
            "conversation",
            "conversations",
            "history",
        ]
        table = next((t for t in preferred if t in tables), tables[0])

        cols = [r[1] for r in cur.execute(f"pragma table_info({table})").fetchall()]
        if not cols:
            raise RuntimeError(f"No columns found in table {table}")

        def pick(candidates: List[str]) -> str:
            for c in candidates:
                if c in cols:
                    return c
            return cols[0]

        pk = pick(["id", "msg_id", "message_id", "uuid"])
        time_col = pick(["created_at", "create_time", "timestamp", "ts", "time", "date"])
        text_col = pick(["content", "text", "message", "body"])

        return table, pk, time_col, text_col
    finally:
        con.close()


def _write_temp_mapping_yaml(
    *,
    db_path: str,
    table: str,
    pk: str,
    time_col: str,
    text_col: str,
) -> str:
    # We keep it minimal: 1 extract item, limit rows to avoid huge import during verification.
    # NOTE: This is not schema preview; it just uses pragma metadata.
    content = f"""# Auto-generated for verification only
extract:
  - id: auto_{table}
    type: localdb_row
    sql: |
      SELECT
        {pk} as pk,
        {time_col} as ts,
        {text_col} as title
      FROM {table}
      ORDER BY {time_col} DESC
      LIMIT 200
    columns:
      pk: pk
      time: ts
      title: title
"""
    fd, path = tempfile.mkstemp(prefix="openviking-localdb-", suffix=".yaml")
    os.close(fd)
    Path(path).write_text(content, encoding="utf-8")
    return path


async def _call_ingest_api(
    *,
    base_url: str,
    api_key: str | None,
    db_path: str,
    user_space: str,
    source: str,
    config_path: str,
    dry_run: bool,
) -> dict:
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=120.0) as client:
        r = await client.post(
            "/api/v1/localdb/ingest",
            json={
                "db_path": db_path,
                "user_space": user_space,
                "source": source,
                "config_path": config_path,
                "dry_run": dry_run,
                "redact": True,
            },
        )
        r.raise_for_status()
        return r.json()


async def _read_content(
    *,
    base_url: str,
    api_key: str | None,
    uri: str,
    limit: int = 50,
) -> str:
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=60.0) as client:
        r = await client.get(
            "/api/v1/content/read",
            params={"uri": uri, "offset": 0, "limit": limit},
        )
        r.raise_for_status()
        data = r.json()
        return data.get("result", "")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify OpenViking LocalDB ingest: sqlite -> viking://user/.../memories/localdb/.../events.jsonl"
    )
    parser.add_argument(
        "--db",
        default=r"D:\HonorShare\yoyochat2.db",
        help="SQLite db path (default: D:\\HonorShare\\yoyochat2.db)",
    )
    parser.add_argument(
        "--user-space",
        required=True,
        help="User space, e.g. <account>/<user> or <account>/<user>/<agent>",
    )
    parser.add_argument(
        "--source",
        default="yoyo_history",
        help="Source name under memories/localdb/<source>",
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
        "--config",
        default=None,
        help="Mapping config path (yaml/json). If omitted, auto-generate a minimal one.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run (do not write events.jsonl)",
    )

    args = parser.parse_args()

    db_path = args.db
    if not os.path.exists(db_path):
        _print(f"ERROR: db not found: {db_path}")
        return 2

    config_path = args.config
    temp_config = None
    if not config_path:
        table, pk, time_col, text_col = _detect_candidate_mapping(db_path)
        temp_config = _write_temp_mapping_yaml(
            db_path=db_path, table=table, pk=pk, time_col=time_col, text_col=text_col
        )
        config_path = temp_config
        _print(
            "Auto mapping generated (verification only): "
            f"table={table}, pk={pk}, time={time_col}, text={text_col}"
        )
        _print(f"mapping_config: {config_path}")

    output_uri = f"viking://user/{args.user_space}/memories/localdb/{args.source}/events.jsonl"

    try:
        result = asyncio.run(
            _call_ingest_api(
                base_url=args.base_url,
                api_key=args.api_key,
                db_path=db_path,
                user_space=args.user_space,
                source=args.source,
                config_path=config_path,
                dry_run=args.dry_run,
            )
        )
        _print("Ingest API response:")
        _print(json.dumps(result, ensure_ascii=False, indent=2))

        if args.dry_run:
            _print("dry-run enabled: skip reading events.jsonl")
            return 0

        content = asyncio.run(
            _read_content(base_url=args.base_url, api_key=args.api_key, uri=output_uri, limit=50)
        )
        if not content.strip():
            _print(f"ERROR: events.jsonl is empty or not readable: {output_uri}")
            return 3

        lines = [ln for ln in content.splitlines() if ln.strip()]
        _print(f"OK: events.jsonl written: {output_uri}")
        _print(f"Preview lines: {min(len(lines), 5)}")
        for ln in lines[:5]:
            _print(ln)

        return 0
    finally:
        if temp_config:
            try:
                Path(temp_config).unlink(missing_ok=True)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
