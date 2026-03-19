# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0
"""LocalDB ingest and query endpoints."""

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from openviking.db.ingest import ingest
from openviking.db.query import get_event, list_sources, query_events
from openviking.db.types import GetEventRequest, IngestRequest, QueryRequest
from openviking.server.auth import get_request_context
from openviking.server.identity import RequestContext
from openviking.server.models import Response

router = APIRouter(prefix="/api/v1/localdb", tags=["localdb"])


class IngestBody(BaseModel):
    db_path: str | None = None
    user_space: str
    source: str
    config_path: str
    since: str | None = None
    dry_run: bool = False
    redact: bool = True


class QueryBody(BaseModel):
    user_space: str
    source: str
    event_types: list[str] = []
    ids: list[str] = []
    since: str | None = None
    until: str | None = None
    keyword: str | None = None
    offset: int = 0
    limit: int = 100
    include_evidence: bool = True


@router.post("/ingest")
async def ingest_localdb(
    body: IngestBody,
    _ctx: RequestContext = Depends(get_request_context),
):
    # Authorization: only ROOT can ingest local db via server API.
    if _ctx.role.value != "root":
        # keep it simple; server error handler will wrap
        raise PermissionError("localdb ingest requires ROOT")

    report = await ingest(
        IngestRequest(
            db_path=body.db_path or "",
            user_space=body.user_space,
            source=body.source,
            config_path=body.config_path,
            since=body.since,
            dry_run=body.dry_run,
            redact=body.redact,
        )
    )
    return Response(status="ok", result=report.__dict__)


@router.get("/sources")
async def list_localdb_sources(
    user_space: str = Query(..., description="User space"),
    _ctx: RequestContext = Depends(get_request_context),
):
    sources = await list_sources(user_space, _ctx)
    return Response(status="ok", result=sources)


@router.post("/query")
async def query_localdb(
    body: QueryBody,
    _ctx: RequestContext = Depends(get_request_context),
):
    result = await query_events(
        QueryRequest(
            user_space=body.user_space,
            source=body.source,
            event_types=body.event_types,
            ids=body.ids,
            since=body.since,
            until=body.until,
            keyword=body.keyword,
            offset=body.offset,
            limit=body.limit,
            include_evidence=body.include_evidence,
        ),
        _ctx,
    )
    return Response(status="ok", result=asdict(result))


@router.get("/event")
async def get_localdb_event(
    user_space: str = Query(..., description="User space"),
    source: str = Query(..., description="Source"),
    event_id: str = Query(..., description="Event ID"),
    include_evidence: bool = Query(True, description="Whether to include evidence"),
    _ctx: RequestContext = Depends(get_request_context),
):
    event = await get_event(
        GetEventRequest(
            user_space=user_space,
            source=source,
            event_id=event_id,
            include_evidence=include_evidence,
        ),
        _ctx,
    )
    return Response(status="ok", result=asdict(event) if event is not None else None)
