"""
NASQuay — FastAPI application entry point.
"""
from __future__ import annotations

import logging
import os.path
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.actions.registry import sync_actions
from app.config import get_settings
from app.database import connect, init_db
from app.version import get_version

# ── Routers ───────────────────────────────────────────────────────────────────
from app.api import audit    as audit_router
from app.api import auth     as auth_router
from app.api import nas      as nas_router
from app.api import roles    as roles_router
from app.api import settings as settings_router
from app.api import system   as system_router
from app.api import tools    as tools_router
from app.api import users    as users_router

log = logging.getLogger("nasquay")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    # ── Startup ───────────────────────────────────────────────────────────────
    get_settings()  # refuses to start with a missing or placeholder key
    await init_db()
    conn = await connect()
    try:
        await sync_actions(conn)
    finally:
        await conn.close()
    log.info("NASQuay %s started", get_version())

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    log.info("NASQuay shutting down")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="NASQuay",
    description="Self-hosted operation of QNAP NAS units",
    version=get_version(),
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ── API Routers ───────────────────────────────────────────────────────────────

app.include_router(auth_router.router,     prefix="/api/auth",     tags=["auth"])
app.include_router(users_router.router,    prefix="/api/users",    tags=["users"])
app.include_router(roles_router.router,    prefix="/api/roles",    tags=["roles"])
app.include_router(nas_router.router,      prefix="/api/nas",      tags=["nas"])
app.include_router(audit_router.router,    prefix="/api/audit",    tags=["audit"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(system_router.router,   prefix="/api/system",   tags=["system"])
app.include_router(tools_router.router,    prefix="/api/tools",    tags=["tools"])


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/api/health", tags=["system"])
async def health() -> dict[str, str]:
    """Public and unauthenticated: says only that the service is up, and its version."""
    return {"status": "ok", "version": get_version()}


# ── The web interface ─────────────────────────────────────────────────────────
# Serves frontend/dist when it has been built. In development Vite serves the app
# itself and proxies /api here, so this stays quiet.
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_web(full_path: str):
        """Anything that is not an API route is the single-page app."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        # Normalise first, then check the result is still inside dist, so a path like
        # "../../etc/passwd" cannot escape it.
        root = os.path.normpath(str(_frontend_dist))
        candidate = os.path.normpath(os.path.join(root, full_path))
        if candidate != root and not candidate.startswith(root + os.sep):
            raise HTTPException(status_code=404, detail="Not Found")
        if os.path.isfile(candidate):
            return FileResponse(candidate)
        # index.html names the hashed bundles, so a cached copy pins the browser to an
        # old build. The bundles are fingerprinted and may be cached.
        return FileResponse(
            str(_frontend_dist / "index.html"),
            headers={"Cache-Control": "no-store, must-revalidate"},
        )
