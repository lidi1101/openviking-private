# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Delayed startup ingest/query end-to-end probe for local OpenViking server."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import traceback
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx
import yaml

from openviking.db.reader import parse_event
from openviking.db.sqlite_reader import open_sqlite_readonly
from openviking.server.config import ServerConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HISTORY_DIR = Path(r"D:\HONOR Share\YOYO History")
YOYO_DB_FILENAME = "yoyochat2.db"
USER_PREFERENCE_DB_FILENAME = "UserPreference.db"
YOYO_MAPPING_PATH = REPO_ROOT / "examples" / "localdb_yoyo_mapping.yaml"
USER_PREFERENCE_MAPPING_PATH = REPO_ROOT / "examples" / "localdb_user_preference_mapping.yaml"
USER_PREFERENCE_OUTPUT_URI = "viking://sense/pcevent/default/event.jsonl"


@dataclass(frozen=True)
class ProfileCase:
    name: str
    db_path: Path
    config_path: Path
    ingest_source: str
    query_profile: str
    query_source: str | None = None


PROFILE_CASES = {
    "yoyo": ProfileCase(
        name="yoyo",
        db_path=DEFAULT_HISTORY_DIR / YOYO_DB_FILENAME,
        config_path=YOYO_MAPPING_PATH,
        ingest_source="yoyo_history",
        query_profile="yoyo",
        query_source=None,
    ),
    "user_preference": ProfileCase(
        name="user_preference",
        db_path=DEFAULT_HISTORY_DIR / USER_PREFERENCE_DB_FILENAME,
        config_path=USER_PREFERENCE_MAPPING_PATH,
        ingest_source="user_preference",
        query_profile="user_preference",
        query_source="userpreference",
    ),
}

DEFAULT_PROFILE_CONFIG_PATHS = {
    name: case.config_path for name, case in PROFILE_CASES.items()
}

DEFAULT_PROFILE_CONFIG_ENV = "OPENVIKING_STARTUP_E2E_CONFIG_PATH"


@dataclass(frozen=True)
class GeneratedExtract:
    query_id: str
    event_type: str
    table_name: str
    output_uri: str
    sql: str | None = None
    columns: dict[str, str] | None = None


def _normalize_name(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum()).casefold()


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _pick_name(candidates: list[str], actual_names: list[str]) -> str | None:
    if not actual_names:
        return None

    lookup = {_normalize_name(name): name for name in actual_names}
    for candidate in candidates:
        matched = lookup.get(_normalize_name(candidate))
        if matched:
            return matched
    return None


def _cleanup_temp_copy(tmp_copy_path: str | None) -> None:
    if not tmp_copy_path:
        return
    shutil.rmtree(Path(tmp_copy_path).parent, ignore_errors=True)


def _build_generated_extract(
    *,
    table_name: str,
    columns: list[str],
    query_id: str,
    event_type: str,
    output_uri: str,
) -> dict[str, Any]:
    if not columns:
        raise ValueError(f"table {table_name!r} has no columns")

    pk_col = _pick_name(["id", "msg_id", "message_id", "uuid", "key"], columns) or columns[0]
    time_col = _pick_name(
        ["created_at", "create_time", "timestamp", "ts", "time", "date", "updated_at"],
        columns,
    )
    title_col = _pick_name(
        [
            "title",
            "content",
            "text",
            "message",
            "body",
            "value",
            "name",
            "summary",
            "preference",
            "description",
        ],
        columns,
    )

    select_ts = f"{_quote_ident(time_col)} as ts" if time_col else "NULL as ts"
    select_title = (
        f"CAST({_quote_ident(title_col)} AS TEXT) as title"
        if title_col
        else f"CAST({_quote_ident(pk_col)} AS TEXT) as title"
    )
    order_col = _quote_ident(time_col or pk_col)

    sql = "\n".join(
        [
            "SELECT",
            f"  {_quote_ident(pk_col)} as pk,",
            f"  {select_ts},",
            f"  {select_title}",
            f"FROM {_quote_ident(table_name)}",
            f"ORDER BY {order_col} DESC",
            "LIMIT 200",
        ]
    )

    return {
        "id": query_id,
        "type": event_type,
        "table": table_name,
        "output_uri": output_uri,
        "sql": sql,
        "columns": {
            "pk": "pk",
            "time": "ts",
            "title": "title",
        },
    }


