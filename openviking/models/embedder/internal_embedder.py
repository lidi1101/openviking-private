"""Internal embedder factory for the built-in Honor embedding path."""

from functools import lru_cache
from pathlib import Path

from openviking.models.embedder.honor_embedders import HonorDenseEmbedder

INTERNAL_EMBEDDING_DIMENSION = 768
INTERNAL_EMBEDDING_MODEL = "honor-embedding"
INTERNAL_SOURCE_FUNCTION = "send_emb_request"


def get_internal_embedding_source_file() -> str:
    repo_root = Path(__file__).resolve().parents[3]
    source_file = repo_root / "emb_requests.py"
    if not source_file.exists():
        raise FileNotFoundError(f"Internal embedding source file not found: {source_file}")
    return str(source_file)


@lru_cache(maxsize=1)
def get_internal_embedder() -> HonorDenseEmbedder:
    return HonorDenseEmbedder(
        model_name=INTERNAL_EMBEDDING_MODEL,
        source_file=get_internal_embedding_source_file(),
        source_function=INTERNAL_SOURCE_FUNCTION,
        dimension=INTERNAL_EMBEDDING_DIMENSION,
    )
