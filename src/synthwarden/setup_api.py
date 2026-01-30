"""Setup API routes for first-time configuration."""

import asyncio
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pathlib import Path

from .user_config import get_config_manager, UniFiConfig, SensorConfig

router = APIRouter(prefix="/setup", tags=["setup"])

templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


class UniFiTestRequest(BaseModel):
    host: str
    port: int = 443
    username: str
    password: str
    verify_ssl: bool = False


class SensorConfigRequest(BaseModel):
    sensors: dict[str, dict]  # sensor_id -> {name, monitor}


# === UI Routes ===

@router.get("", response_class=HTMLResponse)
async def setup_page(request: Request):
    """Render the setup wizard page."""
    manager = get_config_manager()
    config = manager.load()
    
    return templates.TemplateResponse("setup.html", {
        "request": request,
        "config": config,
    })


# === API Routes ===

@router.post("/test-connection")
async def test_connection(data: UniFiTestRequest):
    """Test UniFi Protect connection and return sensor list."""
    from uiprotect import ProtectApiClient
    
    try:
        client = ProtectApiClient(
            host=data.host,
            port=data.port,
            username=data.username,
            password=data.password,
            verify_ssl=data.verify_ssl,
        )
        
        await asyncio.wait_for(client.update(), timeout=15)
        
        # Get sensors
        sensors = []
        for sensor_id, sensor in client.bootstrap.sensors.items():
            state = None
            if hasattr(sensor, "is_opened"):
                state = "open" if sensor.is_opened else "closed"
            
            battery = None
            if hasattr(sensor, "battery_status") and sensor.battery_status:
                battery = sensor.battery_status.percentage
            
            sensors.append({
                "id": sensor_id,
                "name": sensor.name,
                "type": "door" if hasattr(sensor, "is_opened") else "sensor",
                "state": state,
                "battery": battery,
            })
        
        return {
            "success": True,
            "sensor_count": len(sensors),
            "sensors": sensors,
        }
        
    except asyncio.TimeoutError:
        return {"success": False, "error": "Connection timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/save-unifi")
async def save_unifi_config(data: UniFiTestRequest):
    """Save UniFi connection settings."""
    manager = get_config_manager()
    config = manager.load()
    
    config.unifi = UniFiConfig(
        host=data.host,
        port=data.port,
        username=data.username,
        password=data.password,
        verify_ssl=data.verify_ssl,
    )
    
    manager.save()
    return {"status": "saved"}


@router.post("/save-sensors")
async def save_sensor_configs(data: SensorConfigRequest):
    """Save sensor nicknames and monitoring preferences."""
    manager = get_config_manager()
    config = manager.load()
    
    for sensor_id, sensor_data in data.sensors.items():
        config.sensors[sensor_id] = SensorConfig(
            name=sensor_data.get("name", sensor_id[:8]),
            monitor=sensor_data.get("monitor", True),
        )
    
    manager.save()
    return {"status": "saved"}


@router.post("/complete")
async def mark_setup_complete():
    """Mark setup as complete."""
    manager = get_config_manager()
    manager.mark_setup_complete()
    return {"status": "complete"}


@router.get("/status")
async def get_setup_status():
    """Check if setup is needed."""
    manager = get_config_manager()
    return {
        "needs_setup": manager.needs_setup(),
        "config_exists": manager.exists(),
    }
