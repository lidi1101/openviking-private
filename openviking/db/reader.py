# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional, Tuple

from openviking.server.identity import RequestContext
from openviking.storage.viking_fs import get_viking_fs
from openviking_cli.exceptions import NotFoundError

from .types import Event, QueryRequest

FIXED_SOURCE_URIS = {
    "userpreference": "viking://sense/pcevent/default/event.jsonl",
    "userinformation": "viking://yoyo/userinformation/default/userinformation.jsonl",
    "usertendencies": "viking://yoyo/usertendencies/default/usertendencies.jsonl",
}


def normalize_source_name(source: str) -> str:
    return "".join(ch for ch in str(source) if ch.isalnum()).casefold()


def build_localdb_root_uri(user_space: str) -> str:
    return f"viking://user/{user_space}/memories/localdb"


def build_events_uri(user_space: str, source: str) -> str:
    mapped_uri = FIXED_SOURCE_URIS.get(normalize_source_name(source))
    if mapped_uri:
        return mapped_uri
    return f"{build_localdb_root_uri(user_space)}/{source}/events.jsonl"


async def read_events_file(user_space: str, source: str, ctx: RequestContext) -> Optional[str]:
    uri = build_events_uri(user_space, source)
    try:
        return await get_viking_fs().read_file(uri, ctx=ctx)
    except (FileNotFoundError, NotFoundError):
        return None


def iter_event_dicts(content: str) -> Iterator[Tuple[Optional[Dict[str, Any]], Optional[str]]]:
    for line_no, line in enumerate(content.splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            yield None, f"line {line_no}: invalid json: {exc.msg}"
            continue
        if not isinstance(data, dict):
            yield None, f"line {line_no}: event must be a json object"
            continue
        yield data, None


def _derive_event_id(data: Dict[str, Any]) -> str:
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_event(data: Dict[str, Any], include_evidence: bool = True) -> Event:
    event_id = str(data.get("id", "")).strip()
    if not event_id:
        event_id = _derive_event_id(data)

    event_type = str(data.get("type", "")).strip()
    if not event_type:
        raise ValueError(f"event {event_id} missing type")

    time_obj = data.get("time")
    if not isinstance(time_obj, dict):
        time_obj = {"ts": "", "precision": "unknown"}

    text = data.get("text")
    if text is None:
        text = ""

    attrs = data.get("attrs")
    if not isinstance(attrs, dict):
        attrs = {}

    entities_raw = data.get("entities")
    entities = (
        [item for item in entities_raw if isinstance(item, dict)]
        if isinstance(entities_raw, list)
        else []
    )

    evidence = data.get("evidence")
    if not include_evidence or not isinstance(evidence, dict):
        evidence = {}

    privacy = data.get("privacy")
    if not isinstance(privacy, dict):
        privacy = {}

    return Event(
        id=event_id,
        type=event_type,
        time=time_obj,
        text=str(text),
        attrs=attrs,
        entities=entities,
        evidence=evidence,
        privacy=privacy,
    )


def match_event(event: Event, request: QueryRequest) -> bool:
    ids = set(request.ids)
    if ids and event.id not in ids:
        return False

    event_types = set(request.event_types)
    if event_types and event.type not in event_types:
        return False

    event_ts = _parse_iso_ts(event.time.get("ts"))
    if request.since:
        since_ts = _parse_iso_ts(request.since)
        if since_ts is None:
            raise ValueError(f"invalid since timestamp: {request.since}")
        if event_ts is None or event_ts < since_ts:
            return False

    if request.until:
        until_ts = _parse_iso_ts(request.until)
        if until_ts is None:
            raise ValueError(f"invalid until timestamp: {request.until}")
        if event_ts is None or event_ts > until_ts:
            return False

    if request.keyword:
        keyword = request.keyword.casefold()
        if keyword not in event.text.casefold():
            return False

    return True


def _parse_iso_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
