from __future__ import annotations

import asyncio
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Sequence

from openviking.prompts import render_prompt
from openviking.server.identity import RequestContext
from openviking.storage.viking_fs import get_viking_fs
from openviking_cli.exceptions import NotFoundError
from openviking_cli.utils.config import get_openviking_config
from openviking_cli.utils.logger import get_logger

from .reader import iter_event_dicts

logger = get_logger(__name__)

LOCALDB_SUMMARY_ROOT_URIS = ("viking://yoyo", "viking://sense")
LOCALDB_SUMMARY_MAX_ITEMS = 50
LOCALDB_SUMMARY_MAX_TEXT_CHARS = 240


@dataclass
class LocalDbSummaryResult:
    jsonl_uris: List[str] = field(default_factory=list)
    summary_uris: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def _summary_uri_for_jsonl(jsonl_uri: str) -> str:
    if jsonl_uri.endswith(".jsonl"):
        return jsonl_uri[: -len(".jsonl")] + ".md"
    return jsonl_uri + ".md"


def _compact_text(value: object, max_chars: int = LOCALDB_SUMMARY_MAX_TEXT_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _pick_record_text(event: Dict[str, object]) -> str:
    text = str(event.get("text", "")).strip()
    if text:
        return _compact_text(text)

    attrs = event.get("attrs")
    if isinstance(attrs, dict):
        for key in ("title", "summary", "content", "description", "name"):
            value = attrs.get(key)
            if value:
                return _compact_text(value)

    return ""


def _record_brief(event: Dict[str, object]) -> str:
    event_id = str(event.get("id", "")).strip()
    event_type = str(event.get("type", "")).strip() or "unknown"

    time_obj = event.get("time")
    ts = ""
    if isinstance(time_obj, dict):
        ts = str(time_obj.get("ts", "")).strip()

    parts = [
        f"id={event_id}" if event_id else None,
        f"type={event_type}",
        f"ts={ts}" if ts else None,
    ]
    text = _pick_record_text(event)
    if text:
        parts.append(f"text={text}")
    return " | ".join(part for part in parts if part)


def _build_jsonl_digest(content: str) -> str:
    valid_count = 0
    invalid_lines = 0
    type_counter: Counter[str] = Counter()
    earliest_ts: Optional[str] = None
    latest_ts: Optional[str] = None
    recent_records: Deque[str] = deque(maxlen=LOCALDB_SUMMARY_MAX_ITEMS)

    for event_dict, error in iter_event_dicts(content):
        if error:
            invalid_lines += 1
            continue
        if not event_dict:
            continue

        valid_count += 1
        event_type = str(event_dict.get("type", "")).strip() or "unknown"
        type_counter[event_type] += 1

        time_obj = event_dict.get("time")
        ts = ""
        if isinstance(time_obj, dict):
            ts = str(time_obj.get("ts", "")).strip()
        if ts:
            if earliest_ts is None or ts < earliest_ts:
                earliest_ts = ts
            if latest_ts is None or ts > latest_ts:
                latest_ts = ts

        recent_records.append(_record_brief(event_dict))

    type_lines = (
        "\n".join(f"- {event_type}: {count}" for event_type, count in type_counter.most_common(12))
        if type_counter
        else "- None"
    )
    record_lines = (
        "\n".join(f"- {record}" for record in recent_records)
        if recent_records
        else "- None"
    )

    return "\n".join(
        [
            f"Valid records: {valid_count}",
            f"Invalid lines: {invalid_lines}",
            f"Earliest timestamp: {earliest_ts or 'unknown'}",
            f"Latest timestamp: {latest_ts or 'unknown'}",
            "",
            "[Event Type Counts]",
            type_lines,
            "",
            f"[Recent {len(recent_records)} Records]",
            record_lines,
        ]
    )


async def _generate_summary_markdown(file_uri: str, content: str) -> str:
    vlm = get_openviking_config().vlm
    file_name = file_uri.rsplit("/", 1)[-1]
    digest = _build_jsonl_digest(content)

    logger.info("[LocalDbSummary] VLM available: %s for file: %s", vlm.is_available(), file_name)

    if not vlm.is_available():
        logger.warning("[LocalDbSummary] VLM is not available, using fallback summary for: %s", file_uri)
        return "\n".join(
            [
                f"# {file_name}",
                "",
                "## Summary",
                "VLM is not available, so this file contains a local fallback summary.",
                "",
                "## Digest",
                "```text",
                digest,
                "```",
            ]
        )

    prompt = render_prompt(
        "semantic.localdb_jsonl_summary",
        {
            "file_name": file_name,
            "file_uri": file_uri,
            "digest": digest,
        },
    )
    summary = await vlm.get_completion_async(prompt)
    return summary.strip()


async def _list_jsonl_files(root_uri: str, ctx: RequestContext) -> List[str]:
    try:
        entries = await get_viking_fs().tree(uri=root_uri, level_limit=32, node_limit=10000, ctx=ctx)
    except (FileNotFoundError, NotFoundError):
        return []

    return [
        str(entry.get("uri", ""))
        for entry in entries
        if not entry.get("isDir", False) and str(entry.get("uri", "")).endswith(".jsonl")
    ]


async def summarize_workspace_jsonl_files(
    ctx: RequestContext,
    root_uris: Sequence[str] = LOCALDB_SUMMARY_ROOT_URIS,
) -> LocalDbSummaryResult:
    viking_fs = get_viking_fs()
    result = LocalDbSummaryResult()

    jsonl_uris: List[str] = []
    for root_uri in root_uris:
        logger.info("[LocalDbSummary] Scanning root_uri: %s", root_uri)
        uris = await _list_jsonl_files(root_uri, ctx)
        logger.info("[LocalDbSummary] Found %d jsonl files in %s", len(uris), root_uri)
        jsonl_uris.extend(uris)

    # Preserve order while deduplicating across overlapping roots.
    seen = set()
    ordered_jsonl_uris = []
    for uri in jsonl_uris:
        if not uri or uri in seen:
            continue
        seen.add(uri)
        ordered_jsonl_uris.append(uri)

    result.jsonl_uris = ordered_jsonl_uris
    if not ordered_jsonl_uris:
        return result

    semaphore = asyncio.Semaphore(4)

    async def summarize_one(jsonl_uri: str) -> None:
        async with semaphore:
            try:
                logger.info("[LocalDbSummary] Generating summary for: %s", jsonl_uri)
                content = await viking_fs.read_file(jsonl_uri, ctx=ctx)
                summary_md = await _generate_summary_markdown(jsonl_uri, content)
                summary_uri = _summary_uri_for_jsonl(jsonl_uri)
                await viking_fs.write_file(summary_uri, summary_md, ctx=ctx)
                result.summary_uris.append(summary_uri)
                logger.info("[LocalDbSummary] Summary written to: %s", summary_uri)
            except Exception as exc:
                logger.warning("Failed to summarize localdb jsonl %s: %s", jsonl_uri, exc)
                result.errors.append(f"{jsonl_uri}: {exc}")

    await asyncio.gather(*(summarize_one(uri) for uri in ordered_jsonl_uris))
    logger.info("[LocalDbSummary] Completed. Total jsonl: %d, Summaries: %d, Errors: %d",
                len(ordered_jsonl_uris), len(result.summary_uris), len(result.errors))
    return result
