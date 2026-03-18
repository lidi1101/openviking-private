# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from openviking.server.identity import RequestContext, Role
from openviking_cli.session.user_id import UserIdentifier

from .config import load_mapping_config
from .normalize import build_event
from .sqlite_reader import iter_rows, open_sqlite_readonly
from .types import IngestItemReport, IngestReport, IngestRequest
from .writer import append_jsonl


def _default_output_uri(request: IngestRequest) -> str:
    return f"viking://user/{request.user_space}/memories/localdb/{request.source}/events.jsonl"


def _resolve_output_uri(request: IngestRequest, raw_output_uri: Optional[str]) -> str:
    if not raw_output_uri:
        return _default_output_uri(request)
    return raw_output_uri.format(
        user_space=request.user_space,
        source=request.source,
        db_path=request.db_path,
    )


async def ingest(request: IngestRequest) -> IngestReport:
    if not os.path.exists(request.db_path):
        raise FileNotFoundError(f"db not found: {request.db_path}")

    output_uri = _default_output_uri(request)

    items = load_mapping_config(request.config_path)

    report = IngestReport(db_path=request.db_path, output_uri=output_uri)

    conn, opened_via_copy, _tmp = open_sqlite_readonly(request.db_path)
    report.opened_via_copy = opened_via_copy

    # Use ROOT role for local CLI import; user/account are derived from user_space string.
    # user_space is usually "<account>/<user>" or "<account>/<user>/<agent>".
    parts = request.user_space.split("/")
    account = parts[0] if len(parts) >= 1 else "default"
    user = parts[1] if len(parts) >= 2 else "default"
    agent = parts[2] if len(parts) >= 3 else "default"
    ctx = RequestContext(user=UserIdentifier(account, user, agent), role=Role.ROOT)

    try:
        for item in items:
            item_output_uri = _resolve_output_uri(request, item.output_uri)
            item_report = IngestItemReport(id=item.id, output_uri=item_output_uri)
            report.items.append(item_report)
            if item_output_uri not in report.output_uris:
                report.output_uris.append(item_output_uri)

            params: Dict[str, Any] = {}
            if request.since is not None:
                params["since"] = request.since
                params["since_ts"] = request.since

            try:
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
                        db_path=request.db_path,
                    )

                    if len(report.samples) < 5:
                        report.samples.append(event)

                    if not request.dry_run:
                        await append_jsonl(item_output_uri, event, ctx=ctx)
                        item_report.written += 1
                        report.written += 1

            except Exception as e:
                item_report.failed += 1
                report.failed += 1
                report.errors.append(f"extract[{item.id}] failed: {e}")

    finally:
        try:
            conn.close()
        except Exception:
            pass

    return report
