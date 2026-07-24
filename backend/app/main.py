import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import JWTError

from app.core.config import settings  # noqa: F401 — ensures .env is loaded early

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("acra")

app = FastAPI(
    title="ACRA MES API",
    description="ACRA Integrated Manufacturing Execution System",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(JWTError)
async def jwt_error_handler(request: Request, exc: JWTError) -> JSONResponse:
    logger.warning("JWT error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "Invalid or expired token"},
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


from app.routers.audit import router as audit_router  # noqa: E402
from app.routers.auth import router as auth_router  # noqa: E402
from app.routers.contacts import router as contacts_router  # noqa: E402
from app.routers.deliveries import router as deliveries_router  # noqa: E402
from app.routers.delivery_notes import router as delivery_notes_router  # noqa: E402
from app.routers.inventory import router as inventory_router  # noqa: E402
from app.routers.production_worksheets import router as production_worksheets_router  # noqa: E402
from app.routers.products import router as products_router  # noqa: E402
from app.routers.reservations import router as reservations_router  # noqa: E402
from app.routers.roles import router as roles_router  # noqa: E402
from app.routers.shipments import router as shipments_router  # noqa: E402
from app.routers.stock_movements import router as stock_movements_router  # noqa: E402
from app.routers.users import router as users_router  # noqa: E402
from app.routers.work_orders import router as work_orders_router  # noqa: E402

app.include_router(audit_router)
app.include_router(auth_router)
app.include_router(contacts_router)
app.include_router(deliveries_router)
app.include_router(delivery_notes_router)
app.include_router(inventory_router)
app.include_router(production_worksheets_router)
app.include_router(products_router)
app.include_router(reservations_router)
app.include_router(roles_router)
app.include_router(shipments_router)
app.include_router(stock_movements_router)  # Phase 2 ledger surface (skeleton — returns 501)
app.include_router(users_router)
app.include_router(work_orders_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
