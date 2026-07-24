from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.schemas.product import ProductListResponse, ProductResponse
from tests.conftest import _make_rbac_session, _override

BASE_URL = "http://test"

_PRODUCT_RESPONSE = ProductResponse(
    id=1,
    name="Steel Rod",
    description="Grade A steel",
    category="raw",
    contact_id=None,
    created_at=datetime(2026, 4, 9, tzinfo=timezone.utc),
)

_VALID_BODY = {
    "name": "Steel Rod",
    "description": "Grade A steel",
    "category": "raw",
    "contact_id": None,
}


# ---------------------------------------------------------------------------
# HTTP Test 1 — GET /products → 200
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_products_returns_200():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("master_data.view",))
    mock_list = ProductListResponse(total=0, page=1, page_size=20, results=[])

    with patch("app.services.product_service.list_products", new=AsyncMock(return_value=mock_list)):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.get(
                    "/api/v1/products",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 0
            assert body["page"] == 1
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# HTTP Test 2 — GET /products without token → 401/403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_products_no_auth_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.get("/api/v1/products")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# HTTP Test 3 — POST /products → 201
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_product_returns_201():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("master_data.manage",))

    with patch("app.services.product_service.create_product", new=AsyncMock(return_value=_PRODUCT_RESPONSE)):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.post(
                    "/api/v1/products",
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 201
            body = resp.json()
            assert body["id"] == 1
            assert body["name"] == "Steel Rod"
            assert body["category"] == "raw"
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# HTTP Test 4 — POST /products without token → 401/403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_product_no_auth_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.post("/api/v1/products", json=_VALID_BODY)
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# HTTP Test 5 — GET /products/{id} → 200
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_product_returns_200():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("master_data.view",))

    with patch("app.services.product_service.get_product", new=AsyncMock(return_value=_PRODUCT_RESPONSE)):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.get(
                    "/api/v1/products/1",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            assert resp.json()["id"] == 1
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# HTTP Test 6 — GET /products/{id} → 404 when not found
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_product_returns_404():
    from fastapi import HTTPException

    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("master_data.view",))

    with patch(
        "app.services.product_service.get_product",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Product not found")),
    ):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.get(
                    "/api/v1/products/9999",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# HTTP Test 7 — PATCH /products/{id} → 200
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_update_product_returns_200():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("master_data.manage",))
    updated = _PRODUCT_RESPONSE.model_copy(update={"name": "Aluminum Rod"})

    with patch("app.services.product_service.update_product", new=AsyncMock(return_value=updated)):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.patch(
                    "/api/v1/products/1",
                    json={"name": "Aluminum Rod"},
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            assert resp.json()["name"] == "Aluminum Rod"
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# HTTP Test 8 — DELETE /products/{id} → 204
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delete_product_returns_204():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("master_data.manage",))

    with patch("app.services.product_service.delete_product", new=AsyncMock(return_value=None)):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.delete(
                    "/api/v1/products/1",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 204
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Service Test 9 — create_product stores correct fields
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_create_product_stores_fields():
    from app.services.product_service import create_product
    from app.schemas.product import ProductCreate

    session = AsyncMock()
    session.commit = AsyncMock()

    data = ProductCreate(
        name="Finished Widget",
        description="A finished product",
        category="finished",
        contact_id=None,
    )

    added_obj = None

    def _add(obj):
        nonlocal added_obj
        added_obj = obj
        obj.id = 10
        obj.created_at = datetime(2026, 4, 9, tzinfo=timezone.utc)

    session.add = MagicMock(side_effect=_add)

    result = await create_product(db=session, data=data)

    assert result.name == "Finished Widget"
    assert result.category == "finished"
    assert result.contact_id is None
    assert session.commit.called


# ---------------------------------------------------------------------------
# Service Test 10 — delete_product removes the record
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_delete_product_removes_record():
    from app.services.product_service import delete_product
    from app.models.product import Product

    mock_product = Product()
    mock_product.id = 1
    mock_product.name = "To Delete"
    mock_product.category = "raw"

    session = AsyncMock()

    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = mock_product
    session.execute = AsyncMock(return_value=get_result)
    session.delete = AsyncMock()
    session.commit = AsyncMock()

    await delete_product(db=session, product_id=1)

    session.delete.assert_called_once_with(mock_product)
    session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Service Test 11 — product with contact_id links correctly
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_create_product_with_contact_id():
    from app.services.product_service import create_product
    from app.schemas.product import ProductCreate

    session = AsyncMock()
    session.commit = AsyncMock()

    data = ProductCreate(
        name="Raw Material A",
        description=None,
        category="raw",
        contact_id=5,
    )

    def _add(obj):
        obj.id = 20
        obj.created_at = datetime(2026, 4, 9, tzinfo=timezone.utc)

    session.add = MagicMock(side_effect=_add)

    result = await create_product(db=session, data=data)

    assert result.contact_id == 5
    assert result.category == "raw"


# ---------------------------------------------------------------------------
# HTTP Test 12 — Filter by category works
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_products_filter_by_category():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("master_data.view",))
    finished_product = ProductResponse(
        id=2,
        name="Widget A",
        description=None,
        category="finished",
        contact_id=None,
        created_at=datetime(2026, 4, 9, tzinfo=timezone.utc),
    )
    mock_list = ProductListResponse(total=1, page=1, page_size=20, results=[finished_product])

    captured_kwargs = {}

    async def _mock_list(**kwargs):
        captured_kwargs.update(kwargs)
        return mock_list

    with patch("app.services.product_service.list_products", new=_mock_list):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.get(
                    "/api/v1/products?category=finished",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 1
            assert body["results"][0]["category"] == "finished"
            assert captured_kwargs.get("category") == "finished"
        finally:
            app.dependency_overrides.pop(get_db, None)
