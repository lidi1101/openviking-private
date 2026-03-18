# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0
"""LocalDB ingest endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from openviking.db.ingest import ingest
from openviking.db.types import IngestRequest
from openviking.server.auth import get_request_context
from openviking.server.identity import RequestContext
from openviking.server.models import Response

router = APIRouter(prefix="/api/v1/localdb", tags=["localdb"])


class IngestBody(BaseModel):
    db_path: str
    user_space: str
    source: str
    config_path: str
    since: str | None = None
    dry_run: bool = False
    redact: bool = True


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
            db_path=body.db_path,
            user_space=body.user_space,
            source=body.source,
            config_path=body.config_path,
            since=body.since,
            dry_run=body.dry_run,
            redact=body.redact,
        )
    )
    return Response(status="ok", result=report.__dict__)
