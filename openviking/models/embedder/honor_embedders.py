"""Honor embedding provider implementation."""

import base64
import hashlib
import hmac
import importlib.util
import json
import os
import urllib.parse
from email.utils import formatdate
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from openviking.models.embedder.base import DenseEmbedderBase, EmbedResult

DEFAULT_API_URL = "https://all-scenario-device-test.test.honor.com/all-scenario/rag/v1/get-embedding"
DEFAULT_MODEL = "honor-embedding"
DEFAULT_SOURCE_FUNCTION = "send_emb_request"


class HonorDenseEmbedder(DenseEmbedderBase):
    """Honor dense embedder with in-process HMAC or source-function execution."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        api_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        dimension: Optional[int] = None,
        timeout: Optional[float] = None,
        source_file: Optional[str] = None,
        source_function: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(model_name, config)

        self.api_url = api_url or os.environ.get("HONOR_EMBED_API_URL", DEFAULT_API_URL)
        self.access_key = access_key or os.environ.get("HONOR_EMBED_ACCESS_KEY")
        self.secret_key = secret_key or os.environ.get("HONOR_EMBED_SECRET_KEY")
        self.timeout = float(timeout or os.environ.get("HONOR_EMBED_TIMEOUT", "60"))
        self.source_file = source_file or os.environ.get("HONOR_EMBED_SOURCE_FILE")
        self.source_function = source_function or os.environ.get(
            "HONOR_EMBED_SOURCE_FUNCTION", DEFAULT_SOURCE_FUNCTION
        )
        self._cached_source_callable: Optional[Callable[[List[str]], Any]] = None

        if not self._can_use_source_file() and (not self.access_key or not self.secret_key):
            raise ValueError(
                "Honor provider requires either source_file or both access_key and secret_key"
            )

        self._dimension = dimension or self._detect_dimension()

    def _can_use_source_file(self) -> bool:
        return bool(self.source_file and Path(self.source_file).exists())

    def _load_source_callable(self) -> Callable[[List[str]], Any]:
        if self._cached_source_callable is not None:
            return self._cached_source_callable

        if not self.source_file:
            raise RuntimeError("Honor source_file is not configured")

        source_path = Path(self.source_file)
        if not source_path.exists():
            raise RuntimeError(f"Honor source_file does not exist: {source_path}")

        spec = importlib.util.spec_from_file_location("honor_embed_source", str(source_path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Failed to load Honor source file: {source_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        embed_fn = getattr(module, self.source_function, None)
        if not callable(embed_fn):
            raise RuntimeError(
                f"Function '{self.source_function}' was not found in {source_path}"
            )

        self._cached_source_callable = embed_fn
        return embed_fn

    def _generate_signature(
        self,
        method: str,
        url: str,
        access_key: str,
        secret_key: str,
        date_str: str,
        signed_headers: List[str],
        headers: Dict[str, str],
    ) -> str:
        parsed_url = urllib.parse.urlparse(url)
        http_uri = parsed_url.path or "/"

        canonical_query_string = ""
        if parsed_url.query:
            query_pairs = urllib.parse.parse_qsl(parsed_url.query, keep_blank_values=True)
            query_pairs = [
                (urllib.parse.quote(key, safe=""), urllib.parse.quote(value, safe=""))
                for key, value in query_pairs
            ]
            query_pairs.sort(key=lambda item: item[0])
            canonical_query_string = "&".join(f"{key}={value}" for key, value in query_pairs)

        signed_headers_string = ""
        for header_name in signed_headers:
            matched = next(
                (
                    f"{original_key}:{value}\n"
                    for original_key, value in headers.items()
                    if original_key.lower() == header_name.lower()
                ),
                "\n",
            )
            signed_headers_string += matched

        signing_string = (
            f"{method.upper()}\n"
            f"{http_uri}\n"
            f"{canonical_query_string}\n"
            f"{access_key}\n"
            f"{date_str}\n"
            f"{signed_headers_string}"
        )

        digest = hmac.new(
            secret_key.encode("utf-8"),
            signing_string.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _parse_embedding_payload(self, payload: Any) -> List[List[float]]:
        data = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(data, str):
            data = json.loads(data)

        if isinstance(data, dict):
            embeddings = data.get("embeddings")
            if embeddings is None:
                raise RuntimeError(f"Embedding response did not contain 'embeddings': {data}")
            return [self._normalize_single_vector(embeddings)]

        if isinstance(data, list):
            return [
                self._normalize_single_vector(item["embeddings"])
                for item in data
                if isinstance(item, dict) and "embeddings" in item
            ]

        raise RuntimeError(f"Unexpected embedding response type: {type(data)}")

    def _normalize_single_vector(self, value: Any) -> List[float]:
        current = value
        while isinstance(current, list) and len(current) == 1 and isinstance(current[0], list):
            current = current[0]

        if not isinstance(current, list):
            raise RuntimeError(f"Expected embedding vector list, got {type(current)}")

        if current and not all(isinstance(item, (int, float)) for item in current):
            raise RuntimeError(f"Expected flat numeric embedding vector, got {current[:3]}")

        return [float(item) for item in current]

    def _embed_via_source(self, texts: List[str]) -> List[List[float]]:
        embed_fn = self._load_source_callable()
        vectors = []
        for text in texts:
            result = embed_fn([text])
            vectors.append(self._normalize_single_vector(result))
        return vectors

    def _embed_via_hmac(self, texts: List[str]) -> List[List[float]]:
        if not self.access_key or not self.secret_key:
            raise RuntimeError("Honor access_key and secret_key are required for HMAC mode")

        date_str = formatdate(usegmt=True)
        signed_headers = ["User-Agent"]
        headers = {"User-Agent": "openviking-honor-embedder/1.0"}
        signature = self._generate_signature(
            method="POST",
            url=self.api_url,
            access_key=self.access_key,
            secret_key=self.secret_key,
            date_str=date_str,
            signed_headers=signed_headers,
            headers=headers,
        )

        request_headers = {
            "X-HMAC-SIGNATURE": signature,
            "X-HMAC-ALGORITHM": "hmac-sha256",
            "X-HMAC-ACCESS-KEY": self.access_key,
            "Date": date_str,
            "X-HMAC-SIGNED-HEADERS": ";".join(signed_headers),
            "Content-Type": "application/json",
            **headers,
        }

        response = requests.post(
            self.api_url,
            json={"query": texts},
            headers=request_headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self._parse_embedding_payload(response.json())

    def _embed_many(self, texts: List[str]) -> List[List[float]]:
        if self._can_use_source_file():
            return self._embed_via_source(texts)
        return self._embed_via_hmac(texts)

    def _detect_dimension(self) -> int:
        vectors = self._embed_many(["test"])
        if not vectors or not vectors[0]:
            raise RuntimeError("Honor embedding dimension detection returned empty vector")
        return len(vectors[0])

    def embed(self, text: str) -> EmbedResult:
        try:
            vectors = self._embed_many([text])
            return EmbedResult(dense_vector=vectors[0])
        except Exception as exc:
            raise RuntimeError(f"Honor embedding failed: {exc}") from exc

    def embed_batch(self, texts: List[str]) -> List[EmbedResult]:
        if not texts:
            return []

        try:
            vectors = self._embed_many(texts)
            if len(vectors) != len(texts):
                raise RuntimeError(
                    f"Honor embedding result count mismatch: expected {len(texts)}, got {len(vectors)}"
                )
            return [EmbedResult(dense_vector=vector) for vector in vectors]
        except Exception as exc:
            raise RuntimeError(f"Honor batch embedding failed: {exc}") from exc

    def get_dimension(self) -> int:
        return self._dimension
