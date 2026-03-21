# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from openviking.server.identity import RequestContext, Role
from openviking.pyagfs.exceptions import AGFSClientError
from openviking.storage.viking_fs import get_viking_fs
from openviking_cli.exceptions import NotFoundError
from openviking_cli.session.user_id import UserIdentifier

from .config import load_mapping_config
from .normalize import build_event
from .sqlite_reader import iter_rows, open_sqlite_readonly
from .summary import summarize_workspace_jsonl_files
from .types import IngestItemReport, IngestReport, IngestRequest
from .writer import append_jsonl_lines

FIXED_SOURCE_OUTPUT_URIS = {
    "userpreference": "viking://sense/pcevent/default/event.jsonl",
}

YOYO_TABLE_OUTPUT_URIS = {
    "userinformation": "viking://yoyo/userinformation/default/userinformation.jsonl",
    "usertendencies": "viking://yoyo/usertendencies/default/usertendencies.jsonl",
}

MINIMAL_EVENT_OUTPUT_URIS = {
    "viking://sense/pcevent/default/event.jsonl",
    "viking://yoyo/userinformation/default/userinformation.jsonl",
    "viking://yoyo/usertendencies/default/usertendencies.jsonl",
}


def _normalize_name(value: Optional[str]) -> str:
    if not value:
        return ""
    return "".join(ch for ch in value if ch.isalnum()).casefold()


def _resolve_db_path(request: IngestRequest) -> str:
    db_path = request.db_path.strip()
    if not db_path:
        raise ValueError("db_path is required")
    return db_path


def _resolve_output_uri(
    request: IngestRequest,
    *,
    table: Optional[str],
    raw_output_uri: Optional[str],
    db_path: str,
) -> str:
    mapped_source_uri = FIXED_SOURCE_OUTPUT_URIS.get(_normalize_name(request.source))
    if mapped_source_uri:
        return mapped_source_uri

    if not raw_output_uri:
        table_key = _normalize_name(table)
        mapped_uri = YOYO_TABLE_OUTPUT_URIS.get(table_key)
        if mapped_uri:
            return mapped_uri
        raise ValueError(f"extract table is not mapped to a VikingFS target: {table!r}")
    return raw_output_uri.format(
        user_space=request.user_space,
        source=request.source,
        db_path=db_path,
    )


def _trim_event_fields_for_output(event: Dict[str, Any], output_uri: str) -> Dict[str, Any]:
    if output_uri not in MINIMAL_EVENT_OUTPUT_URIS:
        return event

    trimmed = dict(event)
    trimmed.pop("id", None)
    trimmed.pop("attrs", None)
    trimmed.pop("entities", None)
    trimmed.pop("evidence", None)
    return trimmed


async def ingest(request: IngestRequest) -> IngestReport:
    db_path = _resolve_db_path(request)
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"db not found: {db_path}")

    output_uri = ""

    items = load_mapping_config(request.config_path)

    report = IngestReport(db_path=db_path, output_uri=output_uri)

    conn, opened_via_copy, _tmp = open_sqlite_readonly(db_path)
    report.opened_via_copy = opened_via_copy

    # Use ROOT role for local CLI import; user/account are derived from user_space string.
    # user_space is usually "<account>/<user>" or "<account>/<user>/<agent>".
    parts = request.user_space.split("/")
    account = parts[0] if len(parts) >= 1 else "default"
    user = parts[1] if len(parts) >= 2 else "default"
    agent = parts[2] if len(parts) >= 3 else "default"
    ctx = RequestContext(user=UserIdentifier(account, user, agent), role=Role.ROOT)

    try:
        cleared_output_uris: set[str] = set()
        for item in items:
            item_report = IngestItemReport(id=item.id)
            report.items.append(item_report)

            params: Dict[str, Any] = {}
            if request.since is not None:
                params["since"] = request.since
                params["since_ts"] = request.since

            try:
                item_output_uri = _resolve_output_uri(
                    request,
                    table=item.table,
                    raw_output_uri=item.output_uri,
                    db_path=db_path,
                )
                item_report.output_uri = item_output_uri
                if item_output_uri not in report.output_uris:
                    report.output_uris.append(item_output_uri)
                    if not report.output_uri:
                        report.output_uri = item_output_uri

                if (
                    not request.dry_run
                    and item_output_uri in MINIMAL_EVENT_OUTPUT_URIS
                    and item_output_uri not in cleared_output_uris
                ):
                    try:
                        vfs = get_viking_fs()
                        try:
                            await vfs.stat(item_output_uri, ctx=ctx)
                        except (FileNotFoundError, NotFoundError, AGFSClientError):
                            pass
                        else:
                            await vfs.rm(item_output_uri, ctx=ctx)
                    except (FileNotFoundError, NotFoundError, AGFSClientError):
                        pass
                    cleared_output_uris.add(item_output_uri)

                pending_events = []
                for row in iter_rows(conn, item.sql, params=params):
                    item_report.rows += 1
                    report.total_rows += 1

                    row_dict = {k: row[k] for k in row.keys()}
                    event = build_event(
                        source=request.source,
                        query_id=item.id,
                        event_type=item.type,
                        row=row_dict,
                        columns=item.columns,
                        redact=request.redact,
                        db_path=db_path,
                    )
                    event = _trim_event_fields_for_output(event, item_output_uri)

                    if len(report.samples) < 5:
                        report.samples.append(event)

                    if not request.dry_run:
                        pending_events.append(event)

                if not request.dry_run and pending_events:
                    await append_jsonl_lines(item_output_uri, pending_events, ctx=ctx)
                    item_report.written += len(pending_events)
                    report.written += len(pending_events)

            except Exception as e:
                item_report.failed += 1
                report.failed += 1
                report.errors.append(f"extract[{item.id}] failed: {e}")

    finally:
        try:
            conn.close()
        except Exception:
            pass

    if not request.dry_run and report.written > 0:
        try:
            summary_result = await summarize_workspace_jsonl_files(ctx)
            report.summary_output_uris.extend(summary_result.summary_uris)
            report.summary_errors.extend(summary_result.errors)
        except Exception as e:
            report.summary_errors.append(f"localdb summary failed: {e}")

    return report
