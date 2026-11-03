"""Post image generation falls back to a model the account can use when gpt-image-1 isn't available
(for some keys: "The model 'gpt-image-1' does not exist")."""
from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException

from app.config import settings
from app.services import distribution

_NO_MODEL = (
    '{ "error": { "message": "The model `gpt-image-1` does not exist.", "type": "image_generation_user_error", '
    '"param": "model", "code": "invalid_value" } }'
)


class _FakeClient:
    """Stands in for httpx.AsyncClient; `script` maps the requested model to (status, body)."""

    calls: list[dict] = []
    script: dict[str, tuple[int, str]] = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None, data=None, files=None):
        body = json if json is not None else data
        _FakeClient.calls.append({"url": url, "model": body["model"], "prompt": body["prompt"]})
        status, text = _FakeClient.script[body["model"]]
        return httpx.Response(status, text=text, request=httpx.Request("POST", url))


@pytest.fixture(autouse=True)
def _fake_openai(monkeypatch):
    _FakeClient.calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_image_model", "gpt-image-1")
    monkeypatch.setattr(settings, "openai_image_fallback_models", "gpt-image-1.5,gpt-image-1-mini")


@pytest.mark.asyncio
async def test_falls_back_to_the_next_model_when_gpt_image_1_is_unavailable():
    _FakeClient.script = {"gpt-image-1": (400, _NO_MODEL), "gpt-image-1.5": (200, '{"data":[{"b64_json":"QUJD"}]}')}
    assert (await distribution.generate_post_image("Dunkin", "msg")).startswith("data:image/png;base64,")
    assert [c["model"] for c in _FakeClient.calls] == ["gpt-image-1", "gpt-image-1.5"]


@pytest.mark.asyncio
async def test_walks_the_whole_chain_and_reports_the_last_error_if_none_work():
    _FakeClient.script = {m: (400, _NO_MODEL) for m in ("gpt-image-1", "gpt-image-1.5", "gpt-image-1-mini")}
    with pytest.raises(HTTPException) as exc:
        await distribution.generate_post_image("Dunkin", "msg")
    assert exc.value.status_code == 502 and "does not exist" in exc.value.detail
    assert [c["model"] for c in _FakeClient.calls] == ["gpt-image-1", "gpt-image-1.5", "gpt-image-1-mini"]


@pytest.mark.asyncio
async def test_a_working_primary_model_is_not_retried():
    _FakeClient.script = {"gpt-image-1": (200, '{"data":[{"b64_json":"QUJD"}]}')}
    assert (await distribution.generate_post_image("Dunkin", "msg")).startswith("data:image/png;base64,")
    assert [c["model"] for c in _FakeClient.calls] == ["gpt-image-1"]


@pytest.mark.asyncio
async def test_other_errors_are_not_masked_by_the_fallback():
    # A rejected prompt (content policy) must surface as-is, not be retried on another model.
    _FakeClient.script = {"gpt-image-1": (400, '{"error":{"message":"Your request was rejected by the safety system."}}')}
    with pytest.raises(HTTPException) as exc:
        await distribution.generate_post_image("Dunkin", "msg")
    assert exc.value.status_code == 502 and "safety system" in exc.value.detail
    assert [c["model"] for c in _FakeClient.calls] == ["gpt-image-1"]


@pytest.mark.asyncio
async def test_photo_edit_uses_the_same_fallback_chain():
    _FakeClient.script = {"gpt-image-1": (400, _NO_MODEL), "gpt-image-1.5": (200, '{"data":[{"b64_json":"QUJD"}]}')}
    url = await distribution.generate_post_image_from_photo("Dunkin", "msg", b"png", "p.png", "image/png")
    assert url.startswith("data:image/png;base64,")
    assert [c["model"] for c in _FakeClient.calls] == ["gpt-image-1", "gpt-image-1.5"]
