# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for OpenViking server tests."""

import shutil
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import uvicorn

from openviking import AsyncOpenViking
from openviking.models.embedder.base import EmbedResult
from openviking.server.app import create_app
from openviking.server.config import ServerConfig
from openviking.server.identity import RequestContext, Role
from openviking.service.core import OpenVikingService
from openviking_cli.session.user_id import UserIdentifier
from openviking_cli.utils.config.embedding_config import EmbeddingConfig
from openviking_cli.utils.config.open_viking_config import OpenVikingConfigSingleton
from openviking_cli.utils.config.vlm_config import VLMConfig

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent.parent
TEST_TMP_DIR = PROJECT_ROOT / "test_data" / "tmp_server"

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_MD_CONTENT = """\
# Sample Document

## Introduction
This is a sample markdown document for server testing.

## Features
- Feature 1: Resource management
- Feature 2: Semantic search
"""


class _FakeEmbedder:
    is_sparse = False

    def embed(self, text: str) -> EmbedResult:
        seed = max(len(text.strip()), 1)
        return EmbedResult(dense_vector=[float(seed % 7 or 1)] * 8)

    def embed_batch(self, texts: list[str]) -> list[EmbedResult]:
        return [self.embed(text) for text in texts]

    def close(self) -> None:
        return None


class _FakeVLM:
    def get_completion(self, prompt: str, thinking: bool = False) -> str:
        prompt_lower = prompt.lower()
        if "overview" in prompt_lower:
            return "# Overview\n\nSynthetic test overview."
        if "abstract" in prompt_lower or "summary" in prompt_lower:
            return "Synthetic test abstract."
        return "Synthetic test completion."

    async def get_completion_async(self, prompt: str, thinking: bool = False, max_retries: int = 0):
        return self.get_completion(prompt, thinking)

    def get_vision_completion(self, prompt: str, images: list, thinking: bool = False) -> str:
        return self.get_completion(prompt, thinking)

    async def get_vision_completion_async(
        self, prompt: str, images: list, thinking: bool = False
    ) -> str:
        return self.get_completion(prompt, thinking)


# ---------------------------------------------------------------------------
# Core fixtures: service + app + async client (HTTP API tests, in-process)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def temp_dir():
    """Create a unique temp directory per test, auto-cleanup."""
    import uuid

    unique_dir = TEST_TMP_DIR / uuid.uuid4().hex[:8]
    unique_dir.mkdir(parents=True, exist_ok=True)
    yield unique_dir
    shutil.rmtree(unique_dir, ignore_errors=True)


@pytest.fixture(scope="function", autouse=True)
def isolated_openviking_config(temp_dir: Path, monkeypatch):
    OpenVikingConfigSingleton.reset_instance()
    OpenVikingConfigSingleton.initialize(
        config_dict={
            "storage": {
                "workspace": str(temp_dir / "config_data"),
                "agfs": {"backend": "local"},
                "vectordb": {"backend": "local"},
            },
            "embedding": {
                "dense": {
                    "provider": "openai",
                    "model": "test-embedding",
                    "api_key": "test-key",
                    "dimension": 8,
                }
            },
            "vlm": {
                "provider": "openai",
                "model": "test-vlm",
                "api_key": "test-key",
            },
        }
    )
    monkeypatch.setattr(EmbeddingConfig, "get_embedder", lambda self: _FakeEmbedder())
    monkeypatch.setattr(VLMConfig, "get_vlm_instance", lambda self: _FakeVLM())
    yield
    OpenVikingConfigSingleton.reset_instance()


@pytest.fixture(scope="function")
def sample_markdown_file(temp_dir: Path) -> Path:
    """Create a sample markdown file for resource tests."""
    f = temp_dir / "sample.md"
    f.write_text(SAMPLE_MD_CONTENT)
    return f


@pytest_asyncio.fixture(scope="function")
async def service(temp_dir: Path):
    """Create and initialize an OpenVikingService in embedded mode."""
    svc = OpenVikingService(
        path=str(temp_dir / "data"), user=UserIdentifier.the_default_user("test_user")
    )
    await svc.initialize()
    yield svc
    await svc.close()


@pytest_asyncio.fixture(scope="function")
async def app(service: OpenVikingService):
    """Create FastAPI app with pre-initialized service (no auth)."""
    from openviking.server.dependencies import set_service

    config = ServerConfig()
    fastapi_app = create_app(config=config, service=service)
    # ASGITransport doesn't trigger lifespan, so wire up the service manually
    set_service(service)
    return fastapi_app


@pytest_asyncio.fixture(scope="function")
async def client(app):
    """httpx AsyncClient bound to the ASGI app (no real network)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest_asyncio.fixture(scope="function")
async def client_with_resource(client, service, sample_markdown_file):
    """Client + a resource already added and processed."""
    ctx = RequestContext(user=UserIdentifier.the_default_user(), role=Role.ROOT)
    result = await service.resources.add_resource(
        path=str(sample_markdown_file),
        ctx=ctx,
        reason="test resource",
        wait=True,
    )
    yield client, result.get("root_uri", "")


# ---------------------------------------------------------------------------
# SDK fixtures: real uvicorn server + AsyncHTTPClient (end-to-end tests)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def running_server(temp_dir: Path):
    """Start a real uvicorn server in a background thread."""
    await AsyncOpenViking.reset()

    svc = OpenVikingService(
        path=str(temp_dir / "sdk_data"), user=UserIdentifier.the_default_user("sdk_test_user")
    )
    await svc.initialize()

    config = ServerConfig()
    fastapi_app = create_app(config=config, service=svc)

    # Find a free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    uvi_config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(uvi_config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server ready
    for _ in range(50):
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.1)

    yield port, svc

    server.should_exit = True
    thread.join(timeout=5)
    await svc.close()
    await AsyncOpenViking.reset()
