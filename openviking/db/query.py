# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from openviking.server.identity import RequestContext
from openviking.storage.viking_fs import get_viking_fs
from openviking_cli.exceptions import NotFoundError

from .reader import (
    build_localdb_root_uri,
    iter_event_dicts,
    match_event,
    parse_event,
    read_events_file,
)
from .types import Event, GetEventRequest, QueryRequest, QueryResult


async def list_sources(user_space: str, ctx: RequestContext) -> list[str]:
    root_uri = build_localdb_root_uri(user_space)
    try:
        entries = await get_viking_fs().ls(root_uri, ctx=ctx)
    except (FileNotFoundError, NotFoundError):
        return []

    sources: list[str] = []
    viking_fs = get_viking_fs()
    for entry in entries:
        if not entry.get("isDir"):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        try:
            source_entries = await viking_fs.ls(f"{root_uri}/{name}", ctx=ctx)
        except (FileNotFoundError, NotFoundError):
            continue
        if not any(
            not source_entry.get("isDir") and source_entry.get("name") == "events.jsonl"
            for source_entry in source_entries
        ):
            continue
        sources.append(name)

    return sorted(sources)


async def query_events(request: QueryRequest, ctx: RequestContext) -> QueryResult:
    _validate_query_request(request)

    content = await read_events_file(request.user_space, request.source, ctx)
    if content is None:
        return QueryResult(
            user_space=request.user_space,
            source=request.source,
            total=0,
            offset=request.offset,
            limit=request.limit,
            has_more=False,
        )

    total = 0
    items: list[Event] = []
    errors: list[str] = []

    for data, error in iter_event_dicts(content):
        if error:
            errors.append(error)
            continue
        if data is None:
            continue

        try:
            event = parse_event(data, include_evidence=request.include_evidence)
        except ValueError as exc:
            errors.append(str(exc))
            continue

        if not match_event(event, request):
            continue

        match_index = total
        total += 1
        if match_index < request.offset:
            continue
        if len(items) < request.limit:
            items.append(event)

    return QueryResult(
        user_space=request.user_space,
        source=request.source,
        total=total,
        offset=request.offset,
        limit=request.limit,
        has_more=total > request.offset + request.limit,
        items=items,
        errors=errors,
    )


async def get_event(request: GetEventRequest, ctx: RequestContext) -> Event | None:
    content = await read_events_file(request.user_space, request.source, ctx)
    if content is None:
        return None

    for data, error in iter_event_dicts(content):
        if error or data is None:
            continue
        try:
            event = parse_event(data, include_evidence=request.include_evidence)
        except ValueError:
            continue
        if event.id == request.event_id:
            return event

    return None


def _validate_query_request(request: QueryRequest) -> None:
    if request.offset < 0:
        raise ValueError("offset must be >= 0")
    if request.limit <= 0:
        raise ValueError("limit must be > 0")
