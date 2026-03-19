"""Tests for the Honor embedding provider."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openviking.models.embedder import HonorDenseEmbedder


class TestHonorDenseEmbedder:
    def test_init_requires_credentials_or_source(self):
        with pytest.raises(ValueError, match="Honor provider requires either 'source_file'"):
            HonorDenseEmbedder(model_name="honor-embedding", dimension=4)

    @patch("openviking.models.embedder.honor_embedders.requests.post")
    def test_embed_via_hmac(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [{"embeddings": [0.1, 0.2, 0.3, 0.4]}]}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        embedder = HonorDenseEmbedder(
            model_name="honor-embedding",
            access_key="test-ak",
            secret_key="test-sk",
            api_url="https://example.com/embedding",
            dimension=4,
        )

        result = embedder.embed("hello")

        assert result.dense_vector == [0.1, 0.2, 0.3, 0.4]
        mock_post.assert_called_once()

    def test_embed_via_source_file(self, tmp_path: Path):
        source_file = tmp_path / "honor_source.py"
        source_file.write_text(
            "def send_emb_request(query_list):\n"
            "    assert isinstance(query_list, list)\n"
            "    return [0.5, 0.6, 0.7]\n",
            encoding="utf-8",
        )

        embedder = HonorDenseEmbedder(
            model_name="honor-embedding",
            source_file=str(source_file),
            dimension=3,
        )

        result = embedder.embed("hello")
        assert result.dense_vector == [0.5, 0.6, 0.7]

    @patch("openviking.models.embedder.honor_embedders.requests.post")
    def test_embed_batch_count_mismatch_raises(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [{"embeddings": [0.1, 0.2]}]}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        embedder = HonorDenseEmbedder(
            model_name="honor-embedding",
            access_key="test-ak",
            secret_key="test-sk",
            dimension=2,
        )

        with pytest.raises(RuntimeError, match="result count mismatch"):
            embedder.embed_batch(["hello", "world"])
