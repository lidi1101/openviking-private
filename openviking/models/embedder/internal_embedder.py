"""Internal embedder factory for the built-in Honor embedding path."""

import os
import sys
from functools import lru_cache
from pathlib import Path

from openviking.models.embedder.honor_embedders import HonorDenseEmbedder

INTERNAL_EMBEDDING_DIMENSION = 768
INTERNAL_EMBEDDING_MODEL = "honor-embedding"
INTERNAL_SOURCE_FUNCTION = "send_emb_request"


def _auto_probe_internal_embedding_sources_enabled() -> bool:
    raw = os.environ.get("OPENVIKING_AUTO_DISCOVER_HONOR_SOURCE_FILE", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _candidate_internal_embedding_source_files() -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add_candidate(path: Path | None) -> None:
        if path is None:
            return
        resolved = path.expanduser().resolve(strict=False)
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(resolved)

    env_source_file = os.environ.get("HONOR_EMBED_SOURCE_FILE")
    if env_source_file:
        add_candidate(Path(env_source_file))

    if not _auto_probe_internal_embedding_sources_enabled():
        return candidates

    meipass_root = getattr(sys, "_MEIPASS", None)
    if meipass_root:
        add_candidate(Path(meipass_root) / "emb_requests.py")

    executable = getattr(sys, "executable", None)
    if executable:
        add_candidate(Path(executable).resolve(strict=False).parent / "emb_requests.py")

    repo_root = Path(__file__).resolve().parents[3]
    add_candidate(repo_root / "emb_requests.py")

    return candidates


def get_internal_embedding_source_file() -> str:
    candidates = _candidate_internal_embedding_source_files()
    for source_file in candidates:
        if source_file.exists():
            return str(source_file)

    candidate_paths = "\n".join(f"- {candidate}" for candidate in candidates)
    raise FileNotFoundError(
        "Internal embedding source file not found. Checked:\n"
        f"{candidate_paths}"
    )


@lru_cache(maxsize=1)
def get_internal_embedder() -> HonorDenseEmbedder:
    return HonorDenseEmbedder(
        model_name=INTERNAL_EMBEDDING_MODEL,
        source_file=get_internal_embedding_source_file(),
        source_function=INTERNAL_SOURCE_FUNCTION,
        dimension=INTERNAL_EMBEDDING_DIMENSION,
    )
