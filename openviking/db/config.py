# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .types import ExtractItem


def _resolve_mapping_path(config_path: str) -> Path:
    candidate = Path(config_path).expanduser()
    if candidate.exists():
        return candidate

    repo_relative = Path(__file__).resolve().parents[2] / candidate
    if repo_relative.exists():
        return repo_relative

    raise FileNotFoundError(f"mapping_config not found: {config_path}")


def load_mapping_config(config_path: str) -> List[ExtractItem]:
    p = _resolve_mapping_path(config_path)

    if p.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    elif p.suffix.lower() == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"Unsupported mapping_config format: {p.suffix}")

    if not isinstance(data, dict):
        raise ValueError("mapping_config must be a dict with key 'extract'")

    extract = data.get("extract")
    if not isinstance(extract, list) or not extract:
        raise ValueError("mapping_config.extract must be a non-empty list")

    items: List[ExtractItem] = []
    for idx, raw in enumerate(extract):
        if not isinstance(raw, dict):
            raise ValueError(f"extract[{idx}] must be an object")
        for k in ("id", "type", "sql"):
            if k not in raw or not raw[k]:
                raise ValueError(f"extract[{idx}] missing required field: {k}")
        columns = raw.get("columns") or {}
        if not isinstance(columns, dict):
            raise ValueError(f"extract[{idx}].columns must be an object")
        items.append(
            ExtractItem(
                id=str(raw["id"]),
                type=str(raw["type"]),
                sql=str(raw["sql"]),
                columns={str(k): str(v) for k, v in columns.items()},
                table=str(raw["table"]) if raw.get("table") else None,
                output_uri=str(raw["output_uri"]) if raw.get("output_uri") else None,
            )
        )

    return items
