"""SynthWarden - Main FastAPI application."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .openclaw import router as openclaw_router
from .ui import router as ui_router
from .setup_api import router as setup_router
from .settings_api import router as settings_router
from .config import settings
from .database import init_db
from .unifi import UniFiClient
from .rules import RuleEngine
from .user_config import get_config_manager, get_user_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    # Startup
    await init_db()
    
    # Load user config
    manager = get_config_manager()
    user_cfg = manager.load()
    
    # Use user config if available, fall back to env vars
    unifi_host = user_cfg.unifi.host or settings.unifi_host
    unifi_user = user_cfg.unifi.username or settings.unifi_user
    unifi_pass = user_cfg.unifi.password or settings.unifi_pass
    
    # Initialize UniFi client
    app.state.unifi = UniFiClient(
        host=unifi_host,
        username=unifi_user,
        password=unifi_pass,
    )
    
    # Store config manager in app state
    app.state.config_manager = manager
    
    # Initialize rule engine
    app.state.rules = RuleEngine(app.state.unifi)
    
    # Only connect if credentials are configured
    if unifi_host and unifi_pass:
        await app.state.unifi.connect()
        asyncio.create_task(app.state.rules.run())
    
    yield
    
    # Shutdown
    if app.state.unifi.connected:
        await app.state.unifi.disconnect()


app = FastAPI(
    title="SynthWarden",
    description="Smart notifications for UniFi Protect sensors",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# API routes
app.include_router(api_router, prefix="/api")
app.include_router(openclaw_router, prefix="/api")
app.include_router(setup_router, prefix="/api")

# UI routes (no prefix - serves at /, /rules, /alerts, /settings)
app.include_router(ui_router)
app.include_router(settings_router)  # /settings page


# Setup redirect middleware
@app.middleware("http")
async def check_setup_required(request: Request, call_next):
    """Redirect to setup page if not configured."""
    path = request.url.path
    
    # Allow setup routes, static files, and API calls
    if (path.startswith("/api/setup") or 
        path.startswith("/static") or 
        path == "/health" or
        path.startswith("/api/openclaw")):  # Allow OpenClaw API even during setup
        return await call_next(request)
    
    # Check if setup is needed
    manager = get_config_manager()
    if manager.needs_setup() and path != "/api/setup":
        # For UI routes, redirect to setup
        if not path.startswith("/api"):
            return RedirectResponse(url="/api/setup", status_code=302)
    
    return await call_next(request)


# Health check
@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
