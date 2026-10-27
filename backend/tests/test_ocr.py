"""
Tests for T08 — OCR Service & API (Vision LLM pipeline).
Expected: 6+ passed, 0 failed.
All tests run without live API keys — Claude calls are mocked.
"""
import json
from io import BytesIO
from unittest.mock import MagicMock, patch, AsyncMock

import anthropic
import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.routers.deliveries import _OCR_MAX_SIZE
from app.schemas.delivery import OCRItemResult, OCRResponse
from app.services import ocr_service
from tests.conftest import _make_rbac_session, _override

BASE_URL = "http://test"

PRIMARY = "claude-haiku-5-5"
FALLBACK = "claude-sonnet-5-5"


@pytest.fixture(autouse=True)
def _pin_models():
    """Pin the chain so these tests do not depend on whatever a developer's .env configures."""
    with (
        patch.object(settings, "anthropic_model", PRIMARY),
        patch.object(settings, "anthropic_fallback_model", FALLBACK),
    ):
        yield


def _small_jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (20, 20), color=(255, 255, 255)).save(buf, format="JPEG")
    return buf.getvalue()


_GOOD_RESPONSE = OCRResponse(
    supplier="Acme Metals",
    carrier="Fast Freight",
    bol_reference="BOL-2026-001",
    delivery_date="01/15/2026",
    # ACR-36: these were `material_type=` / `lot_batch_number=` — fields OCRItemResult has not had
    # for some time. Pydantic v2 silently drops unknown kwargs, so the assertions below were
    # passing against an all-None item. Use the real field names.
    items=[
        OCRItemResult(item_name="Steel Rod", quantity=50.0, pallets=2, units_per_pallet=25),
    ],
    confidence=1.0,
    header_fill_rate=1.0,
    provider=PRIMARY,
)

_EXTRACTION = {
    "supplier": "Acme Metals",
    "carrier": "Fast Freight",
    "bol_reference": "BOL-001",
    "delivery_date": "01/15/2026",
    "items": [],
}


def _claude_message(payload=None, stop_reason="end_turn", stop_details=None):
    """A Messages API reply as the SDK returns it: adaptive thinking first, then the JSON text."""
    blocks = [MagicMock(type="thinking", thinking="")]
    if payload is not None:
        blocks.append(MagicMock(type="text", text=json.dumps(payload)))
    return MagicMock(content=blocks, stop_reason=stop_reason, stop_details=stop_details)


def _client_by_model(**replies):
    """A client whose reply depends on the requested model; an Exception value is raised."""

    def create(**kwargs):
        reply = replies[kwargs["model"]]
        if isinstance(reply, Exception):
            raise reply
        return reply

    client = MagicMock()
    client.messages.create.side_effect = create
    return client


def _api_status_error(status: int) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIStatusError(
        f"Error code: {status}", response=httpx.Response(status, request=request), body=None
    )


