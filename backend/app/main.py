from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .auth import router as auth_router
from .auth import validate_session_configuration
from .cost_centers import router as cost_centers_router
from .current_states import router as current_states_router
from .dashboard import router as dashboard_router
from .imports import router as imports_router
from .request_limits import ImportBodyLimitMiddleware
from .readiness import is_ready
from .users import router as users_router


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
app.add_middleware(ImportBodyLimitMiddleware)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(cost_centers_router)
app.include_router(imports_router)
app.include_router(current_states_router)
app.include_router(dashboard_router)


@app.get("/health", tags=["system"])
@app.get("/api/health", tags=["system"])
def health() -> dict[str, str]:
    """Report process liveness only; dependency readiness is exposed separately."""
    return {"status": "ok"}


@app.get("/ready", tags=["system"])
@app.get("/api/ready", tags=["system"])
def ready() -> dict[str, str]:
    """Report dependency readiness without disclosing failing infrastructure details."""
    if is_ready():
        return {"status": "ok"}
    return JSONResponse(status_code=503, content={"status": "unavailable"})
