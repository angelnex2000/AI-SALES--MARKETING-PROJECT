"""Application entry point.

Deliberately thin: create the app, wire middleware, mount routers. No
business logic lives here — routers receive requests, services decide.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.exceptions import register_exception_handlers
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.routers import (
    ai,
    analytics,
    auth,
    billing,
    campaigns,
    deals,
    integrations,
    jobs,
    leads,
    meetings,
    outreach,
    rag,
    users,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info(
        "starting %s",
        settings.APP_NAME,
        extra={"environment": settings.ENVIRONMENT, "api_prefix": settings.API_V1_PREFIX},
    )
    # Loud but non-fatal: a production box with a placeholder secret should
    # complain in the logs rather than refuse to boot mid-incident.
    for problem in settings.check_production_readiness():
        logger.warning("production readiness: %s", problem)
    yield
    logger.info("shutting down %s", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
    # Interactive docs expose the full schema of a multi-tenant API — fine in
    # dev, off in production.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

# Phase 5 Module 11 — one uniform error envelope for the whole API.
register_exception_handlers(app)

# Starlette's add_middleware inserts at the front of the stack, so the LAST
# one added is the outermost. Request logging goes last on purpose: it then
# wraps CORS and sees every response, including CORS preflight rejections.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,  # required — auth rides in an httpOnly cookie
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],  # lets the frontend quote an id in bug reports
)
app.add_middleware(RequestLoggingMiddleware)

# Phase 5 Module 1 — everything is versioned so v2 can land later without
# breaking existing clients. The prefix is configuration, not a literal.
API = settings.API_V1_PREFIX

# Routers that own multiple top-level paths mount at API root and declare full
# paths internally (users → /users + /roles + /permissions; deals → /deals +
# /pipeline). The rest mount under their domain prefix.
app.include_router(auth.router, prefix=f"{API}/auth", tags=["auth"])
app.include_router(users.router, prefix=API, tags=["users"])
app.include_router(leads.router, prefix=f"{API}/leads", tags=["leads"])
app.include_router(deals.router, prefix=API, tags=["deals"])
app.include_router(campaigns.router, prefix=f"{API}/campaigns", tags=["campaigns"])
app.include_router(outreach.router, prefix=f"{API}/outreach", tags=["outreach"])
app.include_router(meetings.router, prefix=f"{API}/meetings", tags=["meetings"])
app.include_router(ai.router, prefix=f"{API}/ai", tags=["ai"])
app.include_router(rag.router, prefix=f"{API}/rag", tags=["rag"])
app.include_router(analytics.router, prefix=f"{API}/analytics", tags=["analytics"])
app.include_router(integrations.router, prefix=f"{API}/integrations", tags=["integrations"])
app.include_router(billing.router, prefix=f"{API}/billing", tags=["billing"])
app.include_router(jobs.router, prefix=f"{API}/jobs", tags=["jobs"])


# Operational endpoints stay unversioned at the root and return plain JSON,
# not the {success, message, data} envelope: their consumers are load
# balancers and orchestrators, not our frontend.


@app.get("/", tags=["ops"])
async def root() -> dict[str, str]:
    return {
        "service": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "api": API,
        "status": "running",
    }


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """Liveness: is the process up? Touches no dependency on purpose — a
    database blip must not make the orchestrator kill healthy containers."""
    return {"status": "ok", "service": settings.APP_NAME}


@app.get("/health/ready", tags=["ops"])
async def readiness(response: Response) -> dict[str, object]:
    """Readiness: can this instance actually serve traffic? Checks the
    dependencies a request needs, so a broken instance is pulled from the
    load balancer instead of accepting requests it cannot fulfil."""
    checks: dict[str, str] = {}

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.error("readiness: database unreachable", exc_info=exc)
        checks["database"] = "unavailable"

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.REDIS_URL)
        try:
            await client.ping()
            checks["redis"] = "ok"
        finally:
            await client.aclose()
    except Exception as exc:
        logger.error("readiness: redis unreachable", exc_info=exc)
        checks["redis"] = "unavailable"

    ready = all(value == "ok" for value in checks.values())
    # Must be a real 503, not a 200 with a sad body — orchestrators route on
    # the status code.
    response.status_code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "degraded", **checks}