def _yoyo_generated_extracts(table_names: list[str]) -> list[GeneratedExtract] | None:
    user_information_table = _pick_name(["user_information", "userinformation"], table_names)
    user_tendencies_table = _pick_name(["user_tendencies", "usertendencies"], table_names)
    if not user_information_table or not user_tendencies_table:
        return None

    return [
        _manual_generated_extract(
            query_id="yoyo_user_information_profile",
            event_type="yoyo_user_information",
            table_name=user_information_table,
            output_uri="viking://yoyo/userinformation/default/userinformation.jsonl",
            sql="\n".join(
                [
                    "SELECT",
                    '  "id" as pk,',
                    '  "timestamp" as ts,',
                    '  CAST("count_id" AS TEXT) as count_id,',
                    '  CAST("preference_owner" AS TEXT) as preference_owner,',
                    '  CAST("content" AS TEXT) as content,',
                    '  CAST("preference_type" AS TEXT) as preference_type,',
                    '  CAST("preference_sub_type" AS TEXT) as preference_sub_type,',
                    '  CAST("preference_content" AS TEXT) as preference_content,',
                    '  \'count_id=\' || COALESCE(trim(CAST("count_id" AS TEXT)), \'\')',
                    '    || \' | preference_owner=\' || COALESCE(trim(CAST("preference_owner" AS TEXT)), \'\')',
                    '    || \' | content=\' || COALESCE(trim(CAST("content" AS TEXT)), \'\')',
                    '    || \' | preference_type=\' || COALESCE(trim(CAST("preference_type" AS TEXT)), \'\')',
                    '    || \' | preference_sub_type=\' || COALESCE(trim(CAST("preference_sub_type" AS TEXT)), \'\')',
                    '    || \' | preference_content=\' || COALESCE(trim(CAST("preference_content" AS TEXT)), \'\') as title',
                    f"FROM {_quote_ident(user_information_table)}",
                    'ORDER BY "id" DESC',
                    "LIMIT 200",
                ]
            ),
            columns={
                "pk": "pk",
                "time": "ts",
                "title": "title",
                "text_count_id": "count_id",
                "text_preference_owner": "preference_owner",
                "text_content": "content",
                "text_preference_type": "preference_type",
                "text_preference_sub_type": "preference_sub_type",
                "text_preference_content": "preference_content",
            },
        ),
        _manual_generated_extract(
            query_id="yoyo_user_tendencies_preference",
            event_type="yoyo_user_tendency",
            table_name=user_tendencies_table,
            output_uri="viking://yoyo/usertendencies/default/usertendencies.jsonl",
            sql="\n".join(
                [
                    "SELECT",
                    '  "id" as pk,',
                    '  "timestamp" as ts,',
                    '  CAST("count_id" AS TEXT) as count_id,',
                    '  CAST("preference_owner" AS TEXT) as preference_owner,',
                    '  CAST("content" AS TEXT) as content,',
                    '  CAST("preference_type" AS TEXT) as preference_type,',
                    '  CAST("preference_content" AS TEXT) as preference_content,',
                    '  CAST("tendency" AS TEXT) as tendency,',
                    '  \'count_id=\' || COALESCE(trim(CAST("count_id" AS TEXT)), \'\')',
                    '    || \' | preference_owner=\' || COALESCE(trim(CAST("preference_owner" AS TEXT)), \'\')',
                    '    || \' | content=\' || COALESCE(trim(CAST("content" AS TEXT)), \'\')',
                    '    || \' | preference_type=\' || COALESCE(trim(CAST("preference_type" AS TEXT)), \'\')',
                    '    || \' | preference_content=\' || COALESCE(trim(CAST("preference_content" AS TEXT)), \'\')',
                    '    || \' | tendency=\' || COALESCE(trim(CAST("tendency" AS TEXT)), \'\') as title',
                    f"FROM {_quote_ident(user_tendencies_table)}",
                    "WHERE",
                    '  COALESCE(trim(CAST("preference_type" AS TEXT)), \'\') <> \'\'',
                    "  AND lower(trim(CAST(\"preference_type\" AS TEXT))) NOT IN ('none', 'null')",
                    '  AND COALESCE(trim(CAST("preference_content" AS TEXT)), \'\') <> \'\'',
                    "  AND lower(trim(CAST(\"preference_content\" AS TEXT))) NOT IN ('none', 'null')",
                    'ORDER BY "id" DESC',
                    "LIMIT 200",
                ]
            ),
            columns={
                "pk": "pk",
                "time": "ts",
                "title": "title",
                "text_count_id": "count_id",
                "text_preference_owner": "preference_owner",
                "text_content": "content",
                "text_preference_type": "preference_type",
                "text_preference_content": "preference_content",
                "text_tendency": "tendency",
            },
        ),
    ]


