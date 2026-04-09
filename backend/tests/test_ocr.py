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
    items=[OCRItemResult(material_type="Steel Rod", quantity=50.0, lot_batch_number="LOT-001")],
    confidence=1.0,
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
            {"material_type": "Steel Rod", "quantity": 50.0, "lot_batch_number": "LOT-001"},
            {"material_type": "Bolt", "quantity": None, "lot_batch_number": None},
        ],
    }
    result = ocr_service._build_response(data)
    assert result.supplier == "Acme Metals"
    assert result.confidence == 1.0
    assert len(result.items) == 2
    assert result.items[0].quantity == 50.0
    assert result.items[1].quantity is None


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
    assert mock_client.messages.create.call_count == 2


def test_ocr_service_gemini_zero_confidence_falls_back_to_claude():
    with (
        patch("app.services.ocr_service._extract_with_gemini", return_value=OCRResponse(confidence=0.0)),
        patch("app.services.ocr_service._extract_with_claude", return_value=_GOOD_RESPONSE),
    ):
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.confidence == 1.0
    assert result.supplier == "Acme Metals"
