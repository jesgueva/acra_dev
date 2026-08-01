"""
Tests for T08 — OCR Service & API (Vision LLM pipeline).
Expected: 6+ passed, 0 failed.
All tests run without live API keys — Gemini and Claude calls are mocked.
"""
import json
from io import BytesIO
from unittest.mock import MagicMock, patch, AsyncMock

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
    provider="gemini",
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


def test_ocr_service_falls_back_to_claude_when_gemini_fails():
    with (
        patch("app.services.ocr_service._extract_with_gemini", side_effect=Exception("Gemini API error")),
        patch("app.services.ocr_service._extract_with_claude", return_value=_GOOD_RESPONSE),
    ):
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.supplier == "Acme Metals"
    assert result.confidence == 1.0


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
    result = ocr_service._build_response(data, "gemini")
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


def test_build_response_reports_the_answering_provider():
    """ACR-36: `provider` was accepted by _build_response and thrown away."""
    data = {"supplier": "Acme Metals", "items": []}
    assert ocr_service._build_response(data, "gemini").provider == "gemini"
    assert ocr_service._build_response(data, "claude").provider == "claude"


def test_header_fill_rate_mirrors_confidence():
    data = {"supplier": "Acme Metals", "carrier": "Fast Freight", "items": []}
    result = ocr_service._build_response(data, "gemini")
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
    result = ocr_service._build_response(nonsense, "gemini")
    assert result.confidence == 1.0
    assert result.header_fill_rate == 1.0


def test_ocr_service_extract_with_gemini():
    json_payload = json.dumps({
        "supplier": "Acme Metals",
        "carrier": "Fast Freight",
        "bol_reference": "BOL-001",
        "delivery_date": "01/15/2026",
        "items": [],
    })
    mock_response = MagicMock()
    mock_response.text = json_payload
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("app.services.ocr_service._get_gemini_client", return_value=mock_client):
        result = ocr_service._extract_with_gemini(_small_jpeg_bytes(), "image/jpeg")

    assert result.bol_reference == "BOL-001"
    assert result.confidence == 1.0
    assert result.provider == "gemini"
    mock_client.models.generate_content.assert_called_once()


def test_ocr_service_extract_with_claude_jpeg_and_pdf():
    tool_input = {
        "supplier": "Acme Metals",
        "carrier": "Fast Freight",
        "bol_reference": "BOL-001",
        "delivery_date": "01/15/2026",
        "items": [],
    }
    mock_response = MagicMock()
    mock_response.content = [MagicMock(input=tool_input)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("app.services.ocr_service._get_anthropic_client", return_value=mock_client):
        result_jpeg = ocr_service._extract_with_claude(_small_jpeg_bytes(), "image/jpeg")
        result_pdf = ocr_service._extract_with_claude(b"%PDF-1.4", "application/pdf")

    assert result_jpeg.bol_reference == "BOL-001"
    assert result_pdf.bol_reference == "BOL-001"
    assert result_jpeg.provider == "claude"
    assert result_pdf.provider == "claude"
    assert mock_client.messages.create.call_count == 2


def test_ocr_service_gemini_zero_confidence_falls_back_to_claude():
    with (
        patch("app.services.ocr_service._extract_with_gemini", return_value=OCRResponse(confidence=0.0)),
        patch("app.services.ocr_service._extract_with_claude", return_value=_GOOD_RESPONSE),
    ):
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.confidence == 1.0
    assert result.supplier == "Acme Metals"


def test_fallback_reports_claude_through_the_real_build_path():
    """A genuine Gemini failure must surface `provider == "claude"`.

    Patched at the *client* boundary rather than at `_extract_with_*`, so the provider label comes
    from the real `_build_response` call instead of from a mock's return value.
    """
    tool_input = {
        "supplier": "Acme Metals",
        "carrier": "Fast Freight",
        "bol_reference": "BOL-001",
        "delivery_date": "01/15/2026",
        "items": [],
    }
    claude_response = MagicMock()
    claude_response.content = [MagicMock(input=tool_input)]
    claude_client = MagicMock()
    claude_client.messages.create.return_value = claude_response

    gemini_client = MagicMock()
    gemini_client.models.generate_content.side_effect = RuntimeError("gemini is down")

    with (
        patch("app.services.ocr_service._get_gemini_client", return_value=gemini_client),
        patch("app.services.ocr_service._get_anthropic_client", return_value=claude_client),
    ):
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.provider == "claude"
    assert result.bol_reference == "BOL-001"


def test_total_failure_reports_no_provider():
    gemini_client = MagicMock()
    gemini_client.models.generate_content.side_effect = RuntimeError("gemini is down")
    claude_client = MagicMock()
    claude_client.messages.create.side_effect = RuntimeError("claude is down too")

    with (
        patch("app.services.ocr_service._get_gemini_client", return_value=gemini_client),
        patch("app.services.ocr_service._get_anthropic_client", return_value=claude_client),
    ):
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.confidence == 0.0
    assert result.provider is None


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
            assert body["provider"] == "gemini"
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

def test_ocr_mock_mode_defaults_to_off():
    """Negative control: mock mode must be opt-in, never the default."""
    assert settings.ocr_mock_mode is False


def test_ocr_service_mock_mode_returns_canned_response_without_calling_providers():
    with (
        patch.object(settings, "ocr_mock_mode", True),
        patch("app.services.ocr_service._get_gemini_client") as gemini_client,
        patch("app.services.ocr_service._get_anthropic_client") as claude_client,
    ):
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.provider == "mock"
    assert result.supplier == "Acme Steel Supply Co."
    assert result.bol_reference == "BOL-2026-0623"
    assert result.confidence == 1.0
    assert len(result.items) == 3
    assert result.items[0].item_name == "Galvanized Steel Sheet"
    gemini_client.assert_not_called()
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
        patch.object(settings, "gemini_api_key", ""),
        patch.object(settings, "anthropic_api_key", ""),
        patch("app.services.ocr_service._get_gemini_client") as gemini_client,
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
    gemini_client.assert_not_called()
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