def _manual_generated_extract(
    *,
    query_id: str,
    event_type: str,
    table_name: str,
    output_uri: str,
    sql: str,
    columns: dict[str, str] | None = None,
) -> GeneratedExtract:
    return GeneratedExtract(
        query_id=query_id,
        event_type=event_type,
        table_name=table_name,
        output_uri=output_uri,
        sql=sql,
        columns=columns
        or {
            "pk": "pk",
            "time": "ts",
            "title": "title",
        },
    )


def _user_preference_generated_extracts(table_names: list[str]) -> list[GeneratedExtract] | None:
    windows_info_table = _pick_name(["windowsinfodata", "windows_info_data"], table_names)
    if windows_info_table:
        return [
            _manual_generated_extract(
                query_id="user_preference_windows_info",
                event_type="user_preference_event",
                table_name=windows_info_table,
                output_uri=USER_PREFERENCE_OUTPUT_URI,
                sql="\n".join(
                    [
                        "SELECT",
                        '  "WindowsInfoDataID" as pk,',
                        '  "CreatTime" as ts,',
                        '  CAST("APIType" AS TEXT) as api_type,',
                        '  CAST("Name" AS TEXT) as name,',
                        '  CAST("Data" AS TEXT) as data,',
                        "  CASE",
                        '    WHEN COALESCE("Name", \'\') <> \'\' AND COALESCE("Data", \'\') <> \'\'',
                        '      THEN CAST("Name" AS TEXT) || \': \' || CAST("Data" AS TEXT)',
                        '    WHEN COALESCE("Name", \'\') <> \'\'',
                        '      THEN CAST("Name" AS TEXT)',
                        '    ELSE CAST("Data" AS TEXT)',
                        "  END as title",
                        f"FROM {_quote_ident(windows_info_table)}",
                        "WHERE lower(",
                        '  replace(replace(replace(CAST("APIType" AS TEXT), \'_\', \'\'), \' \', \'\'), \'-\', \'\')',
                        ") IN (",
                        "  '\u7535\u6c60',",
                        "  'battery',",
                        "  'batterystatus',",
                        "  '\u84dd\u7259\u8fde\u63a5\u72b6\u6001',",
                        "  'bluetoothconnectionstatus',",
                        "  'bluetoothstatus',",
                        "  'wifi\u7f51\u7edc\u72b6\u6001',",
                        "  'wifinetworkstatus',",
                        "  'wifistatus',",
                        "  '\u5de5\u4f5c\u72b6\u6001',",
                        "  'workstatus',",
                        "  'workingstatus'",
                        ")",
                        'ORDER BY "WindowsInfoDataID" DESC',
                        "LIMIT 200",
                    ]
                ),
                columns={
                    "pk": "pk",
                    "time": "ts",
                    "title": "title",
                    "text_api_type": "api_type",
                    "text_name": "name",
                    "text_data": "data",
                },
            )
        ]

    return None


def _build_generated_extract_specs(case: ProfileCase, table_names: list[str]) -> list[GeneratedExtract] | None:
    if case.name == "yoyo":
        return _yoyo_generated_extracts(table_names)
    if case.name == "user_preference":
        return _user_preference_generated_extracts(table_names)
    return None


def _should_generate_default_config(case: ProfileCase) -> bool:
    if os.environ.get(DEFAULT_PROFILE_CONFIG_ENV):
        return False

    default_path = DEFAULT_PROFILE_CONFIG_PATHS.get(case.name)
    if default_path is None:
        return False

    return case.config_path == default_path


