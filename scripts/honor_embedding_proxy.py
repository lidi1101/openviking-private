import argparse
import base64
import hashlib
import hmac
import importlib.util
import json
import os
import sys
import urllib.parse
from email.utils import formatdate
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import requests

DEFAULT_URL = "https://all-scenario-device-test.test.honor.com/all-scenario/rag/v1/get-embedding"
DEFAULT_MODEL = "honor-embedding"
DEFAULT_SOURCE_FILE = str(Path.home() / "Downloads" / "emb_requests.py")

class HonorEmbeddingProxy:
    def __init__(self):
        self.source_file = os.environ.get("HONOR_EMBED_SOURCE_FILE", DEFAULT_SOURCE_FILE)
        self.source_function = os.environ.get("HONOR_EMBED_SOURCE_FUNCTION", "send_emb_request")
        self.api_url = os.environ.get("HONOR_EMBED_API_URL", DEFAULT_URL)
        self.access_key = os.environ.get("HONOR_EMBED_ACCESS_KEY")
        self.secret_key = os.environ.get("HONOR_EMBED_SECRET_KEY")
        self.timeout = float(os.environ.get("HONOR_EMBED_TIMEOUT", "60"))
        self.default_model = os.environ.get("HONOR_EMBED_MODEL", DEFAULT_MODEL)
        self._cached_source_callable: Optional[Callable[[List[str]], Any]] = None

    def _use_source_file(self) -> bool:
        return Path(self.source_file).exists()

    def _load_source_callable(self) -> Callable[[List[str]], Any]:
        if self._cached_source_callable:
            return self._cached_source_callable

        source_path = Path(self.source_file)
        if not source_path.exists():
            raise RuntimeError(
                f"HONOR_EMBED_SOURCE_FILE does not exist: {source_path}. "
                "Set HONOR_EMBED_SOURCE_FILE or configure HONOR_EMBED_ACCESS_KEY / HONOR_EMBED_SECRET_KEY."
            )

        spec = importlib.util.spec_from_file_location("honor_embed_source", str(source_path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Failed to load source file: {source_path}")

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
                (urllib.parse.quote(k, safe=""), urllib.parse.quote(v, safe=""))
                for k, v in query_pairs
            ]
            query_pairs.sort(key=lambda x: x[0])
            canonical_query_string = "&".join(f"{k}={v}" for k, v in query_pairs)

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
            return [embeddings]

        if isinstance(data, list):
            parsed = []
            for item in data:
                if isinstance(item, dict) and "embeddings" in item:
                    parsed.append(item["embeddings"])
                else:
                    raise RuntimeError(f"Unexpected embedding item: {item}")
            return parsed

        raise RuntimeError(f"Unexpected embedding response type: {type(data)}")

    def _normalize_single_vector(self, value: Any) -> List[float]:
        current = value
        while (
            isinstance(current, list)
            and len(current) == 1
            and isinstance(current[0], list)
        ):
            current = current[0]

        if not isinstance(current, list):
            raise RuntimeError(f"Expected embedding vector list, got {type(current)}")

        if not current:
            return []

        if not all(isinstance(item, (int, float)) for item in current):
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
            raise RuntimeError(
                "HONOR_EMBED_ACCESS_KEY and HONOR_EMBED_SECRET_KEY must be set "
                "when HONOR_EMBED_SOURCE_FILE is unavailable."
            )

        date_str = formatdate(usegmt=True)
        signed_headers = ["User-Agent"]
        headers = {"User-Agent": "openviking-honor-proxy/1.0"}
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

    def embed_many(self, texts: List[str], dimensions: Optional[int] = None) -> List[List[float]]:
        vectors = (
            self._embed_via_source(texts)
            if self._use_source_file()
            else [self._normalize_single_vector(vector) for vector in self._embed_via_hmac(texts)]
        )
        if dimensions is None:
            return vectors

        truncated = []
        for vector in vectors:
            if dimensions > len(vector):
                raise RuntimeError(
                    f"Requested dimensions={dimensions}, but upstream vector length is {len(vector)}"
                )
            truncated.append(vector[:dimensions])
        return truncated

    def detect_dimension(self, probe_text: str = "test") -> int:
        vector = self.embed_many([probe_text])[0]
        return len(vector)


proxy = HonorEmbeddingProxy()


def create_app():
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    class EmbeddingRequest(BaseModel):
        input: Union[str, List[str]]
        model: str = DEFAULT_MODEL
        dimensions: Optional[int] = None
        encoding_format: str = "float"
        user: Optional[str] = None

    app = FastAPI(title="Honor Embedding OpenAI Proxy", version="1.0.0")

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {
            "ok": True,
            "mode": "source-file" if proxy._use_source_file() else "hmac-env",
            "source_file": proxy.source_file if proxy._use_source_file() else None,
            "api_url": proxy.api_url,
            "default_model": proxy.default_model,
        }

    @app.get("/dimension")
    def detect_dimension() -> Dict[str, int]:
        try:
            return {"dimension": proxy.detect_dimension()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/v1/embeddings")
    def create_embeddings(request: EmbeddingRequest) -> Dict[str, Any]:
        texts = [request.input] if isinstance(request.input, str) else request.input
        if not texts:
            raise HTTPException(status_code=400, detail="'input' must not be empty")

        try:
            vectors = proxy.embed_many(texts, request.dimensions)
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else 502
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return {
            "object": "list",
            "data": [
                {
                    "object": "embedding",
                    "index": index,
                    "embedding": vector,
                }
                for index, vector in enumerate(vectors)
            ],
            "model": request.model or proxy.default_model,
            "usage": {
                "prompt_tokens": 0,
                "total_tokens": 0,
            },
        }

    return app


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Honor embedding OpenAI-compatible local proxy")
    parser.add_argument("--host", default=os.environ.get("HONOR_EMBED_PROXY_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("HONOR_EMBED_PROXY_PORT", "18080")),
    )
    parser.add_argument(
        "--probe-dimension",
        action="store_true",
        help="Call the upstream embedding API once and print the vector dimension.",
    )
    parser.add_argument(
        "--probe-text",
        default="dimension probe",
        help="Probe text used with --probe-dimension.",
    )
    args = parser.parse_args(argv)

    if args.probe_dimension:
        print(proxy.detect_dimension(args.probe_text))
        return 0

    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "uvicorn is not installed in the current Python environment. "
            "Activate the OpenViking environment first, or install 'uvicorn' and 'fastapi'."
        ) from exc

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
