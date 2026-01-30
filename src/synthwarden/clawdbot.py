"""Clawdbot Integration API.

Endpoints for Clawdbot instances to:
1. Query sensor status
2. Register for webhook notifications
3. Get alert history

Authentication via API key (optional, configurable).
"""

import logging
from datetime import datetime, timezone
from typing import Optional
import json
import uuid
import aiohttp

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session, AlertLog, Sensor
from .config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clawdbot", tags=["clawdbot"])


# === Models ===

class SensorStatusResponse(BaseModel):
    """Sensor status for Clawdbot."""
    id: str
    name: str
    type: str
    state: Optional[str]
    state_duration_minutes: Optional[int]
    battery_percent: Optional[int]
    is_online: bool
    last_updated: Optional[datetime]


class SystemStatusResponse(BaseModel):
    """Overall system status."""
    connected: bool
    sensor_count: int
    sensors: list[SensorStatusResponse]
    active_alerts: int
    last_alert: Optional[datetime]
    version: str


class WebhookRegistration(BaseModel):
    """Register a webhook for Clawdbot notifications."""
    url: str
    secret: Optional[str] = None  # For HMAC signing
    events: list[str] = ["alert"]  # alert, state_change, connection_lost
    sensor_ids: Optional[list[str]] = None  # Filter to specific sensors


class WebhookResponse(BaseModel):
    id: str
    url: str
    events: list[str]
    created_at: datetime


class AlertPayload(BaseModel):
    """Alert payload sent to Clawdbot webhooks."""
    event: str  # alert, state_change, connection_lost
    sensor_id: str
    sensor_name: str
    state: str
    message: str
    triggered_at: datetime
    rule_name: Optional[str]


# === In-memory webhook storage (would be DB in production) ===
_webhooks: dict[str, dict] = {}


# === Optional API Key Auth ===

async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """Verify API key if configured."""
    if settings.clawdbot_api_key:
        if not x_api_key or x_api_key != settings.clawdbot_api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")
    return True


# === Endpoints ===

@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_api_key),
):
    """
    Get full system status for Clawdbot.
    
    Returns sensor states, connection status, and recent alert info.
    Clawdbot can poll this endpoint to show sensor status in its dashboard.
    """
    unifi = request.app.state.unifi
    rules_engine = request.app.state.rules
    
    # Build sensor list
    sensors = []
    now = datetime.now(timezone.utc)
    
    for sensor_id, sensor in unifi.get_sensors().items():
        state_info = rules_engine._sensor_states.get(sensor_id, {})
        state_since = state_info.get("since")
        
        duration_min = None
        if state_since:
            duration_min = int((now - state_since).total_seconds() / 60)
        
        sensors.append(SensorStatusResponse(
            id=sensor_id,
            name=sensor.name,
            type="door" if hasattr(sensor, "is_opened") else "sensor",
            state=state_info.get("state"),
            state_duration_minutes=duration_min,
            battery_percent=getattr(getattr(sensor, "battery_status", None), "percentage", None),
            is_online=sensor.is_connected if hasattr(sensor, "is_connected") else True,
            last_updated=state_since,
        ))
    
    # Get last alert
    result = await session.execute(
        select(AlertLog).order_by(desc(AlertLog.triggered_at)).limit(1)
    )
    last_alert_record = result.scalar_one_or_none()
    
    # Count active alerts (unresolved in last hour)
    # For simplicity, just count alerts in last hour
    result = await session.execute(
        select(AlertLog).where(
            AlertLog.triggered_at > datetime.now(timezone.utc).replace(tzinfo=None) 
        ).limit(100)
    )
    recent_alerts = result.scalars().all()
    
    return SystemStatusResponse(
        connected=unifi.connected,
        sensor_count=len(sensors),
        sensors=sensors,
        active_alerts=len([a for a in recent_alerts if not a.resolved_at]),
        last_alert=last_alert_record.triggered_at if last_alert_record else None,
        version="0.1.0",
    )


@router.get("/sensors", response_model=list[SensorStatusResponse])
async def get_sensors(
    request: Request,
    _: bool = Depends(verify_api_key),
):
    """Get all sensor states."""
    unifi = request.app.state.unifi
    rules_engine = request.app.state.rules
    now = datetime.now(timezone.utc)
    
    sensors = []
    for sensor_id, sensor in unifi.get_sensors().items():
        state_info = rules_engine._sensor_states.get(sensor_id, {})
        state_since = state_info.get("since")
        
        duration_min = None
        if state_since:
            duration_min = int((now - state_since).total_seconds() / 60)
        
        sensors.append(SensorStatusResponse(
            id=sensor_id,
            name=sensor.name,
            type="door" if hasattr(sensor, "is_opened") else "sensor",
            state=state_info.get("state"),
            state_duration_minutes=duration_min,
            battery_percent=getattr(getattr(sensor, "battery_status", None), "percentage", None),
            is_online=sensor.is_connected if hasattr(sensor, "is_connected") else True,
            last_updated=state_since,
        ))
    
    return sensors


