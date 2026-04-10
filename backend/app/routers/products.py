from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_privilege
from app.schemas.auth import TokenUser
from app.schemas.product import ProductCreate, ProductListResponse, ProductResponse, ProductUpdate
from app.services import product_service

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("", response_model=ProductListResponse)
async def list_products(
    category: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: TokenUser = Depends(require_privilege("master_data.view")),
    db: AsyncSession = Depends(get_db),
) -> ProductListResponse:
    return await product_service.list_products(
        db=db, page=page, page_size=page_size, category=category, name=name
    )


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    current_user: TokenUser = Depends(require_privilege("master_data.view")),
    db: AsyncSession = Depends(get_db),
) -> ProductResponse:
    return await product_service.get_product(db=db, product_id=product_id)


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    body: ProductCreate,
    current_user: TokenUser = Depends(require_privilege("master_data.manage")),
    db: AsyncSession = Depends(get_db),
) -> ProductResponse:
    return await product_service.create_product(db=db, data=body)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    body: ProductUpdate,
    current_user: TokenUser = Depends(require_privilege("master_data.manage")),
    db: AsyncSession = Depends(get_db),
) -> ProductResponse:
    return await product_service.update_product(db=db, product_id=product_id, data=body)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    current_user: TokenUser = Depends(require_privilege("master_data.manage")),
    db: AsyncSession = Depends(get_db),
) -> None:
    await product_service.delete_product(db=db, product_id=product_id)
