from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from .auth import router as auth_router
from .auth import validate_session_configuration
from .imports import router as imports_router
from .request_limits import SystemImportBodyLimitMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Reject invalid session configuration before the server accepts traffic."""
    validate_session_configuration()
    yield


app = FastAPI(
    title="Asset Reconciliation API",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(SystemImportBodyLimitMiddleware)
app.include_router(auth_router)
app.include_router(imports_router)


@app.get("/health", tags=["system"])
@app.get("/api/health", tags=["system"])
def health() -> dict[str, str]:
    """Report whether this API process is ready to receive requests."""
    return {"status": "ok"}