def _generate_temp_mapping_config(case: ProfileCase) -> Path | None:
    if not _should_generate_default_config(case):
        return None
    if not case.db_path.exists():
        return None

    conn, _opened_via_copy, tmp_copy_path = open_sqlite_readonly(str(case.db_path))
    try:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        table_names = [str(row["name"]) for row in rows if row["name"]]
        extract_specs = _build_generated_extract_specs(case, table_names)
        if not extract_specs:
            return None

        extract_items: list[dict[str, Any]] = []
        for spec in extract_specs:
            if spec.sql is not None:
                extract_items.append(
                    {
                        "id": spec.query_id,
                        "type": spec.event_type,
                        "table": spec.table_name,
                        "output_uri": spec.output_uri,
                        "sql": spec.sql,
                        "columns": spec.columns
                        or {
                            "pk": "pk",
                            "time": "ts",
                            "title": "title",
                        },
                    }
                )
                continue

            column_rows = conn.execute(f"PRAGMA table_info({_quote_ident(spec.table_name)})").fetchall()
            columns = [str(row["name"]) for row in column_rows if row["name"]]
            if not columns:
                return None
            extract_items.append(
                _build_generated_extract(
                    table_name=spec.table_name,
                    columns=columns,
                    query_id=spec.query_id,
                    event_type=spec.event_type,
                    output_uri=spec.output_uri,
                )
            )
    finally:
        try:
            conn.close()
        finally:
            _cleanup_temp_copy(tmp_copy_path)

    fd, temp_path = tempfile.mkstemp(
        prefix=f"openviking-startup-e2e-{case.name}-",
        suffix=".yaml",
    )
    os.close(fd)
    temp_config_path = Path(temp_path)
    temp_config_path.write_text(
        yaml.safe_dump({"extract": extract_items}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return temp_config_path


def _prepare_case_for_probe(case: ProfileCase) -> tuple[ProfileCase | None, str | None, Path | None]:
    missing: list[str] = []
    cleanup_path: Path | None = None
    prepared_case = case

    if not case.db_path.exists():
        missing.append(f"db_path missing: {case.db_path}")

    if case.config_path.exists():
        return prepared_case, None if not missing else " ; ".join(missing), cleanup_path

    generated_config_path = _generate_temp_mapping_config(case)
    if generated_config_path is not None:
        cleanup_path = generated_config_path
        prepared_case = replace(case, config_path=generated_config_path)
        _print_probe(
            f"profile={case.name} generated temp mapping config_path={generated_config_path}"
        )
        return prepared_case, None if not missing else " ; ".join(missing), cleanup_path

    missing.append(f"config_path missing: {case.config_path}")
    return None, " ; ".join(missing), cleanup_path


def _print_probe(message: str) -> None:
    print(f"[StartupE2E] {message}", flush=True)


def _history_dir() -> Path:
    return Path(os.environ.get("OPENVIKING_STARTUP_E2E_DB_DIR", str(DEFAULT_HISTORY_DIR)))


def _resolve_profile_db_path(profile_name: str) -> Path:
    base_dir = _history_dir()
    filename = {
        "yoyo": YOYO_DB_FILENAME,
        "user_preference": USER_PREFERENCE_DB_FILENAME,
    }.get(profile_name)
    if not filename:
        raise ValueError(f"unsupported profile for db resolution: {profile_name}")
    return base_dir / filename


def _default_profiles() -> list[ProfileCase]:
    return [
        ProfileCase(
            name=PROFILE_CASES["yoyo"].name,
            db_path=_resolve_profile_db_path("yoyo"),
            config_path=PROFILE_CASES["yoyo"].config_path,
            ingest_source=PROFILE_CASES["yoyo"].ingest_source,
            query_profile=PROFILE_CASES["yoyo"].query_profile,
            query_source=PROFILE_CASES["yoyo"].query_source,
        ),
        ProfileCase(
            name=PROFILE_CASES["user_preference"].name,
            db_path=_resolve_profile_db_path("user_preference"),
            config_path=PROFILE_CASES["user_preference"].config_path,
            ingest_source=PROFILE_CASES["user_preference"].ingest_source,
            query_profile=PROFILE_CASES["user_preference"].query_profile,
            query_source=PROFILE_CASES["user_preference"].query_source,
        ),
    ]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value < 0:
        return default
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return value


def startup_probe_enabled() -> bool:
    return _env_bool("OPENVIKING_STARTUP_E2E_ENABLED", False)


def _startup_delay_seconds() -> float:
    return _env_float("OPENVIKING_STARTUP_E2E_DELAY_SECONDS", 30.0)


def _resolve_base_url(config: ServerConfig) -> str:
    override = os.environ.get("OPENVIKING_STARTUP_E2E_BASE_URL")
    if override:
        return override.rstrip("/")

    host = str(config.host or "").strip()
    if host in {"", "0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"

    return f"http://{host}:{config.port}"


def _headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _expected_output_uris(case: ProfileCase, user_space: str) -> list[str]:
    if case.query_profile == "yoyo":
        return [
            "viking://yoyo/userinformation/default/userinformation.jsonl",
            "viking://yoyo/usertendencies/default/usertendencies.jsonl",
        ]

    return [USER_PREFERENCE_OUTPUT_URI]


def _query_sources(case: ProfileCase, user_space: str) -> list[tuple[str, str]]:
    if case.query_profile == "yoyo":
        return [
            ("userinformation", "viking://yoyo/userinformation/default/userinformation.jsonl"),
            ("usertendencies", "viking://yoyo/usertendencies/default/usertendencies.jsonl"),
        ]

    source = case.query_source or case.ingest_source
    return [(source, USER_PREFERENCE_OUTPUT_URI)]


def _resolve_profiles() -> list[ProfileCase]:
    profile = os.environ.get("OPENVIKING_STARTUP_E2E_PROFILE", "all").strip() or "all"
    if profile == "all":
        return _default_profiles()
    if profile not in PROFILE_CASES:
        _print_probe(f"unknown profile={profile!r}; fallback to all")
        return _default_profiles()

    default_case = PROFILE_CASES[profile]
    db_path = Path(
        os.environ.get(
            "OPENVIKING_STARTUP_E2E_DB_PATH",
            str(_resolve_profile_db_path(profile)),
        )
    )
    config_path = Path(
        os.environ.get("OPENVIKING_STARTUP_E2E_CONFIG_PATH", str(default_case.config_path))
    )
    source = os.environ.get("OPENVIKING_STARTUP_E2E_SOURCE", default_case.ingest_source)

    return [
        ProfileCase(
            name=default_case.name,
            db_path=db_path,
            config_path=config_path,
            ingest_source=source,
            query_profile=default_case.query_profile,
            query_source=source if default_case.query_profile != "yoyo" else None,
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
    response = client.request(method, path, params=params, json=payload)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError(f"{method} {path} returned non-object payload")
    return body


def _derive_keyword(item: dict[str, Any]) -> str:
    attrs = item.get("attrs") if isinstance(item.get("attrs"), dict) else {}
    candidates = [
        str(attrs.get("title", "")).strip(),
        str(item.get("text", "")).strip(),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        for part in (segment.strip() for segment in candidate.split("|")):
            if len(part) >= 2:
                return part[:32]
        return candidate[:32]
    return ""


def _parse_jsonl_rows(content: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _event_identity_from_row(row: dict[str, Any], *, case_name: str, source: str) -> tuple[str, str]:
    try:
        event = parse_event(row, include_evidence=True)
    except ValueError as exc:
        raise RuntimeError(f"[{case_name}] {source} first row is invalid: {exc}") from exc
    return event.id, event.type


def _health_check(*, client: httpx.Client) -> None:
    body = _call_json(client=client, method="GET", path="/health")
    if body.get("status") != "ok":
        raise RuntimeError(f"health check failed: {body}")


def _wait_processed(*, client: httpx.Client, timeout: float) -> None:
    body = _call_json(
        client=client,
        method="POST",
        path="/api/v1/system/wait",
        payload={"timeout": timeout},
    )
    if body.get("status") != "ok":
        raise RuntimeError(f"wait_processed failed: {body}")


def _delete_output_uri(*, client: httpx.Client, uri: str, ignore_missing: bool) -> None:
    response = client.delete("/api/v1/fs", params={"uri": uri})
    if response.status_code == 404 and ignore_missing:
        return
    response.raise_for_status()


def _reset_outputs(
    *,
    client: httpx.Client,
    case: ProfileCase,
    user_space: str,
    ignore_missing: bool,
) -> None:
    for uri in _expected_output_uris(case, user_space):
        _delete_output_uri(client=client, uri=uri, ignore_missing=ignore_missing)


def _run_ingest(
    *,
    client: httpx.Client,
    case: ProfileCase,
    user_space: str,
    dry_run: bool,
) -> dict[str, Any]:
    payload = {
        "db_path": str(case.db_path),
        "user_space": user_space,
        "source": case.ingest_source,
        "config_path": str(case.config_path),
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
    if str(result.get("db_path", "")) != str(case.db_path):
        raise RuntimeError(
            f"[{case.name}] ingest db_path mismatch: expected {case.db_path}, actual {result.get('db_path')}"
        )
    if int(result.get("failed", 0)) != 0:
        errors = result.get("errors") or []
        error_suffix = f" errors={errors}" if errors else ""
        raise RuntimeError(
            f"[{case.name}] ingest reported failures: {result.get('failed')}{error_suffix}"
        )
    return result


def _query_localdb(
    *,
    client: httpx.Client,
    user_space: str,
    source: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    body = _call_json(
        client=client,
        method="POST",
        path="/api/v1/localdb/query",
        payload={"user_space": user_space, "source": source, **payload},
    )
    if body.get("status") != "ok":
        raise RuntimeError(f"[{source}] localdb query failed: {body}")
    result = body.get("result") or {}
    if not isinstance(result, dict):
        raise RuntimeError(f"[{source}] localdb query returned invalid result payload")
    return result


def _get_event(
    *,
    client: httpx.Client,
    user_space: str,
    source: str,
    event_id: str,
) -> dict[str, Any]:
    body = _call_json(
        client=client,
        method="GET",
        path="/api/v1/localdb/event",
        params={
            "user_space": user_space,
            "source": source,
            "event_id": event_id,
        },
    )
    if body.get("status") != "ok":
        raise RuntimeError(f"[{source}] get_event failed: {body}")
    result = body.get("result") or {}
    if not isinstance(result, dict):
        raise RuntimeError(f"[{source}] get_event returned invalid result payload")
    return result


def _run_query(
    *,
    client: httpx.Client,
    case: ProfileCase,
    user_space: str,
    read_limit: int,
) -> list[str]:
    summaries: list[str] = []
    sources_resp = _call_json(
        client=client,
        method="GET",
        path="/api/v1/localdb/sources",
        params={"user_space": user_space},
    )
    listed_sources = sources_resp.get("result") or []
    if not isinstance(listed_sources, list):
        raise RuntimeError(f"[{case.name}] list_sources returned invalid payload")

    for source, uri in _query_sources(case, user_space):
        if source not in listed_sources:
            raise RuntimeError(f"[{case.name}] list_sources did not contain {source}")

        content_resp = _call_json(
            client=client,
            method="GET",
            path="/api/v1/content/read",
            params={"uri": uri, "offset": 0, "limit": read_limit},
        )
        content = str(content_resp.get("result", ""))
        rows = _parse_jsonl_rows(content)
        if not rows:
            raise RuntimeError(f"[{case.name}] no jsonl rows found in {uri}")

        first = rows[0]
        first_id, first_type = _event_identity_from_row(first, case_name=case.name, source=source)

        all_result = _query_localdb(
            client=client,
            user_space=user_space,
            source=source,
            payload={"limit": min(max(len(rows), 1), 20)},
        )
        all_items = all_result.get("items") or []
        if not all_items:
            raise RuntimeError(f"[{case.name}] {source} all query returned no items")

        id_result = _query_localdb(
            client=client,
            user_space=user_space,
            source=source,
            payload={"ids": [first_id], "limit": 1},
        )
        id_items = id_result.get("items") or []
        if not id_items or str(id_items[0].get("id", "")) != first_id:
            raise RuntimeError(f"[{case.name}] {source} id query did not return expected event")

        type_result = _query_localdb(
            client=client,
            user_space=user_space,
            source=source,
            payload={"event_types": [first_type], "limit": 3},
        )
        type_items = type_result.get("items") or []
        if not type_items or not all(str(item.get("type", "")) == first_type for item in type_items):
            raise RuntimeError(f"[{case.name}] {source} type query returned unexpected event types")

        event_result = _get_event(
            client=client,
            user_space=user_space,
            source=source,
            event_id=first_id,
        )
        if str(event_result.get("id", "")) != first_id:
            raise RuntimeError(f"[{case.name}] {source} get_event returned unexpected event id")

        summaries.append(
            "query source={source} read_rows={rows} total={total} first_id={first_id} type={first_type}".format(
                source=source,
                rows=len(rows),
                total=int(all_result.get("total", 0)),
                first_id=first_id,
                first_type=first_type,
            )
        )

        keyword = _derive_keyword(first)
        if keyword:
            keyword_result = _query_localdb(
                client=client,
                user_space=user_space,
                source=source,
                payload={"keyword": keyword, "limit": 3},
            )
            keyword_total = int(keyword_result.get("total", 0))
            if keyword_total < 1:
                raise RuntimeError(f"[{case.name}] {source} keyword query returned no hits for {keyword!r}")
            summaries.append(
                f"query keyword source={source} keyword={keyword!r} hits={keyword_total}"
            )

    return summaries


def _run_probe_sync(config: ServerConfig) -> None:
    profiles = _resolve_profiles()
    user_space = os.environ.get("OPENVIKING_STARTUP_E2E_USER_SPACE", "default/default")
    wait_timeout = _env_float("OPENVIKING_STARTUP_E2E_WAIT_TIMEOUT", 120.0)
    read_limit = _env_int("OPENVIKING_STARTUP_E2E_READ_LIMIT", 200000)
    dry_run = _env_bool("OPENVIKING_STARTUP_E2E_DRY_RUN", False)
    reset_output = _env_bool("OPENVIKING_STARTUP_E2E_RESET_OUTPUT", False)
    ignore_missing = _env_bool("OPENVIKING_STARTUP_E2E_IGNORE_MISSING", True)
    base_url = _resolve_base_url(config)
    api_key = config.root_api_key or os.environ.get("OPENVIKING_API_KEY")

    runnable_profiles: list[ProfileCase] = []
    temp_config_paths: list[Path] = []
    for case in profiles:
        prepared_case, missing_reason, cleanup_path = _prepare_case_for_probe(case)
        if cleanup_path is not None:
            temp_config_paths.append(cleanup_path)
        if missing_reason:
            _print_probe(f"skip profile={case.name} reason={missing_reason}")
            continue
        if prepared_case is not None:
            runnable_profiles.append(prepared_case)

    if not runnable_profiles:
        _print_probe("skip all profiles because no runnable ingest/query inputs were found")
        for temp_config_path in temp_config_paths:
            temp_config_path.unlink(missing_ok=True)
        return

    try:
        _print_probe(
            "starting probe base_url={base_url} db_dir={db_dir} profiles={profiles} user_space={user_space} dry_run={dry_run}".format(
                base_url=base_url,
                db_dir=_history_dir(),
                profiles=",".join(case.name for case in runnable_profiles),
                user_space=user_space,
                dry_run=str(dry_run).lower(),
            )
        )

        errors: list[str] = []
        with httpx.Client(
            base_url=base_url,
            headers=_headers(api_key),
            timeout=180.0,
        ) as client:
            _health_check(client=client)
            _print_probe("GET /health status=ok")

            for case in runnable_profiles:
                try:
                    if reset_output:
                        _reset_outputs(
                            client=client,
                            case=case,
                            user_space=user_space,
                            ignore_missing=ignore_missing,
                        )
                        _print_probe(f"DELETE /api/v1/fs profile={case.name} status=ok")

                    ingest_result = _run_ingest(
                        client=client,
                        case=case,
                        user_space=user_space,
                        dry_run=dry_run,
                    )
                    _print_probe(
                        "POST /api/v1/localdb/ingest profile={name} db_path={db_path} source={source} written={written} failed={failed} output_uris={output_uris}".format(
                            name=case.name,
                            db_path=case.db_path,
                            source=case.ingest_source,
                            written=int(ingest_result.get("written", 0)),
                            failed=int(ingest_result.get("failed", 0)),
                            output_uris=len(ingest_result.get("output_uris") or []),
                        )
                    )

                    if dry_run:
                        continue

                    _wait_processed(client=client, timeout=wait_timeout)
                    _print_probe(f"POST /api/v1/system/wait profile={case.name} status=ok")

                    for line in _run_query(
                        client=client,
                        case=case,
                        user_space=user_space,
                        read_limit=read_limit,
                    ):
                        _print_probe(line)
                except Exception as exc:
                    errors.append(f"profile={case.name} error={exc}")
                    _print_probe(f"FAIL profile={case.name} error={exc}")
                    traceback.print_exc()

        if errors:
            _print_probe("overall: FAIL")
            for error in errors:
                _print_probe(error)
            return

        _print_probe("overall: PASS")
    finally:
        for temp_config_path in temp_config_paths:
            temp_config_path.unlink(missing_ok=True)


async def run_startup_probe(config: ServerConfig) -> None:
    delay_seconds = _startup_delay_seconds()
    _print_probe(f"scheduled delayed ingest/query probe in {delay_seconds:.0f}s")
    try:
        await asyncio.sleep(delay_seconds)
    except asyncio.CancelledError:
        _print_probe("cancelled before delayed probe started")
        raise

    await asyncio.to_thread(_run_probe_sync, config)
