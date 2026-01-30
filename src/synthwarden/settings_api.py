"""Settings API routes for managing configuration."""

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pathlib import Path
import json
from sqlalchemy.ext.asyncio import AsyncSession

from .user_config import get_config_manager, UniFiConfig, SensorConfig
from .database import get_session

router = APIRouter(prefix="/settings", tags=["settings"])

templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


# === Models ===

class SensorNameUpdate(BaseModel):
    sensor_id: str
    name: str


class SensorMonitorUpdate(BaseModel):
    sensor_id: str
    monitor: bool


# === UI Route ===

@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request, session: AsyncSession = Depends(get_session)):
    """Render the settings page."""
    from .database import Channel
    from sqlalchemy import select
    
    manager = get_config_manager()
    config = manager.load()
    
    # Get sensors from UniFi
    unifi = request.app.state.unifi
    sensors = []
    
    for sensor_id, sensor in unifi.get_sensors().items():
        user_cfg = config.sensors.get(sensor_id)
        sensors.append({
            "id": sensor_id,
            "original_name": sensor.name,
            "display_name": user_cfg.name if user_cfg else sensor.name,
            "monitor": user_cfg.monitor if user_cfg else True,
            "is_online": sensor.is_connected if hasattr(sensor, "is_connected") else True,
        })
    
    # Get notification channels
    result = await session.execute(select(Channel))
    channels = [{"id": c.id, "name": c.name, "type": c.type} for c in result.scalars().all()]
    
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "active": "settings",
        "config": config,
        "sensors": sensors,
        "channels": channels,
        "connected": unifi.connected,
    })


# === API Routes ===

@router.post("/unifi")
async def save_unifi_settings(
    request: Request,
    host: str = Form(...),
    port: int = Form(443),
    username: str = Form(...),
    password: str = Form(""),
):
    """Save UniFi connection settings."""
    manager = get_config_manager()
    config = manager.load()
    
    # Keep existing password if not provided
    if not password and config.unifi.password:
        password = config.unifi.password
    
    config.unifi = UniFiConfig(
        host=host,
        port=port,
        username=username,
        password=password,
        verify_ssl=config.unifi.verify_ssl,
    )
    
    manager.save()
    
    # Reconnect UniFi client
    unifi = request.app.state.unifi
    await unifi.disconnect()
    unifi.host = host
    unifi.port = port
    unifi.username = username
    unifi.password = password
    await unifi.connect()
    
    return HTMLResponse('<span style="color: var(--success);">✓ Saved</span>')


@router.post("/preferences")
async def save_preferences(
    default_cooldown_minutes: int = Form(30),
    web_port: int = Form(8099),
):
    """Save preferences."""
    manager = get_config_manager()
    config = manager.load()
    
    config.preferences["default_cooldown_minutes"] = default_cooldown_minutes
    config.preferences["web_port"] = web_port
    
    manager.save()
    
    return HTMLResponse('<span style="color: var(--success);">✓ Saved</span>')


@router.post("/sensor-name")
async def save_sensor_name(data: SensorNameUpdate):
    """Update sensor display name."""
    manager = get_config_manager()
    manager.set_sensor_name(data.sensor_id, data.name)
    return {"status": "saved"}


@router.post("/sensor-monitor")
async def save_sensor_monitor(data: SensorMonitorUpdate):
    """Toggle sensor monitoring."""
    manager = get_config_manager()
    manager.set_sensor_monitoring(data.sensor_id, data.monitor)
    return {"status": "saved"}


@router.post("/reset")
async def reset_config():
    """Reset configuration to defaults."""
    manager = get_config_manager()
    if manager.path.exists():
        manager.path.unlink()
    manager._config = None
    return {"status": "reset"}


@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: str, session: AsyncSession = Depends(get_session)):
    """Delete a notification channel."""
    from .database import Channel
    from sqlalchemy import select
    
    result = await session.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    
    if channel:
        await session.delete(channel)
        await session.commit()
    
    return {"status": "deleted"}


@router.get("/export")
async def export_config():
    """Export configuration as JSON download."""
    manager = get_config_manager()
    config = manager.load()
    
    # Mask password for export
    export_data = config.model_dump()
    if export_data["unifi"]["password"]:
        export_data["unifi"]["password"] = "***REDACTED***"
    
    return Response(
        content=json.dumps(export_data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=synthwarden-config.json"},
    )
