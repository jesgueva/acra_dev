"""Tests for the unified Delivery Note document model (ACR-39).

Covers the read endpoints and their RBAC boundary, the schema validation rules that mirror the DB
CHECK constraints, and `generate_internal_note` — the entry point production approval (ACR-31)
calls to satisfy the §4.1 "every movement attaches to a note" invariant.
"""
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.delivery_note import DeliveryNote, DeliveryNoteType
from app.schemas.delivery_note import DeliveryNoteCreate
from tests.conftest import (
    _make_session,
    _make_user,
    _nested_transaction_mock,
    _override,
)

BASE_URL = "http://test"
_CREATED_AT = datetime(2026, 7, 23, tzinfo=timezone.utc)

# Either privilege opens the read endpoints — see routers/delivery_notes.py.
VIEWER_PRIVS = ["deliveries.view"]
SHIPPER_PRIVS = ["shipping.view"]


def _make_note(
    note_id: int = 900,
    note_type: str = "inbound",
    document_number: str = "BOL-2026-001",
    partner_id: int | None = 10,
    source: str | None = None,
    uploaded: bool = True,
) -> DeliveryNote:
    n = DeliveryNote()
    n.id = note_id
    n.type = note_type
    n.source = source
    n.partner_id = partner_id
    n.document_number = document_number
    n.document_date = "2026-07-23"
    n.uploaded = uploaded
    n.notes = None
    n.created_by = 1
    n.created_at = _CREATED_AT
    return n


def _make_contact(contact_id: int = 10, name: str = "Acme Metals"):
    from app.models.contact import Contact

    c = Contact()
    c.id = contact_id
    c.name = name
    c.type = "provider"
    return c