@pytest.mark.asyncio
async def test_ocr_endpoint_success_returns_200():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("deliveries.create",))

    with patch("app.services.ocr_service.process_image_bytes", return_value=_GOOD_RESPONSE):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.post(
                    "/api/v1/deliveries/ocr",
                    files={"file": ("bol.jpg", _small_jpeg_bytes(), "image/jpeg")},
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            body = resp.json()
            assert body["supplier"] == "Acme Metals"
            assert body["bol_reference"] == "BOL-2026-001"
            assert body["confidence"] == 1.0
            assert len(body["items"]) == 1
        finally:
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_ocr_endpoint_no_auth_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.post(
            "/api/v1/deliveries/ocr",
            files={"file": ("bol.jpg", _small_jpeg_bytes(), "image/jpeg")},
        )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_ocr_endpoint_file_too_large_returns_422():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("deliveries.create",))

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/deliveries/ocr",
                files={"file": ("big.jpg", b"x" * (_OCR_MAX_SIZE + 1), "image/jpeg")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 422
        assert "10 MB" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_ocr_endpoint_unsupported_type_returns_422():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("deliveries.create",))

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/deliveries/ocr",
                files={"file": ("doc.txt", b"hello", "text/plain")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 422
        assert "Unsupported file type" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_ocr_endpoint_both_providers_fail_returns_422():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("deliveries.create",))

    with patch("app.services.ocr_service.process_image_bytes", return_value=OCRResponse(confidence=0.0)):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.post(
                    "/api/v1/deliveries/ocr",
                    files={"file": ("bol.jpg", _small_jpeg_bytes(), "image/jpeg")},
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 422
            assert "Unable to extract data" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_ocr_service_falls_back_to_the_fallback_model_when_the_primary_fails():
    def extract(file_bytes, content_type, model):
        if model == PRIMARY:
            raise Exception("primary API error")
        return _GOOD_RESPONSE

    with patch("app.services.ocr_service._extract_with_claude", side_effect=extract) as extract_mock:
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.supplier == "Acme Metals"
    assert result.confidence == 1.0
    assert [c.args[2] for c in extract_mock.call_args_list] == [PRIMARY, FALLBACK]


def test_ocr_service_does_not_call_the_fallback_when_the_primary_succeeds():
    with patch("app.services.ocr_service._extract_with_claude", return_value=_GOOD_RESPONSE) as extract_mock:
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.provider == PRIMARY
    assert extract_mock.call_count == 1


def test_ocr_service_build_response_and_parse_items():
    data = {
        "supplier": "Acme Metals",
        "carrier": "Fast Freight",
        "bol_reference": "BOL-2026-001",
        "delivery_date": "01/15/2026",
        "items": [
            {"item_name": "Steel Rod", "quantity": 50.0, "pallets": 2, "units_per_pallet": 25},
            {"item_name": "Bolt", "quantity": None, "pallets": None, "units_per_pallet": None},
        ],
    }
    result = ocr_service._build_response(data, PRIMARY)
    assert result.supplier == "Acme Metals"
    assert result.confidence == 1.0
    assert len(result.items) == 2
    # Names, not just quantities: the previous version of this test used field names the schema
    # dropped, so item identity went unchecked entirely.
    assert result.items[0].item_name == "Steel Rod"
    assert result.items[0].quantity == 50.0
    assert result.items[0].pallets == 2
    assert result.items[1].item_name == "Bolt"
    assert result.items[1].quantity is None


def test_build_response_reports_the_answering_model():
    """ACR-36: `provider` was accepted by _build_response and thrown away."""
    data = {"supplier": "Acme Metals", "items": []}
    assert ocr_service._build_response(data, PRIMARY).provider == PRIMARY
    assert ocr_service._build_response(data, FALLBACK).provider == FALLBACK


def test_header_fill_rate_mirrors_confidence():
    data = {"supplier": "Acme Metals", "carrier": "Fast Freight", "items": []}
    result = ocr_service._build_response(data, PRIMARY)
    assert result.header_fill_rate == result.confidence == 0.5


def test_confidence_measures_presence_not_correctness():
    """The defect A8-4 exists to expose, pinned at the unit level.

    Four header values that are all wrong still score 1.0, because the number counts non-empty
    fields. This test documents the semantics rather than asserting they are good — real accuracy
    is measured by `scripts/ocr_bench` against ground truth.
    """
    nonsense = {
        "supplier": "wrong",
        "carrier": "also wrong",
        "bol_reference": "wrong again",
        "delivery_date": "not a date",
        "items": [],
    }
    result = ocr_service._build_response(nonsense, PRIMARY)
    assert result.confidence == 1.0
    assert result.header_fill_rate == 1.0


def test_ocr_service_extract_with_claude_jpeg_and_pdf():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _claude_message(_EXTRACTION)

    with patch("app.services.ocr_service._get_anthropic_client", return_value=mock_client):
        result_jpeg = ocr_service._extract_with_claude(_small_jpeg_bytes(), "image/jpeg")
        result_pdf = ocr_service._extract_with_claude(b"%PDF-1.4", "application/pdf")

    assert result_jpeg.bol_reference == "BOL-001"
    assert result_pdf.bol_reference == "BOL-001"
    assert result_jpeg.provider == PRIMARY
    assert result_pdf.provider == PRIMARY
    assert mock_client.messages.create.call_count == 2

    jpeg_call, pdf_call = mock_client.messages.create.call_args_list
    assert jpeg_call.kwargs["messages"][0]["content"][0]["type"] == "image"
    assert jpeg_call.kwargs["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"
    assert pdf_call.kwargs["messages"][0]["content"][0]["type"] == "document"
    assert pdf_call.kwargs["messages"][0]["content"][0]["source"]["media_type"] == "application/pdf"


def test_extract_with_claude_requests_structured_output_without_forced_tool_use():
    """Sonnet 5.5 rejects a forced `tool_choice` with a 400, so the JSON shape comes from
    structured outputs instead — and the same request must work on every model in the chain."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _claude_message(_EXTRACTION)

    with patch("app.services.ocr_service._get_anthropic_client", return_value=mock_client):
        ocr_service._extract_with_claude(_small_jpeg_bytes(), "image/png", FALLBACK)

    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == FALLBACK
    assert kwargs["output_config"]["format"] == {
        "type": "json_schema",
        "schema": ocr_service._BOL_SCHEMA,
    }
    assert kwargs["output_config"]["effort"] == settings.anthropic_effort
    assert "tools" not in kwargs and "tool_choice" not in kwargs
    # Sampling parameters are rejected by the current models; thinking is left adaptive.
    assert not {"temperature", "top_p", "top_k", "thinking"} & kwargs.keys()
    # Thinking counts toward max_tokens — a cap sized for the JSON alone would truncate it.
    assert kwargs["max_tokens"] >= 8000


def test_bol_schema_meets_structured_output_rules():
    """Structured outputs require `additionalProperties: false` and every key listed in `required`
    on every object; a schema that drifts from that is rejected with a 400 on every upload."""

    def objects(schema):
        if isinstance(schema, dict):
            if schema.get("type") == "object":
                yield schema
            for value in schema.values():
                yield from objects(value)
        elif isinstance(schema, list):
            for value in schema:
                yield from objects(value)

    found = list(objects(ocr_service._BOL_SCHEMA))
    assert len(found) == 2  # the BOL and its line item
    for obj in found:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])


def test_extract_with_claude_reads_the_text_block_after_thinking():
    """Adaptive thinking puts `thinking` blocks first — reading content[0] would read the wrong one."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _claude_message(_EXTRACTION)
    assert mock_client.messages.create.return_value.content[0].type == "thinking"

    with patch("app.services.ocr_service._get_anthropic_client", return_value=mock_client):
        result = ocr_service._extract_with_claude(_small_jpeg_bytes(), "image/jpeg")

    assert result.supplier == "Acme Metals"


def test_extract_with_claude_raises_on_refusal():
    refusal = _claude_message(stop_reason="refusal", stop_details=MagicMock(category="general_harms"))
    mock_client = MagicMock()
    mock_client.messages.create.return_value = refusal

    with (
        patch("app.services.ocr_service._get_anthropic_client", return_value=mock_client),
        pytest.raises(ocr_service.ExtractionError, match="declined.*general_harms"),
    ):
        ocr_service._extract_with_claude(_small_jpeg_bytes(), "image/jpeg")


def test_extract_with_claude_raises_on_truncated_output():
    """`max_tokens` mid-JSON is not an extraction — never try to parse half an object."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _claude_message(stop_reason="max_tokens")

    with (
        patch("app.services.ocr_service._get_anthropic_client", return_value=mock_client),
        pytest.raises(ocr_service.ExtractionError, match="max_tokens"),
    ):
        ocr_service._extract_with_claude(_small_jpeg_bytes(), "image/jpeg")


def test_extract_with_claude_raises_when_no_text_comes_back():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _claude_message(payload=None)

    with (
        patch("app.services.ocr_service._get_anthropic_client", return_value=mock_client),
        pytest.raises(ocr_service.ExtractionError, match="no text block"),
    ):
        ocr_service._extract_with_claude(_small_jpeg_bytes(), "image/jpeg")


def test_ocr_service_primary_zero_confidence_falls_back():
    def extract(file_bytes, content_type, model):
        return OCRResponse(confidence=0.0) if model == PRIMARY else _GOOD_RESPONSE

    with patch("app.services.ocr_service._extract_with_claude", side_effect=extract):
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.confidence == 1.0
    assert result.supplier == "Acme Metals"


@pytest.mark.parametrize(
    "primary_reply",
    [
        RuntimeError("haiku is down"),
        _api_status_error(529),
        anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        ),
        _claude_message(stop_reason="refusal", stop_details=MagicMock(category="general_harms")),
    ],
    ids=["unexpected", "overloaded", "connection", "refusal"],
)
def test_fallback_reports_the_fallback_model_through_the_real_build_path(primary_reply):
    """A genuine primary failure must surface `provider == <fallback model>`.

    Patched at the *client* boundary rather than at `_extract_with_claude`, so the label comes from
    the real `_build_response` call instead of from a mock's return value.
    """
    client = _client_by_model(**{PRIMARY: primary_reply, FALLBACK: _claude_message(_EXTRACTION)})

    with patch("app.services.ocr_service._get_anthropic_client", return_value=client):
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.provider == FALLBACK
    assert result.bol_reference == "BOL-001"


def test_total_failure_reports_no_provider():
    client = _client_by_model(
        **{PRIMARY: RuntimeError("haiku is down"), FALLBACK: _api_status_error(500)}
    )

    with patch("app.services.ocr_service._get_anthropic_client", return_value=client):
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.confidence == 0.0
    assert result.provider is None


@pytest.mark.parametrize("fallback", ["", PRIMARY], ids=["disabled", "same-as-primary"])
def test_no_second_call_when_there_is_no_distinct_fallback(fallback):
    """An empty fallback disables the chain; naming the primary twice must not double-bill it."""
    client = _client_by_model(**{PRIMARY: RuntimeError("haiku is down")})

    with (
        patch.object(settings, "anthropic_fallback_model", fallback),
        patch("app.services.ocr_service._get_anthropic_client", return_value=client),
    ):
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.confidence == 0.0
    assert client.messages.create.call_count == 1


@pytest.mark.asyncio
async def test_ocr_endpoint_surfaces_provider_and_fill_rate_on_the_wire():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("deliveries.create",))

    with patch("app.services.ocr_service.process_image_bytes", return_value=_GOOD_RESPONSE):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.post(
                    "/api/v1/deliveries/ocr",
                    files={"file": ("bol.jpg", _small_jpeg_bytes(), "image/jpeg")},
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            body = resp.json()
            assert body["provider"] == PRIMARY
            assert body["header_fill_rate"] == 1.0
            assert body["items"][0]["item_name"] == "Steel Rod"
            assert body["items"][0]["pallets"] == 2
        finally:
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_ocr_endpoint_without_privilege_returns_403():
    """RBAC negative path — the endpoint requires `deliveries.create`."""
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("deliveries.view",))

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/deliveries/ocr",
                files={"file": ("bol.jpg", _small_jpeg_bytes(), "image/jpeg")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── ACR-50 / A10-2: offline/mock mode ──────────────────────────────────────

def test_settings_load_from_an_env_file_that_still_names_gemini(tmp_path):
    """Gemini was removed, but existing `backend/.env` files still carry GEMINI_API_KEY — and
    pydantic-settings rejects unknown keys by default, which would fail backend startup."""
    from app.core.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=old-key\nGEMINI_MODEL=gemini-2.5-flash\n")
    loaded = Settings(_env_file=env_file)
    assert not hasattr(loaded, "gemini_api_key")


def test_ocr_model_defaults():
    from app.core.config import Settings

    defaults = Settings(_env_file=None)
    assert defaults.anthropic_model == "claude-haiku-5-5"
    assert defaults.anthropic_fallback_model == "claude-sonnet-5-5"
    assert defaults.anthropic_effort == "medium"


def test_ocr_mock_mode_defaults_to_off():
    """Negative control: mock mode must be opt-in, never the default."""
    assert settings.ocr_mock_mode is False


def test_ocr_service_mock_mode_returns_canned_response_without_calling_claude():
    with (
        patch.object(settings, "ocr_mock_mode", True),
        patch("app.services.ocr_service._get_anthropic_client") as claude_client,
    ):
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.provider == "mock"
    assert result.supplier == "Acme Steel Supply Co."
    assert result.bol_reference == "BOL-2026-0623"
    assert result.confidence == 1.0
    assert len(result.items) == 3
    assert result.items[0].item_name == "Galvanized Steel Sheet"
    claude_client.assert_not_called()


def test_ocr_mock_mode_ignores_upload_content():
    """Mock mode is deterministic regardless of what was actually uploaded."""
    with patch.object(settings, "ocr_mock_mode", True):
        result_jpeg = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")
        result_pdf = ocr_service.process_image_bytes(b"%PDF-1.4", "application/pdf")

    assert result_jpeg == result_pdf


@pytest.mark.asyncio
async def test_ocr_endpoint_mock_mode_returns_200_without_api_keys():
    """The end-to-end case this ticket exists for: no keys configured, mock mode on, still 200."""
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("deliveries.create",))

    with (
        patch.object(settings, "ocr_mock_mode", True),
        patch.object(settings, "anthropic_api_key", ""),
        patch("app.services.ocr_service._get_anthropic_client") as claude_client,
    ):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.post(
                    "/api/v1/deliveries/ocr",
                    files={"file": ("bol.jpg", _small_jpeg_bytes(), "image/jpeg")},
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            body = resp.json()
            assert body["provider"] == "mock"
            assert body["supplier"] == "Acme Steel Supply Co."
            assert len(body["items"]) == 3
        finally:
            app.dependency_overrides.pop(get_db, None)
    claude_client.assert_not_called()


@pytest.mark.asyncio
async def test_ocr_endpoint_mock_mode_still_enforces_rbac():
    """Mock mode is a service-layer branch below the router — RBAC is unaffected."""
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("deliveries.view",))

    with patch.object(settings, "ocr_mock_mode", True):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.post(
                    "/api/v1/deliveries/ocr",
                    files={"file": ("bol.jpg", _small_jpeg_bytes(), "image/jpeg")},
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.pop(get_db, None)
