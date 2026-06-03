"""
FastAPI application — Store Intelligence System API.

API endpoints:
  GET /metrics       — primary KPI endpoint
  GET /events        — event log
  GET /metrics/funnel — visitor funnel
  GET /anomalies     — anomaly list
  GET /health        — health check

Additional endpoints:
  GET /metrics/occupancy  — zone occupancy
  GET /metrics/heatmap    — heatmap data
  POST /pipeline/run      — trigger pipeline
  POST /pipeline/seed     — seed with synthetic data
  GET /docs              — Swagger UI
  GET /redoc             — ReDoc
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from src.api.models.database import get_engine, health_check
from src.api.routers import anomalies, events, metrics, challenge
from src.api.routers.funnel import router as pipeline_router
from src.api.routers.visitors import router as visitors_router
from src.api.routers.gestures import router as gestures_router
from src.shared.config import settings
from src.shared.logger import configure_logging, get_logger

configure_logging(settings.log_level)
logger = get_logger(__name__)

# Track uptime
START_TIME = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: setup resources if needed
    yield

    logger.info("Shutting down Store Intelligence API")


app = FastAPI(
    title="Store Intelligence System API",
    description=(
        "AI Store Intelligence System — Retail CCTV Analytics\n\n"
        "Transforms raw CCTV tracking data into actionable retail intelligence.\n\n"
        "**Key Endpoints:**\n"
        "- `GET /metrics` — Store KPIs (footfall, dwell, conversion)\n"
        "- `GET /metrics/funnel` — Visitor journey funnel\n"
        "- `GET /events` — Paginated event log\n"
        "- `GET /anomalies` — Detected anomalies\n"
        "- `POST /pipeline/seed` — Seed with synthetic data\n"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "Request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
    )
    response.headers["X-Response-Time-ms"] = str(duration_ms)
    return response


# ── Prometheus metrics ────────────────────────────────────────────────────────
Instrumentator().instrument(app).expose(app, endpoint="/metrics/prometheus")

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(metrics.router)
app.include_router(events.router)
app.include_router(anomalies.router)
app.include_router(pipeline_router)
app.include_router(visitors_router)
app.include_router(gestures_router)
app.include_router(challenge_router)

# ── Root & Health ─────────────────────────────────────────────────────────────

@app.get("/", tags=["root"], summary="API root")
async def root() -> dict:
    return {
        "service": "Store Intelligence System",
        "version": "1.0.0",
        "project": "AI Store Intelligence System",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }





if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        log_level=settings.log_level.lower(),
    )
