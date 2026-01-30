"""SynthWarden - Main FastAPI application."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .clawdbot import router as clawdbot_router
from .config import settings
from .database import init_db
from .unifi import UniFiClient
from .rules import RuleEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    # Startup
    await init_db()
    
    # Initialize UniFi client
    app.state.unifi = UniFiClient(
        host=settings.unifi_host,
        username=settings.unifi_user,
        password=settings.unifi_pass,
    )
    
    # Initialize rule engine
    app.state.rules = RuleEngine(app.state.unifi)
    
    # Connect to UniFi and start event loop
    await app.state.unifi.connect()
    asyncio.create_task(app.state.rules.run())
    
    yield
    
    # Shutdown
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

# API routes
app.include_router(api_router, prefix="/api")
app.include_router(clawdbot_router, prefix="/api")

# Health check
@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# Serve static frontend (Vue SPA)
# app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
