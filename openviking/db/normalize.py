# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse, urlunparse


def _parse_time(value: Any) -> Dict[str, Any]:
    if value is None:
        return {"ts": "", "precision": "unknown"}

    # unix seconds / ms
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e12:  # ms
            dt = datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)
            return {"ts": dt.isoformat(), "precision": "millisecond"}
        dt = datetime.fromtimestamp(v, tz=timezone.utc)
        return {"ts": dt.isoformat(), "precision": "second"}

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return {"ts": "", "precision": "unknown"}
        # try iso
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return {"ts": dt.astimezone(timezone.utc).isoformat(), "precision": "second"}
        except Exception:
            pass
        # try sqlite datetime "YYYY-MM-DD HH:MM:SS"
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
                return {"ts": dt.isoformat(), "precision": "second"}
            except Exception:
                continue

    return {"ts": str(value), "precision": "unknown"}


def _normalize_url(url: str, redact: bool) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url)
        if redact:
            p = p._replace(query="", fragment="")
        return urlunparse(p)
    except Exception:
        return url


def build_event(
    *,
    source: str,
    query_id: str,
    event_type: str,
    row: Dict[str, Any],
    columns: Dict[str, str],
    redact: bool,
    db_path: str,
) -> Dict[str, Any]:
    # map columns
    def get_col(key: str) -> Any:
        col = columns.get(key)
        return row.get(col) if col else None

    pk = get_col("pk")
    time_val = get_col("time")
    url_val = get_col("url")
    title_val = get_col("title")

    time_obj = _parse_time(time_val)

    url_norm = _normalize_url(str(url_val) if url_val is not None else "", redact=redact)
    host = ""
    try:
        host = urlparse(url_norm).netloc
    except Exception:
        host = ""

    parts = []
    if time_obj.get("ts"):
        parts.append(time_obj["ts"])
    if event_type:
        parts.append(event_type)
    if host:
        parts.append(host)
    if title_val:
        parts.append(str(title_val))
    if url_norm and not host:
        parts.append(url_norm)

    text = " ".join([p for p in parts if p])

    row_ref = str(pk) if pk is not None else hashlib.sha256(repr(sorted(row.items())).encode("utf-8")).hexdigest()
    raw_id = f"{source}|{event_type}|{query_id}|{row_ref}"
    eid = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()

    attrs: Dict[str, Any] = {}
    if url_norm:
        attrs["url"] = url_norm
    if title_val is not None:
        attrs["title"] = str(title_val)

    entities = []
    if host:
        entities.append({"kind": "url", "host": host})

    evidence = {
        "db": str(db_path),
        "query_id": query_id,
        "row_ref": row_ref,
        "columns_used": columns,
    }

    return {
        "id": eid,
        "type": event_type,
        "time": time_obj,
        "text": text,
        "attrs": attrs,
        "entities": entities,
        "evidence": evidence,
        "privacy": {"redact": bool(redact)},
    }