@router.get("/sensors/{sensor_id}", response_model=SensorStatusResponse)
async def get_sensor(
    sensor_id: str,
    request: Request,
    _: bool = Depends(verify_api_key),
):
    """Get a specific sensor's status."""
    unifi = request.app.state.unifi
    rules_engine = request.app.state.rules
    
    sensor = unifi.get_sensor(sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    
    state_info = rules_engine._sensor_states.get(sensor_id, {})
    state_since = state_info.get("since")
    now = datetime.now(timezone.utc)
    
    duration_min = None
    if state_since:
        duration_min = int((now - state_since).total_seconds() / 60)
    
    return SensorStatusResponse(
        id=sensor_id,
        name=sensor.name,
        type="door" if hasattr(sensor, "is_opened") else "sensor",
        state=state_info.get("state"),
        state_duration_minutes=duration_min,
        battery_percent=getattr(getattr(sensor, "battery_status", None), "percentage", None),
        is_online=sensor.is_connected if hasattr(sensor, "is_connected") else True,
        last_updated=state_since,
    )


@router.post("/webhooks", response_model=WebhookResponse)
async def register_webhook(
    webhook: WebhookRegistration,
    _: bool = Depends(verify_api_key),
):
    """
    Register a webhook for Clawdbot to receive alerts.
    
    SynthWarden will POST AlertPayload to this URL when events occur.
    """
    webhook_id = str(uuid.uuid4())
    
    _webhooks[webhook_id] = {
        "id": webhook_id,
        "url": webhook.url,
        "secret": webhook.secret,
        "events": webhook.events,
        "sensor_ids": webhook.sensor_ids,
        "created_at": datetime.now(timezone.utc),
    }
    
    logger.info(f"Registered webhook {webhook_id} for {webhook.url}")
    
    return WebhookResponse(
        id=webhook_id,
        url=webhook.url,
        events=webhook.events,
        created_at=_webhooks[webhook_id]["created_at"],
    )


@router.delete("/webhooks/{webhook_id}")
async def unregister_webhook(
    webhook_id: str,
    _: bool = Depends(verify_api_key),
):
    """Unregister a webhook."""
    if webhook_id not in _webhooks:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    del _webhooks[webhook_id]
    return {"status": "deleted"}


@router.get("/webhooks", response_model=list[WebhookResponse])
async def list_webhooks(_: bool = Depends(verify_api_key)):
    """List all registered webhooks."""
    return [
        WebhookResponse(
            id=w["id"],
            url=w["url"],
            events=w["events"],
            created_at=w["created_at"],
        )
        for w in _webhooks.values()
    ]


# === Webhook Dispatch (called by rules engine) ===

async def dispatch_to_clawdbot(
    event: str,
    sensor_id: str,
    sensor_name: str,
    state: str,
    message: str,
    rule_name: Optional[str] = None,
):
    """
    Send alert to all registered Clawdbot webhooks.
    
    Called by the rules engine when an alert triggers.
    """
    payload = AlertPayload(
        event=event,
        sensor_id=sensor_id,
        sensor_name=sensor_name,
        state=state,
        message=message,
        triggered_at=datetime.now(timezone.utc),
        rule_name=rule_name,
    )
    
    for webhook_id, webhook in _webhooks.items():
        # Filter by event type
        if event not in webhook["events"]:
            continue
        
        # Filter by sensor
        if webhook["sensor_ids"] and sensor_id not in webhook["sensor_ids"]:
            continue
        
        # Send webhook
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Content-Type": "application/json"}
                
                # Add HMAC signature if secret configured
                if webhook.get("secret"):
                    import hmac
                    import hashlib
                    body = payload.model_dump_json()
                    signature = hmac.new(
                        webhook["secret"].encode(),
                        body.encode(),
                        hashlib.sha256,
                    ).hexdigest()
                    headers["X-SynthWarden-Signature"] = signature
                
                async with session.post(
                    webhook["url"],
                    json=payload.model_dump(mode="json"),
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status < 300:
                        logger.info(f"Webhook {webhook_id} delivered to {webhook['url']}")
                    else:
                        logger.warning(f"Webhook {webhook_id} failed: {resp.status}")
        except Exception as e:
            logger.error(f"Webhook {webhook_id} error: {e}")


# === Summary endpoint for Clawdbot dashboard ===

@router.get("/summary")
async def get_summary(
    request: Request,
    _: bool = Depends(verify_api_key),
):
    """
    Get a quick summary string for Clawdbot dashboard.
    
    Returns a formatted status line like:
    "🏠 4 sensors OK | 🚪 All doors closed | 🔋 Batteries: 95%+"
    """
    unifi = request.app.state.unifi
    rules_engine = request.app.state.rules
    
    sensors = list(unifi.get_sensors().values())
    
    if not unifi.connected:
        return {"summary": "⚠️ UniFi Protect disconnected", "status": "error"}
    
    # Count states
    open_doors = []
    low_battery = []
    offline = []
    
    for sensor in sensors:
        state_info = rules_engine._sensor_states.get(sensor.id, {})
        
        if state_info.get("state") == "open":
            open_doors.append(sensor.name)
        
        battery = getattr(getattr(sensor, "battery_status", None), "percentage", None)
        if battery and battery < 20:
            low_battery.append(f"{sensor.name}: {battery}%")
        
        if hasattr(sensor, "is_connected") and not sensor.is_connected:
            offline.append(sensor.name)
    
    # Build summary
    parts = []
    parts.append(f"🏠 {len(sensors)} sensors")
    
    if open_doors:
        parts.append(f"🚪 Open: {', '.join(open_doors)}")
    else:
        parts.append("🚪 All closed")
    
    if low_battery:
        parts.append(f"🔋 Low: {', '.join(low_battery)}")
    
    if offline:
        parts.append(f"⚠️ Offline: {', '.join(offline)}")
    
    status = "warning" if (open_doors or low_battery or offline) else "ok"
    
    return {
        "summary": " | ".join(parts),
        "status": status,
        "open_doors": open_doors,
        "low_battery": low_battery,
        "offline": offline,
    }
