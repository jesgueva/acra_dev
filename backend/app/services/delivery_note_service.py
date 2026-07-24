"""Delivery Note reads, plus the internal-note generator production depends on."""

from datetime import date
from typing import Awaitable, Callable, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.delivery_note import DeliveryNote, DeliveryNoteType
from app.schemas.delivery_note import (
    DeliveryNoteListResponse,
    DeliveryNoteResponse,
)

#: Prefix for system-generated internal notes: INT-20260723-0007.
_INTERNAL_PREFIX = "INT"


def _response(note: DeliveryNote, partner_name: Optional[str]) -> DeliveryNoteResponse:
    return DeliveryNoteResponse(
        id=note.id,
        type=note.type,
        source=note.source,
        partner_id=note.partner_id,
        partner_name=partner_name,
        document_number=note.document_number,
        document_date=note.document_date,
        uploaded=note.uploaded,
        notes=note.notes,
        created_by=note.created_by,
        created_at=note.created_at,
    )


async def _load_partners(db: AsyncSession, ids: set[int]) -> dict[int, Contact]:
    if not ids:
        return {}
    res = await db.execute(select(Contact).where(Contact.id.in_(ids)))
    return {c.id: c for c in res.scalars().all()}


async def _next_internal_number(db: AsyncSession, on: Optional[date] = None) -> str:
    """Next `INT-YYYYMMDD-NNNN` for the given day.

    Numbered per-day so an operator can cite a short reference on the floor. Derived from the
    highest existing number for that date rather than a global counter, so the sequence stays
    readable and gap-free within a day.
    """
    day = (on or date.today()).strftime("%Y%m%d")
    prefix = f"{_INTERNAL_PREFIX}-{day}-"
    highest = (
        await db.execute(
            select(func.max(DeliveryNote.document_number)).where(
                DeliveryNote.type == DeliveryNoteType.INTERNAL.value,
                DeliveryNote.document_number.like(f"{prefix}%"),
            )
        )
    ).scalar()

    seq = 1
    if highest:
        try:
            seq = int(highest.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            # A hand-edited number that does not parse must not wedge production.
            seq = 1
    return f"{prefix}{seq:04d}"


async def dedupe_document_number(
    db: AsyncSession, note_type: str, document_number: str
) -> str:
    """Return `document_number`, suffixed ` (n)` if that `(type, number)` is already taken.

    Receiving deliberately allows a repeated BoL through `force=true`, but the notes table is
    uniquely keyed on `(type, document_number)`. Suffixing keeps both facts true and matches how
    migration 011 de-duplicates the historical rows, so runtime and backfill agree.
    """
    taken = set(
        (
            await db.execute(
                select(DeliveryNote.document_number).where(
                    DeliveryNote.type == note_type,
                    DeliveryNote.document_number.like(f"{document_number}%"),
                )
            )
        )
        .scalars()
        .all()
    )
    if document_number not in taken:
        return document_number
    n = 2
    while f"{document_number} ({n})" in taken:
        n += 1
    return f"{document_number} ({n})"


async def _insert_with_free_number(
    db: AsyncSession,
    *,
    next_number: Callable[[], Awaitable[str]],
    build: Callable[[str], DeliveryNote],
    attempts: int = 5,
) -> DeliveryNote:
    """Insert a note, re-deriving its document number if a racing transaction takes it first.

    Both number sources read the table and then write, so two concurrent callers can pick the
    same string and one loses to `uq_delivery_notes_type_document_number`. That is a live risk
    for the flows this serves — concurrent worksheet approvals (ACR-31) and two clerks forcing
    the same BoL — so retry inside a SAVEPOINT, which rolls back only the failed INSERT and
    leaves the caller's transaction usable.
    """
    for attempt in range(1, attempts + 1):
        try:
            async with db.begin_nested():
                note = build(await next_number())
                db.add(note)
                await db.flush()
            return note
        except IntegrityError:
            if attempt == attempts:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


async def generate_internal_note(
    db: AsyncSession,
    *,
    user_id: int,
    reason: Optional[str] = None,
    on: Optional[date] = None,
) -> DeliveryNote:
    """Create the INTERNAL note that production Issue/Receipt movements attach to (§4.2).

    Does **not** commit — the caller owns the transaction, so the note and the movements it
    justifies land together or not at all. This is the entry point ACR-31 calls on worksheet
    approval.
    """
    today = on or date.today()
    return await _insert_with_free_number(
        db,
        next_number=lambda: _next_internal_number(db, today),
        build=lambda number: DeliveryNote(
            type=DeliveryNoteType.INTERNAL.value,
            source=None,
            partner_id=None,      # production consumes from ourselves; no counterparty
            document_number=number,
            document_date=today.isoformat(),
            uploaded=False,       # §4.2 — system-generated
            notes=reason,
            created_by=user_id,
        ),
    )


async def add_document_note(
    db: AsyncSession,
    *,
    note_type: str,
    document_number: str,
    document_date: str,
    created_by: int,
    partner_id: Optional[int] = None,
    source: Optional[str] = None,
    uploaded: bool = False,
) -> DeliveryNote:
    """Create the note behind an inbound delivery or an outbound shipment.

    The requested `document_number` is de-duplicated if it is already taken. Does not commit —
    the note and the header it belongs to land in one transaction.
    """
    return await _insert_with_free_number(
        db,
        next_number=lambda: dedupe_document_number(db, note_type, document_number),
        build=lambda number: DeliveryNote(
            type=note_type,
            source=source,
            partner_id=partner_id,
            document_number=number,
            document_date=document_date,
            uploaded=uploaded,
            created_by=created_by,
        ),
    )


async def list_notes(
    db: AsyncSession,
    type_filter: Optional[str] = None,
    partner_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> DeliveryNoteListResponse:
    base = select(DeliveryNote)
    if type_filter:
        base = base.where(DeliveryNote.type == type_filter)
    if partner_id:
        base = base.where(DeliveryNote.partner_id == partner_id)
    if date_from:
        base = base.where(DeliveryNote.document_date >= date_from)
    if date_to:
        base = base.where(DeliveryNote.document_date <= date_to)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0

    offset = (page - 1) * page_size
    rows = (
        await db.execute(
            base.order_by(DeliveryNote.document_date.desc(), DeliveryNote.id.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).scalars().all()

    partners = await _load_partners(db, {n.partner_id for n in rows if n.partner_id})
    results = [
        _response(n, partners[n.partner_id].name if n.partner_id in partners else None)
        for n in rows
    ]
    return DeliveryNoteListResponse(
        total=total, page=page, page_size=page_size, results=results
    )


async def get_note(db: AsyncSession, note_id: int) -> DeliveryNoteResponse:
    note = (
        await db.execute(select(DeliveryNote).where(DeliveryNote.id == note_id))
    ).scalar_one_or_none()
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery note {note_id} not found",
        )

    partners = await _load_partners(db, {note.partner_id} if note.partner_id else set())
    return _response(
        note, partners[note.partner_id].name if note.partner_id in partners else None
    )
