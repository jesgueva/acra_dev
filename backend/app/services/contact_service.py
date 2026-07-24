from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.contact import Contact
from app.schemas.contact import ContactCreate, ContactUpdate, ContactListResponse, ContactResponse


async def list_contacts(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    type_filter: str | None = None,
    name: str | None = None,
) -> ContactListResponse:
    q = select(Contact)
    if type_filter:
        q = q.where(Contact.type == type_filter)
    if name:
        q = q.where(Contact.name.ilike(f"%{name}%"))
    count_res = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_res.scalar() or 0
    offset = (page - 1) * page_size
    res = await db.execute(q.offset(offset).limit(page_size))
    items = res.scalars().all()
    return ContactListResponse(total=total, page=page, page_size=page_size, results=list(items))


async def get_contact(db: AsyncSession, contact_id: int) -> Contact:
    res = await db.execute(select(Contact).where(Contact.id == contact_id))
    contact = res.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return contact


async def create_contact(db: AsyncSession, data: ContactCreate) -> ContactResponse:
    contact = Contact(**data.model_dump())
    db.add(contact)
    await db.commit()
    return ContactResponse.model_validate(contact)


async def update_contact(db: AsyncSession, contact_id: int, data: ContactUpdate) -> ContactResponse:
    contact = await get_contact(db, contact_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(contact, k, v)
    await db.commit()
    return ContactResponse.model_validate(contact)


async def delete_contact(db: AsyncSession, contact_id: int) -> None:
    contact = await get_contact(db, contact_id)
    await db.delete(contact)
    await db.commit()
