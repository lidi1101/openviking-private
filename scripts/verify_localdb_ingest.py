# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
YOYO_DB_PATH = r"D:\HONOR Share\YOYO History\yoyochat2.db"
USER_PREFERENCE_DB_PATH = r"D:\HONOR Share\YOYO History\UserPreference.db"


@dataclass(frozen=True)
class IngestCase:
    name: str
    db_path: str
    config_path: str | None
    source: str


PROFILE_DEFAULTS = {
    "yoyo": IngestCase(
        name="yoyo",
        db_path=YOYO_DB_PATH,
        config_path=str(REPO_ROOT / "examples" / "localdb_yoyo_mapping.yaml"),
        source="yoyo_history",
    ),
    "user_preference": IngestCase(
        name="user_preference",
        db_path=USER_PREFERENCE_DB_PATH,
        config_path=str(REPO_ROOT / "examples" / "localdb_user_preference_mapping.yaml"),
        source="user_preference",
    ),
}


def _print(message: str = "") -> None:
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


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


def _print_jsonl_summary(uri: str, content: str, preview_rows: int, raw_preview: bool) -> int:
    rows = [line for line in content.splitlines() if line.strip()]
    if not rows:
        _print(f"OK: jsonl written: {uri}")
        _print("rows=0")
        return 0

    items, errors = _parse_jsonl(content)
    type_counts = Counter(str(item.get("type", "")) for item in items)

    _print(f"OK: jsonl written: {uri}")
    _print(f"rows={len(rows)} parsed={len(items)} invalid={len(errors)}")
    if type_counts:
        _print(f"types={dict(type_counts)}")

    for idx, item in enumerate(items[:preview_rows], start=1):
        title = str((item.get("attrs") or {}).get("title", "")).strip()
        text = str(item.get("text", "")).strip()
        time_obj = item.get("time") if isinstance(item.get("time"), dict) else {}
        ts = str(time_obj.get("ts", "")).strip()
        _print(f"sample[{idx}] ts={ts} title={title or text}")
        if raw_preview:
            _print(json.dumps(item, ensure_ascii=False))

    if len(items) > preview_rows:
        _print(f"... truncated, showing first {preview_rows} parsed rows")
    if errors:
        _print(f"errors={errors[:3]}")

    return len(rows)


def _detect_candidate_mapping(db_path: str) -> tuple[str, str, str, str]:
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        tables = [
            row[0]
            for row in cur.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
            ).fetchall()
        ]
        if not tables:
            raise RuntimeError("No tables found in sqlite db")

        preferred = [
            "messages",
            "message",
            "chat_messages",
            "chat_message",
            "conversation",
            "conversations",
            "history",
        ]
        table = next((name for name in preferred if name in tables), tables[0])

        cols = [row[1] for row in cur.execute(f"pragma table_info({table})").fetchall()]
        if not cols:
            raise RuntimeError(f"No columns found in table {table}")

        def pick(candidates: list[str]) -> str:
            for candidate in candidates:
                if candidate in cols:
                    return candidate
            return cols[0]

        pk = pick(["id", "msg_id", "message_id", "uuid"])
        time_col = pick(["created_at", "create_time", "timestamp", "ts", "time", "date"])
        text_col = pick(["content", "text", "message", "body"])
        return table, pk, time_col, text_col
    finally:
        con.close()


