# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from openviking.storage.viking_fs import get_viking_fs
from openviking.server.identity import RequestContext


def append_jsonl(uri: str, obj: Dict[str, Any], ctx: Optional[RequestContext]) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    vfs = get_viking_fs()
    # VikingFS is async; we keep writer async-friendly by returning coroutine in caller.
    return vfs.append_file(uri, line, ctx=ctx)
