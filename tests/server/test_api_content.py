# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: Apache-2.0

"""Tests for content endpoints: read, abstract, overview, write."""

from types import SimpleNamespace

import httpx

from openviking.server.app import create_app
from openviking.server.config import ServerConfig
from openviking.server.dependencies import set_service


async def test_read_content(client_with_resource):
    client, uri = client_with_resource
    # The resource URI may be a directory; list children to find the file
    ls_resp = await client.get(
        "/api/v1/fs/ls",
        params={"uri": uri, "simple": True, "recursive": True, "output": "original"},
    )
    children = ls_resp.json().get("result", [])
    # Find a file (non-directory) to read
    file_uri = None
    if children:
        # ls(simple=True) returns full URIs, use directly
        file_uri = children[0] if isinstance(children[0], str) else None
    if file_uri is None:
        file_uri = uri

    resp = await client.get("/api/v1/content/read", params={"uri": file_uri})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["result"] is not None


async def test_abstract_content(client_with_resource):
    client, uri = client_with_resource
    resp = await client.get("/api/v1/content/abstract", params={"uri": uri})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


async def test_overview_content(client_with_resource):
    client, uri = client_with_resource
    resp = await client.get("/api/v1/content/overview", params={"uri": uri})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


async def test_write_content():
    writes: list[tuple[str, str]] = []

    class _FakeFSService:
        async def write_file(self, uri: str, content: str, *, ctx):
            writes.append((uri, content))

    app = create_app(config=ServerConfig(), service=SimpleNamespace(fs=_FakeFSService()))
    set_service(SimpleNamespace(fs=_FakeFSService()))
    transport = httpx.ASGITransport(app=app)
    target_uri = "viking://agent/test-space/instructions/IDENTITY.md"
    payload = {
        "uri": target_uri,
        "content": "# IDENTITY\n\n## Identity\n- You are a Java development assistant.\n",
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        write_resp = await test_client.post("/api/v1/content/write", json=payload)

    assert write_resp.status_code == 200
    assert write_resp.json()["status"] == "ok"
    assert writes == [(target_uri, payload["content"])]
