# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional

from openviking.storage.viking_fs import get_viking_fs
from openviking.server.identity import RequestContext


def format_jsonl_line(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


def append_jsonl_lines(
    uri: str,
    objs: Iterable[Dict[str, Any]],
    ctx: Optional[RequestContext],
) -> None:
    payload = "".join(format_jsonl_line(obj) for obj in objs)
    if not payload:
        return None
    vfs = get_viking_fs()
    # VikingFS is async; we keep writer async-friendly by returning coroutine in caller.
    return vfs.append_file(uri, payload, ctx=ctx)


def append_jsonl(uri: str, obj: Dict[str, Any], ctx: Optional[RequestContext]) -> None:
    return append_jsonl_lines(uri, [obj], ctx=ctx)
