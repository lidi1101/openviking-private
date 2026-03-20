# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0
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

from openviking.models.embedder.base import DenseEmbedderBase, EmbedResult, truncate_and_normalize


class HonorDenseEmbedder(DenseEmbedderBase):
    """Honor dense embedder with direct HMAC or source-file integration."""

    DEFAULT_URL = (
        "https://all-scenario-device-test.test.honor.com/all-scenario/rag/v1/get-embedding"
    )
    DEFAULT_MODEL = "honor-embedding"
    DEFAULT_SOURCE_FUNCTION = "send_emb_request"
    DEFAULT_ACCESS_KEY = "pc-ai-agent"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        api_base: Optional[str] = None,
        dimension: Optional[int] = None,
        timeout_s: float = 60.0,
        source_file: Optional[str] = None,
        source_function: Optional[str] = None,
        hmac_access_key: Optional[str] = None,
        hmac_secret_key: Optional[str] = None,
        hmac_signed_headers: Optional[List[str]] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(model_name, config)

        self.api_base = (
            api_base or os.environ.get("HONOR_EMBED_API_URL") or self.DEFAULT_URL
        ).strip()
        self.dimension = dimension
        self.timeout_s = float(timeout_s)
        self.source_file = source_file or os.environ.get("HONOR_EMBED_SOURCE_FILE")
        self.source_function = (
            source_function
            or os.environ.get("HONOR_EMBED_SOURCE_FUNCTION")
            or self.DEFAULT_SOURCE_FUNCTION
        )
        self.hmac_access_key = (
            hmac_access_key
            or os.environ.get("HONOR_EMBED_ACCESS_KEY")
            or self.DEFAULT_ACCESS_KEY
        )
        self.hmac_secret_key = hmac_secret_key or os.environ.get("HONOR_EMBED_SECRET_KEY")
        self.hmac_signed_headers = self._normalize_signed_headers(
            hmac_signed_headers or self._load_signed_headers_from_env()
        )
        self._cached_source_callable: Optional[Callable[[List[str]], Any]] = None

        self._dimension = dimension
        if self._dimension is None:
            self._dimension = self._detect_dimension()

    @staticmethod
    def _normalize_signed_headers(headers: Optional[List[str]]) -> List[str]:
        cleaned = [header.strip() for header in (headers or ["User-Agent"]) if header.strip()]
        return cleaned or ["User-Agent"]

    @staticmethod
    def _load_signed_headers_from_env() -> Optional[List[str]]:
        raw = os.environ.get("HONOR_EMBED_SIGNED_HEADERS")
        if not raw:
            return None
        return [item.strip() for item in raw.split(",") if item.strip()]

    def _use_source_file(self) -> bool:
        return bool(self.source_file) and Path(self.source_file).exists()

    def _load_source_callable(self) -> Callable[[List[str]], Any]:
        if self._cached_source_callable is not None:
            return self._cached_source_callable

        source_path = Path(self.source_file)
        if not source_path.exists():
            raise RuntimeError(
                f"Honor embedding source file does not exist: {source_path}. "
                "Configure source_file or set HMAC credentials."
            )

        spec = importlib.util.spec_from_file_location("honor_embed_source", str(source_path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Failed to load Honor embedding source file: {source_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        embed_fn = getattr(module, self.source_function, None)
        if not callable(embed_fn):
            raise RuntimeError(
                f"Function '{self.source_function}' was not found in {source_path}"
            )

        self._cached_source_callable = embed_fn
        return embed_fn

    def _detect_dimension(self) -> int:
        vector = self._embed_many(["dimension probe"], requested_dimension=None)[0]
        return len(vector)

    def _generate_signature(
        self,
        *,
        method: str,
        url: str,
        access_key: str,
        secret_key: str,
        date_str: str,
        signed_headers: List[str],
        headers: Dict[str, str],
    ) -> str:
        parsed_url = urllib.parse.urlparse(url)
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
                    f"{original_name}:{value}\n"
                    for original_name, value in headers.items()
                    if original_name.lower() == header_name.lower()
                ),
                "\n",
            )
            signed_headers_string += matched

        signing_string = (
            f"{method.upper()}\n"
            f"{parsed_url.path or '/'}\n"
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

    def _build_headers(self) -> Dict[str, str]:
        if not self.hmac_secret_key:
            raise RuntimeError(
                "Honor embedding HMAC secret key is missing. "
                "Set hmac_secret_key/HONOR_EMBED_SECRET_KEY or provide a source file."
            )

        date_str = formatdate(usegmt=True)
        base_headers = {"User-Agent": "openviking-honor-embedder/1.0"}
        signature = self._generate_signature(
            method="POST",
            url=self.api_base,
            access_key=self.hmac_access_key,
            secret_key=self.hmac_secret_key,
            date_str=date_str,
            signed_headers=self.hmac_signed_headers,
            headers=base_headers,
        )
        return {
            "X-HMAC-SIGNATURE": signature,
            "X-HMAC-ALGORITHM": "hmac-sha256",
            "X-HMAC-ACCESS-KEY": self.hmac_access_key,
            "X-HMAC-SIGNED-HEADERS": ";".join(self.hmac_signed_headers),
            "Date": date_str,
            "Content-Type": "application/json",
            **base_headers,
        }

    @staticmethod
    def _normalize_source_vector(value: Any) -> List[float]:
        current = value
        while isinstance(current, list) and len(current) == 1 and isinstance(current[0], list):
            current = current[0]

        if not isinstance(current, list):
            raise RuntimeError(f"Expected embedding vector list, got {type(current)}")
        if not current:
            return []
        if not all(isinstance(item, (int, float)) for item in current):
            raise RuntimeError(f"Expected flat numeric embedding vector, got {current[:3]}")
        return [float(item) for item in current]

    @staticmethod
    def _parse_embedding_payload(payload: Any) -> List[List[float]]:
        data = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(data, str):
            data = json.loads(data)

        if isinstance(data, dict):
            embeddings = data.get("embeddings")
            if embeddings is None:
                raise RuntimeError(f"Embedding response did not contain 'embeddings': {data}")
            if embeddings and isinstance(embeddings[0], (int, float)):
                return [[float(item) for item in embeddings]]
            return [[float(item) for item in vector] for vector in embeddings]

        if isinstance(data, list):
            parsed = []
            for item in data:
                if isinstance(item, dict) and "embeddings" in item:
                    embedding = item["embeddings"]
                    if embedding and isinstance(embedding[0], (int, float)):
                        parsed.append([float(value) for value in embedding])
                    else:
                        raise RuntimeError(
                            "Honor embedding list response must contain flat vectors per item"
                        )
                else:
                    raise RuntimeError(f"Unexpected embedding item: {item}")
            return parsed

        raise RuntimeError(f"Unexpected embedding response type: {type(data)}")

    def _coerce_dimension(
        self, vector: List[float], requested_dimension: Optional[int]
    ) -> List[float]:
        if requested_dimension is None:
            return vector
        if requested_dimension > len(vector):
            raise RuntimeError(
                f"Requested dimension {requested_dimension}, but upstream vector length is {len(vector)}"
            )
        return truncate_and_normalize(vector, requested_dimension)

    def _embed_via_source(
        self, texts: List[str], requested_dimension: Optional[int]
    ) -> List[List[float]]:
        embed_fn = self._load_source_callable()
        vectors = []
        for text in texts:
            raw_vector = embed_fn([text])
            vector = self._normalize_source_vector(raw_vector)
            vectors.append(self._coerce_dimension(vector, requested_dimension))
        return vectors

    def _embed_via_hmac(
        self, texts: List[str], requested_dimension: Optional[int]
    ) -> List[List[float]]:
        response = requests.post(
            self.api_base,
            json={"query": texts},
            headers=self._build_headers(),
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        vectors = self._parse_embedding_payload(response.json())
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"Embedding count mismatch: expected {len(texts)}, got {len(vectors)}"
            )
        return [self._coerce_dimension(vector, requested_dimension) for vector in vectors]

    def _embed_many(
        self, texts: List[str], requested_dimension: Optional[int]
    ) -> List[List[float]]:
        if not texts:
            return []
        if self._use_source_file():
            return self._embed_via_source(texts, requested_dimension)
        return self._embed_via_hmac(texts, requested_dimension)

    def embed(self, text: str) -> EmbedResult:
        vector = self._embed_many([text], self.dimension)[0]
        return EmbedResult(dense_vector=vector)

    def embed_batch(self, texts: List[str]) -> List[EmbedResult]:
        vectors = self._embed_many(texts, self.dimension)
        return [EmbedResult(dense_vector=vector) for vector in vectors]

    def get_dimension(self) -> int:
        return self._dimension