# ---------------------------------------------------------------------------
# HTTP — GET /delivery-notes
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_delivery_notes_returns_paginated():
    user = _make_user()
    token = create_access_token(user_id=1)
    note = _make_note()
    contact = _make_contact()

    def h_count(r):
        r.scalar.return_value = 1

    def h_rows(r):
        r.scalars.return_value.all.return_value = [note]

    def h_partners(r):
        r.scalars.return_value.all.return_value = [contact]

    session = _make_session(
        user, ["receiving_clerk"], VIEWER_PRIVS, [h_count, h_rows, h_partners]
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/delivery-notes",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 20
        result = body["results"][0]
        assert result["id"] == 900
        assert result["type"] == "inbound"
        assert result["document_number"] == "BOL-2026-001"
        assert result["uploaded"] is True
        assert result["partner_name"] == "Acme Metals"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_list_delivery_notes_accepts_shipping_privilege():
    """`shipping.view` alone also opens the endpoint (require_any_privilege)."""
    user = _make_user()
    token = create_access_token(user_id=1)

    def h_count(r):
        r.scalar.return_value = 0

    def h_rows(r):
        r.scalars.return_value.all.return_value = []

    session = _make_session(
        user, ["shipping_clerk"], SHIPPER_PRIVS, [h_count, h_rows]
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/delivery-notes",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        assert resp.json()["results"] == []
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"type": "internal"},
        {"partner_id": 10},
        {"date_from": "2026-07-01", "date_to": "2026-07-31"},
    ],
    ids=["type", "partner", "date-range"],
)
async def test_list_delivery_notes_filters_are_accepted(params):
    user = _make_user()
    token = create_access_token(user_id=1)

    def h_count(r):
        r.scalar.return_value = 0

    def h_rows(r):
        r.scalars.return_value.all.return_value = []

    session = _make_session(user, ["receiving_clerk"], VIEWER_PRIVS, [h_count, h_rows])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/delivery-notes",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_get_delivery_note_returns_200():
    user = _make_user()
    token = create_access_token(user_id=1)
    note = _make_note(note_type="direct_customer", source="SC", uploaded=False)
    contact = _make_contact()

    def h_note(r):
        r.scalar_one_or_none.return_value = note

    def h_partners(r):
        r.scalars.return_value.all.return_value = [contact]

    session = _make_session(user, ["receiving_clerk"], VIEWER_PRIVS, [h_note, h_partners])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/delivery-notes/900",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 900
        assert body["type"] == "direct_customer"
        assert body["source"] == "SC"
        assert body["uploaded"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_get_delivery_note_unknown_id_returns_404():
    user = _make_user()
    token = create_access_token(user_id=1)

    def h_missing(r):
        r.scalar_one_or_none.return_value = None

    session = _make_session(user, ["receiving_clerk"], VIEWER_PRIVS, [h_missing])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/delivery-notes/4242",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 404
        assert "4242" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# RBAC — a user with neither privilege is blocked, not merely hidden from
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/v1/delivery-notes", "/api/v1/delivery-notes/900"]
)
async def test_delivery_notes_forbidden_without_privilege(path):
    user = _make_user()
    token = create_access_token(user_id=1)
    session = _make_session(user, ["machine_operator"], ["work_orders.view"])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/v1/delivery-notes", "/api/v1/delivery-notes/900"]
)
async def test_delivery_notes_require_auth(path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.get(path)
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Schema validation — mirrors the DB CHECK constraints
# ---------------------------------------------------------------------------
def test_schema_rejects_unknown_type():
    with pytest.raises(ValidationError):
        DeliveryNoteCreate(
            type="not_a_type",
            document_number="X-1",
            document_date="2026-07-23",
        )


@pytest.mark.parametrize("blank", ["", "   "])
def test_schema_rejects_blank_document_number(blank):
    with pytest.raises(ValidationError):
        DeliveryNoteCreate(
            type=DeliveryNoteType.INBOUND,
            document_number=blank,
            document_date="2026-07-23",
        )


@pytest.mark.parametrize("blank", ["", "   "])
def test_schema_rejects_blank_document_date(blank):
    with pytest.raises(ValidationError):
        DeliveryNoteCreate(
            type=DeliveryNoteType.INBOUND,
            document_number="X-1",
            document_date=blank,
        )


def test_schema_rejects_source_on_non_direct_customer_note():
    """§4.3 — only a direct-customer note names an originating location."""
    with pytest.raises(ValidationError, match="direct_customer"):
        DeliveryNoteCreate(
            type=DeliveryNoteType.TRANSFER,
            document_number="X-1",
            document_date="2026-07-23",
            source="SC",
        )


def test_schema_allows_source_on_direct_customer_note():
    note = DeliveryNoteCreate(
        type=DeliveryNoteType.DIRECT_CUSTOMER,
        document_number="X-1",
        document_date="2026-07-23",
        source="SC",
    )
    assert note.source == "SC"


def test_schema_normalizes_empty_source_to_none():
    note = DeliveryNoteCreate(
        type=DeliveryNoteType.TRANSFER,
        document_number="  X-1  ",
        document_date="2026-07-23",
        source="   ",
    )
    assert note.source is None
    assert note.document_number == "X-1"


def test_schema_rejects_overlong_document_number():
    with pytest.raises(ValidationError):
        DeliveryNoteCreate(
            type=DeliveryNoteType.INBOUND,
            document_number="X" * 101,
            document_date="2026-07-23",
        )


# ---------------------------------------------------------------------------
# Service — internal note generation (the ACR-31 entry point)
# ---------------------------------------------------------------------------
def _session_returning(scalar_value=None, scalars_list=None):
    """Minimal session whose single query returns `scalar_value` / `scalars_list`."""
    session = AsyncMock()
    added: list = []

    async def _execute(query, *a, **kw):
        result = MagicMock()
        result.scalar.return_value = scalar_value
        result.scalars.return_value.all.return_value = scalars_list or []
        return result

    session.execute = _execute
    session.add = MagicMock(side_effect=added.append)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.begin_nested = _nested_transaction_mock()
    session.added = added
    return session


@pytest.mark.asyncio
async def test_generate_internal_note_shape():
    from app.services.delivery_note_service import generate_internal_note

    session = _session_returning(scalar_value=None)
    note = await generate_internal_note(
        session, user_id=7, reason="worksheet 42 approved", on=date(2026, 7, 23)
    )

    assert note.type == "internal"
    assert note.uploaded is False
    assert note.partner_id is None      # production has no counterparty
    assert note.source is None
    assert note.document_number == "INT-20260723-0001"
    assert note.document_date == "2026-07-23"
    assert note.created_by == 7
    assert note.notes == "worksheet 42 approved"
    # Caller owns the transaction so the note lands with its movements.
    assert session.commit.called is False
    assert session.flush.called is True


@pytest.mark.asyncio
async def test_generate_internal_note_increments_within_a_day():
    from app.services.delivery_note_service import generate_internal_note

    session = _session_returning(scalar_value="INT-20260723-0006")
    note = await generate_internal_note(session, user_id=1, on=date(2026, 7, 23))
    assert note.document_number == "INT-20260723-0007"


@pytest.mark.asyncio
async def test_generate_internal_note_restarts_each_day():
    from app.services.delivery_note_service import generate_internal_note

    session = _session_returning(scalar_value=None)
    note = await generate_internal_note(session, user_id=1, on=date(2026, 7, 24))
    assert note.document_number == "INT-20260724-0001"


@pytest.mark.asyncio
async def test_generate_internal_note_survives_unparseable_existing_number():
    """A hand-edited number must not wedge production approval."""
    from app.services.delivery_note_service import generate_internal_note

    session = _session_returning(scalar_value="INT-20260723-oops")
    note = await generate_internal_note(session, user_id=1, on=date(2026, 7, 23))
    assert note.document_number == "INT-20260723-0001"


# ---------------------------------------------------------------------------
# Service — document-number de-duplication (shared with migration 011)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dedupe_returns_number_unchanged_when_free():
    from app.services.delivery_note_service import dedupe_document_number

    session = _session_returning(scalars_list=[])
    assert await dedupe_document_number(session, "inbound", "BOL-1") == "BOL-1"


@pytest.mark.asyncio
async def test_dedupe_suffixes_a_taken_number():
    from app.services.delivery_note_service import dedupe_document_number

    session = _session_returning(scalars_list=["BOL-1"])
    assert await dedupe_document_number(session, "inbound", "BOL-1") == "BOL-1 (2)"


@pytest.mark.asyncio
async def test_dedupe_skips_to_the_next_free_suffix():
    from app.services.delivery_note_service import dedupe_document_number

    session = _session_returning(scalars_list=["BOL-1", "BOL-1 (2)", "BOL-1 (3)"])
    assert await dedupe_document_number(session, "inbound", "BOL-1") == "BOL-1 (4)"


# ---------------------------------------------------------------------------
# Service — add_document_note, the shared inbound/outbound creation path
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_add_document_note_sets_the_document_facts():
    from app.services.delivery_note_service import add_document_note

    session = _session_returning(scalars_list=[])
    note = await add_document_note(
        session,
        note_type="direct_customer",
        document_number="AV26-9",
        document_date="2026-07-23",
        partner_id=4,
        source="SC",
        uploaded=False,
        created_by=3,
    )

    assert note.type == "direct_customer"
    assert note.document_number == "AV26-9"
    assert note.source == "SC"
    assert note.partner_id == 4
    assert note.created_by == 3
    # The caller owns the transaction so the note lands with its header.
    assert session.commit.called is False


@pytest.mark.asyncio
async def test_add_document_note_dedupes_a_taken_number():
    from app.services.delivery_note_service import add_document_note

    session = _session_returning(scalars_list=["BOL-1"])
    note = await add_document_note(
        session,
        note_type="inbound",
        document_number="BOL-1",
        document_date="2026-07-23",
        created_by=1,
        uploaded=True,
    )
    assert note.document_number == "BOL-1 (2)"


@pytest.mark.asyncio
async def test_insert_retries_when_a_racing_transaction_takes_the_number():
    """A concurrent caller can claim the same number between the read and the write."""
    from sqlalchemy.exc import IntegrityError

    from app.services.delivery_note_service import _insert_with_free_number

    numbers = iter(["INT-1", "INT-2"])
    session = AsyncMock()
    session.add = MagicMock()
    session.begin_nested = _nested_transaction_mock()
    # First flush loses the race; the second succeeds.
    session.flush = AsyncMock(
        side_effect=[IntegrityError("insert", {}, Exception("duplicate key")), None]
    )

    async def _next() -> str:
        return next(numbers)

    note = await _insert_with_free_number(
        session,
        next_number=_next,
        build=lambda number: DeliveryNote(
            type="internal",
            document_number=number,
            document_date="2026-07-23",
            uploaded=False,
            created_by=1,
        ),
    )

    assert note.document_number == "INT-2"
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_insert_gives_up_after_repeated_collisions():
    from sqlalchemy.exc import IntegrityError

    from app.services.delivery_note_service import _insert_with_free_number

    session = AsyncMock()
    session.add = MagicMock()
    session.begin_nested = _nested_transaction_mock()
    session.flush = AsyncMock(
        side_effect=IntegrityError("insert", {}, Exception("duplicate key"))
    )

    async def _next() -> str:
        return "INT-STUCK"

    with pytest.raises(IntegrityError):
        await _insert_with_free_number(
            session,
            next_number=_next,
            build=lambda number: DeliveryNote(
                type="internal",
                document_number=number,
                document_date="2026-07-23",
                uploaded=False,
                created_by=1,
            ),
            attempts=3,
        )
    assert session.flush.await_count == 3
