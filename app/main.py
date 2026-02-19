# app/main.py
"""
JalSeva — Water Governance Accountability Platform
Main FastAPI application entry point.
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from app.core.config import settings
from app.api.alerts import router as alerts_router
from app.api.auth import router as auth_router

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    logger.info("JalSeva starting up", version=settings.APP_VERSION)

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

    # Pre-warm ML models (optional — lazy-loads on first use if this fails)
    try:
        from app.ml.ml_service import get_risk_scorer
        get_risk_scorer(settings.WATER_GOVERNANCE_MODEL_PATH)
        logger.info("ML models pre-warmed")
    except Exception as e:
        logger.warning("ML pre-warm failed (non-fatal)", error=str(e))

    yield

    logger.info("JalSeva shutting down")


app = FastAPI(
    title="JalSeva — Water Governance Accountability Platform",
    description="""
## 💧 JalSeva

AI-powered water scarcity governance system for India's Panchayati Raj institutions.

### Key features
- **Evidence-gated closure** — alerts close only after independent validation (FixMyStreet pattern)
- **NLI contradiction detection** — flags disputed resolution claims (Ushahidi pattern)
- **Multi-tier escalation** — Panchayat → Block → Mandal → District → State (Sahana Eden)
- **ML risk scoring** — pre-trained water governance model (water_governance_model.pkl)
- **LLM validation** — Gemini 1.5 Flash for coherence analysis
- **n8n integration** — automated email notifications via external workflow
- **Immutable audit trail** — every state transition logged with actor and timestamp

### Governance principle
An alert is **CLOSED** only when a VALIDATOR role submits evidence-backed approval.
""",
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Prometheus metrics (optional — skipped if package not installed) ──────────
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app)
    logger.info("Prometheus metrics enabled at /metrics")
except ImportError:
    logger.warning("prometheus_fastapi_instrumentator not installed — /metrics disabled (non-fatal)")

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(alerts_router)


# ── Root + Health ─────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "operational",
        "docs": "/docs",
        "governance_principle": "Alerts close only after verified evidence — FixMyStreet pattern",
    }


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "version": settings.APP_VERSION}


# ── Global error handler ──────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    tb = traceback.format_exc()
    logger.error("Unhandled exception", path=request.url.path, error=str(exc), traceback=tb)
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "type": type(exc).__name__,
            "path": str(request.url.path),
        }
    )