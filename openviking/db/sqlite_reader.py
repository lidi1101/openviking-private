# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional, Tuple


def _connect_readonly(db_path: str) -> sqlite3.Connection:
    # Use URI mode=ro when possible
    uri = Path(db_path).absolute().as_uri()
    # as_uri gives file:///D:/... on Windows
    return sqlite3.connect(f"{uri}?mode=ro", uri=True)


def open_sqlite_readonly(db_path: str) -> Tuple[sqlite3.Connection, bool, Optional[str]]:
    """Open sqlite in readonly mode.

    Returns:
        (conn, opened_via_copy, temp_copy_path)
    """
    try:
        conn = _connect_readonly(db_path)
        conn.row_factory = sqlite3.Row
        return conn, False, None
    except Exception:
        # Fallback: copy then open
        src = Path(db_path)
        if not src.exists():
            raise
        tmp_dir = Path(tempfile.mkdtemp(prefix="openviking-localdb-"))
        dst = tmp_dir / src.name
        shutil.copy2(src, dst)
        conn = _connect_readonly(str(dst))
        conn.row_factory = sqlite3.Row
        return conn, True, str(dst)


def iter_rows(
    conn: sqlite3.Connection,
    sql: str,
    params: Optional[Dict[str, Any]] = None,
    batch_size: int = 1000,
) -> Iterator[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(sql, params or {})
    while True:
        rows = cur.fetchmany(batch_size)
        if not rows:
            break
        for r in rows:
            yield r
