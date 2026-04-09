import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import JWTError

from app.core.config import settings  # noqa: F401 — ensures .env is loaded early

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("acra")

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Global error handlers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

from app.routers.audit import router as audit_router  # noqa: E402
from app.routers.auth import router as auth_router  # noqa: E402
from app.routers.deliveries import router as deliveries_router  # noqa: E402
from app.routers.inventory import router as inventory_router  # noqa: E402
from app.routers.work_orders import router as work_orders_router  # noqa: E402

app.include_router(audit_router)
app.include_router(auth_router)
app.include_router(deliveries_router)
app.include_router(inventory_router)
app.include_router(work_orders_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