def _write_temp_mapping_yaml(*, table: str, pk: str, time_col: str, text_col: str) -> str:
    content = f"""# Auto-generated for verification only
extract:
  - id: auto_{table}
    type: localdb_row
    output_uri: viking://user/{{user_space}}/memories/localdb/{{source}}/events.jsonl
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
) -> dict[str, Any]:
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=120.0) as client:
        payload = {
            "db_path": db_path,
            "user_space": user_space,
            "source": source,
            "config_path": config_path,
            "dry_run": dry_run,
            "redact": True,
        }
        response = await client.post("/api/v1/localdb/ingest", json=payload)
        response.raise_for_status()
        return response.json()


async def _read_content(
    *,
    base_url: str,
    api_key: str | None,
    uri: str,
    limit: int,
) -> str:
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=60.0) as client:
        response = await client.get(
            "/api/v1/content/read",
            params={"uri": uri, "offset": 0, "limit": limit},
        )
        response.raise_for_status()
        return str((response.json() or {}).get("result", ""))


def _resolve_cases(args: argparse.Namespace) -> list[IngestCase]:
    if args.profile == "all":
        return [PROFILE_DEFAULTS["yoyo"], PROFILE_DEFAULTS["user_preference"]]

    if args.profile in PROFILE_DEFAULTS:
        default_case = PROFILE_DEFAULTS[args.profile]
        return [
            IngestCase(
                name=default_case.name,
                db_path=args.db or default_case.db_path,
                config_path=args.config or default_case.config_path,
                source=args.source or default_case.source,
            )
        ]

    return [
        IngestCase(
            name="custom",
            db_path=args.db,
            config_path=args.config,
            source=args.source or "localdb_verify",
        )
    ]


def _validate_case(case: IngestCase) -> None:
    if not case.db_path:
        raise ValueError(f"[{case.name}] db_path is required")
    if not os.path.exists(case.db_path):
        raise FileNotFoundError(f"[{case.name}] db not found: {case.db_path}")


def _resolve_config(case: IngestCase) -> tuple[str, str | None]:
    if case.config_path:
        return case.config_path, None

    table, pk, time_col, text_col = _detect_candidate_mapping(case.db_path)
    temp_config = _write_temp_mapping_yaml(
        table=table,
        pk=pk,
        time_col=time_col,
        text_col=text_col,
    )
    _print(
        "Auto mapping generated (verification only): "
        f"table={table}, pk={pk}, time={time_col}, text={text_col}"
    )
    _print(f"mapping_config: {temp_config}")
    return temp_config, temp_config


def _run_case(args: argparse.Namespace, case: IngestCase) -> tuple[bool, str]:
    _print(f"\n=== Ingest Case: {case.name} ===")
    _print(f"db_path: {case.db_path}")
    _print(f"source: {case.source}")

    temp_config: str | None = None
    try:
        _validate_case(case)
        config_path, temp_config = _resolve_config(case)
        _print(f"config_path: {config_path}")

        result = asyncio.run(
            _call_ingest_api(
                base_url=args.base_url,
                api_key=args.api_key,
                db_path=case.db_path,
                user_space=args.user_space,
                source=case.source,
                config_path=config_path,
                dry_run=args.dry_run,
            )
        )
        _print("Ingest API response:")
        _print(json.dumps(result, ensure_ascii=False, indent=2))

        report = result.get("result") or {}
        if str(report.get("db_path", "")) != case.db_path:
            raise RuntimeError(
                f"[{case.name}] db_path mismatch: expected {case.db_path}, actual {report.get('db_path')}"
            )

        output_uris = report.get("output_uris") or []
        if not output_uris and report.get("output_uri"):
            output_uris = [str(report["output_uri"])]

        if args.dry_run:
            return True, f"[{case.name}] PASS dry-run"

        if not output_uris:
            raise RuntimeError(f"[{case.name}] ingest did not return any output_uris")

        for output_uri in output_uris:
            content = asyncio.run(
                _read_content(
                    base_url=args.base_url,
                    api_key=args.api_key,
                    uri=output_uri,
                    limit=args.read_limit,
                )
            )
            if not content.strip():
                raise RuntimeError(f"[{case.name}] jsonl is empty or not readable: {output_uri}")

            _print_jsonl_summary(
                output_uri,
                content,
                preview_rows=args.preview_rows,
                raw_preview=args.raw_preview,
            )

        return True, f"[{case.name}] PASS outputs={len(output_uris)}"
    except Exception as exc:
        return False, f"[{case.name}] FAIL {exc}"
    finally:
        if temp_config:
            try:
                Path(temp_config).unlink(missing_ok=True)
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify OpenViking LocalDB ingest for one or more SQLite profiles. "
            "Use --profile yoyo, --profile user_preference, or --profile all."
        )
    )
    parser.add_argument(
        "--profile",
        choices=["custom", "yoyo", "user_preference", "all"],
        default="custom",
        help="Built-in verification profile. Use custom to pass db/config/source manually.",
    )
    parser.add_argument(
        "--db",
        default=YOYO_DB_PATH,
        help=f"SQLite db path (default: {YOYO_DB_PATH})",
    )
    parser.add_argument(
        "--user-space",
        required=True,
        help="User space, e.g. <account>/<user> or <account>/<user>/<agent>",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Source name under memories/localdb/<source>. Profile defaults apply when omitted.",
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
        help="Mapping config path (yaml/json). If omitted in custom mode, auto-generate a minimal one.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run (do not write jsonl files)",
    )
    parser.add_argument(
        "--preview-rows",
        type=int,
        default=5,
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

    args = parser.parse_args()

    if args.preview_rows < 0:
        raise ValueError("--preview-rows must be >= 0")
    if args.read_limit <= 0:
        raise ValueError("--read-limit must be > 0")

    cases = _resolve_cases(args)
    results = [_run_case(args, case) for case in cases]

    _print("\n=== Summary ===")
    for _, message in results:
        _print(message)

    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
