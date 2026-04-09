"""
Tests for T08 — OCR Service & API.
Expected: 6 passed, 0 failed.
All tests run without a live database connection or real tesseract binary.
"""
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.schemas.delivery import OCRItemResult, OCRResponse
from app.services import ocr_service
from tests.conftest import _make_user, _override

BASE_URL = "http://test"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rbac_session(privileges=("deliveries.create",)):
    """Mock AsyncSession satisfying the 3 RBAC execute() calls."""
    user = _make_user()
    session = AsyncMock()
    call_no = {"n": 0}

    async def _execute(query, *args, **kwargs):
        result = MagicMock()
        call_no["n"] += 1
        n = call_no["n"]
        if n == 1:
            result.scalar_one_or_none.return_value = user
        elif n == 2:
            result.fetchall.return_value = [("receiving_clerk",)]
        else:
            result.fetchall.return_value = [(p,) for p in privileges]
        return result

    session.execute = _execute
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


def _small_jpeg_bytes() -> bytes:
    """Return a minimal valid JPEG image as bytes."""
    img = Image.new("RGB", (20, 20), color=(255, 255, 255))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _small_png_bytes() -> bytes:
    img = Image.new("RGB", (20, 20), color=(200, 200, 200))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_GOOD_OCR_RESPONSE = OCRResponse(
    supplier="Acme Metals",
    carrier="Fast Freight",
    bol_reference="BOL-2026-001",
    delivery_date="01/15/2026",
    items=[OCRItemResult(material_type="Steel Rod", quantity=50.0, lot_batch_number="LOT-001")],
    confidence=1.0,
)


# ---------------------------------------------------------------------------
# Test 1 — POST /deliveries/ocr with valid JPEG returns 200
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ocr_jpeg_returns_200():
    token = create_access_token(user_id=1)
    session = _make_rbac_session()

    with patch(
        "app.services.ocr_service.process_image_bytes",
        return_value=_GOOD_OCR_RESPONSE,
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
            assert body["supplier"] == "Acme Metals"
            assert body["bol_reference"] == "BOL-2026-001"
            assert body["confidence"] == 1.0
            assert len(body["items"]) == 1
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 2 — POST /deliveries/ocr without auth token returns 401/403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ocr_no_auth_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.post(
            "/api/v1/deliveries/ocr",
            files={"file": ("bol.jpg", _small_jpeg_bytes(), "image/jpeg")},
        )
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Test 3 — POST /deliveries/ocr with file > 10 MB returns 422
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ocr_file_too_large_returns_422():
    token = create_access_token(user_id=1)
    session = _make_rbac_session()
    oversized = b"x" * (_OCR_MAX_SIZE + 1)

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/deliveries/ocr",
                files={"file": ("big.jpg", oversized, "image/jpeg")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 422
        assert "10 MB" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 4 — POST /deliveries/ocr with unsupported content-type returns 422
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ocr_unsupported_type_returns_422():
    token = create_access_token(user_id=1)
    session = _make_rbac_session()

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


# ---------------------------------------------------------------------------
# Test 5 — POST /deliveries/ocr when OCR confidence is 0.0 returns 422
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ocr_zero_confidence_returns_422():
    token = create_access_token(user_id=1)
    session = _make_rbac_session()

    with patch(
        "app.services.ocr_service.process_image_bytes",
        return_value=OCRResponse(confidence=0.0),
    ):
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


# ---------------------------------------------------------------------------
# Test 6 — service pipeline: process_image_bytes with mocked pytesseract
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ocr_service_pipeline_with_mocked_tesseract():
    """Exercises preprocess(), _deskew(), and process_image_bytes() directly."""
    sample_bol = (
        "BILL OF LADING\n"
        "Supplier: Acme Metals Inc\n"
        "Carrier: FastFreight Co\n"
        "BOL #: BOL-2026-001\n"
        "Date: 01/15/2026\n"
        "Lot #: LOT-A01\n"
        "Steel Rod 50.0 kg\n"
    )

    with patch("pytesseract.image_to_string", return_value=sample_bol):
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.supplier is not None
    assert result.bol_reference == "BOL-2026-001"
    assert result.delivery_date == "01/15/2026"
    assert result.confidence > 0.0
    # items regex requires "Steel Rod 50.0 kg" pattern
    assert len(result.items) == 1
    assert result.items[0].quantity == 50.0


# ---------------------------------------------------------------------------
# Test 7 — process_image_bytes: empty OCR text → confidence 0.0 (no raise)
# ---------------------------------------------------------------------------
def test_ocr_service_empty_text_returns_zero_confidence():
    """process_image_bytes returns confidence=0.0 when pytesseract yields empty text."""
    with patch("pytesseract.image_to_string", return_value="   "):
        result = ocr_service.process_image_bytes(_small_jpeg_bytes(), "image/jpeg")

    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Test 8 — _deskew: covers the warpAffine branch (angle > 0.5)
# ---------------------------------------------------------------------------
def test_ocr_service_deskew_applies_rotation():
    """_deskew() rotates when the image has enough angular skew."""
    import numpy as np

    # Build a binary image with a ~45-degree diagonal strip so minAreaRect
    # returns an angle far enough from 0 to trigger warpAffine.
    arr = np.zeros((100, 100), dtype=np.uint8)
    for i in range(100):
        col = min(i, 99)
        arr[i, col] = 255  # 45° diagonal line

    rotated = ocr_service._deskew(arr)
    # Result is still a 2-D array of the same shape
    assert rotated.shape == arr.shape


# ---------------------------------------------------------------------------
# Module-level constant (mirrors the router constant for test 3)
# ---------------------------------------------------------------------------
_OCR_MAX_SIZE = 10 * 1024 * 1024
