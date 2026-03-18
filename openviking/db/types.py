# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ExtractItem:
    id: str
    type: str
    sql: str
    columns: Dict[str, str] = field(default_factory=dict)
    table: Optional[str] = None
    output_uri: Optional[str] = None


@dataclass
class IngestRequest:
    db_path: str
    user_space: str
    source: str
    config_path: str
    since: Optional[str] = None
    dry_run: bool = False
    redact: bool = True


@dataclass
class IngestItemReport:
    id: str
    output_uri: Optional[str] = None
    rows: int = 0
    written: int = 0
    failed: int = 0


@dataclass
class IngestReport:
    db_path: str
    output_uri: str
    output_uris: List[str] = field(default_factory=list)
    total_rows: int = 0
    written: int = 0
    failed: int = 0
    opened_via_copy: bool = False
    items: List[IngestItemReport] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    samples: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Event:
    id: str
    type: str
    time: Dict[str, Any]
    text: str
    attrs: Dict[str, Any] = field(default_factory=dict)
    entities: List[Dict[str, Any]] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    privacy: Dict[str, Any] = field(default_factory=dict)
