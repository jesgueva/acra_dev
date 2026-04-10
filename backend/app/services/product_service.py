from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate, ProductListResponse, ProductResponse


async def list_products(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    category: str | None = None,
    name: str | None = None,
) -> ProductListResponse:
    q = select(Product)
    if category:
        q = q.where(Product.category == category)
    if name:
        q = q.where(Product.name.ilike(f"%{name}%"))
    count_res = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_res.scalar() or 0
    offset = (page - 1) * page_size
    res = await db.execute(q.offset(offset).limit(page_size))
    items = res.scalars().all()
    return ProductListResponse(total=total, page=page, page_size=page_size, results=list(items))


async def get_product(db: AsyncSession, product_id: int) -> Product:
    res = await db.execute(select(Product).where(Product.id == product_id))
    product = res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


async def create_product(db: AsyncSession, data: ProductCreate) -> ProductResponse:
    product = Product(**data.model_dump())
    db.add(product)
    await db.commit()
    return ProductResponse.model_validate(product)


async def update_product(db: AsyncSession, product_id: int, data: ProductUpdate) -> ProductResponse:
    product = await get_product(db, product_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(product, k, v)
    await db.commit()
    return ProductResponse.model_validate(product)


async def delete_product(db: AsyncSession, product_id: int) -> None:
    product = await get_product(db, product_id)
    await db.delete(product)
    await db.commit()
