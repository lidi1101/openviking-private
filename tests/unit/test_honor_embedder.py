# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from openviking.models.embedder.honor_embedders import HonorDenseEmbedder
from openviking_cli.utils.config.embedding_config import EmbeddingConfig, EmbeddingModelConfig


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_honor_embedding_config_builds_native_embedder(tmp_path: Path):
    source_file = tmp_path / "emb_requests.py"
    source_file.write_text(
        "def send_emb_request(texts):\n"
        "    return [[1.0, 2.0, 3.0]]\n",
        encoding="utf-8",
    )

    config = EmbeddingConfig(
        dense=EmbeddingModelConfig(
            provider="honor",
            model="honor-embedding",
            dimension=3,
            source_file=str(source_file),
        )
    )

    embedder = config.get_embedder()
    assert isinstance(embedder, HonorDenseEmbedder)
    assert embedder.get_dimension() == 3


def test_honor_embedder_posts_signed_request_and_parses_response(monkeypatch):
    calls = []

    def _fake_post(url, json, headers, timeout):
        calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return _FakeResponse({"data": [{"embeddings": [0.1, 0.2, 0.3]}]})

    monkeypatch.setattr("openviking.models.embedder.honor_embedders.requests.post", _fake_post)

    embedder = HonorDenseEmbedder(
        model_name="honor-embedding",
        api_base="https://example.com/embedding",
        dimension=3,
        hmac_access_key="test-ak",
        hmac_secret_key="test-sk",
    )

    result = embedder.embed("hello")

    assert result.dense_vector == [0.1, 0.2, 0.3]
    assert calls[0]["url"] == "https://example.com/embedding"
    assert calls[0]["json"] == {"query": ["hello"]}
    assert calls[0]["headers"]["X-HMAC-ACCESS-KEY"] == "test-ak"
    assert calls[0]["headers"]["X-HMAC-ALGORITHM"] == "hmac-sha256"


def test_honor_embedder_does_not_auto_load_default_source_file(monkeypatch):
    calls = []

    def _fake_post(url, json, headers, timeout):
        calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return _FakeResponse({"data": [{"embeddings": [0.1, 0.2, 0.3]}]})

    monkeypatch.delenv("HONOR_EMBED_SOURCE_FILE", raising=False)
    monkeypatch.setattr("openviking.models.embedder.honor_embedders.requests.post", _fake_post)

    embedder = HonorDenseEmbedder(
        model_name="honor-embedding",
        api_base="https://example.com/embedding",
        dimension=3,
        hmac_access_key="test-ak",
        hmac_secret_key="test-sk",
    )

    result = embedder.embed("hello")

    assert result.dense_vector == [0.1, 0.2, 0.3]
    assert len(calls) == 1
    assert embedder.source_file is None


def test_honor_embedder_detects_dimension_from_source_file(tmp_path: Path):
    source_file = tmp_path / "emb_requests.py"
    source_file.write_text(
        "def send_emb_request(texts):\n"
        "    text = texts[0]\n"
        "    return [[float(len(text)), 2.0, 3.0, 4.0]]\n",
        encoding="utf-8",
    )

    config = EmbeddingConfig(
        dense=EmbeddingModelConfig(
            provider="honor",
            model="honor-embedding",
            source_file=str(source_file),
        )
    )

    assert config.get_dimension() == 4

    embedder = config.get_embedder()
    batch = embedder.embed_batch(["a", "abcd"])

    assert batch[0].dense_vector == [1.0, 2.0, 3.0, 4.0]
    assert batch[1].dense_vector == [4.0, 2.0, 3.0, 4.0]
