"""OpenClaw Integration API.

Endpoints for OpenClaw instances to:
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

from .database import get_session, async_session, AlertLog, Sensor, Webhook
from .config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/openclaw", tags=["openclaw"])


# === Models ===

class SensorStatusResponse(BaseModel):
    """Sensor status for OpenClaw."""
    id: str
    name: str
    model: str  # UFP-SENSE, USL-Entry-US, USL-Environmental-US
    type: str  # Human-readable type
    capabilities: list[str]
    state: Optional[str]
    state_duration_minutes: Optional[int]
    battery_percent: Optional[int]
    is_online: bool
    last_updated: Optional[datetime]
    # Detailed values
    is_open: Optional[bool] = None
    temperature_c: Optional[float] = None
    temperature_f: Optional[float] = None
    humidity_pct: Optional[float] = None
    light_lux: Optional[float] = None


class SystemStatusResponse(BaseModel):
    """Overall system status."""
    connected: bool
    sensor_count: int
    sensors: list[SensorStatusResponse]
    active_alerts: int
    last_alert: Optional[datetime]
    version: str


class WebhookRegistration(BaseModel):
    """Register a webhook for OpenClaw notifications."""
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
    """Alert payload sent to OpenClaw webhooks."""
    event: str  # alert, state_change, connection_lost
    sensor_id: str
    sensor_name: str
    state: str
    message: str
    triggered_at: datetime
    rule_name: Optional[str]


# === Webhook storage (persisted to database) ===
# In-memory cache, synced with database
_webhooks_cache: dict[str, dict] = {}
_webhooks_loaded: bool = False


async def _load_webhooks():
    """Load webhooks from database into cache."""
    global _webhooks_cache, _webhooks_loaded
    if _webhooks_loaded:
        return
    
    async with async_session() as session:
        result = await session.execute(select(Webhook))
        webhooks = result.scalars().all()
        for w in webhooks:
            _webhooks_cache[w.id] = {
                "id": w.id,
                "url": w.url,
                "secret": w.secret,
                "events": json.loads(w.events) if w.events else ["alert"],
                "sensor_ids": json.loads(w.sensor_ids) if w.sensor_ids else None,
                "created_at": w.created_at,
            }
        _webhooks_loaded = True
        logger.info(f"Loaded {len(_webhooks_cache)} webhooks from database")


# === Optional API Key Auth ===

async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """Verify API key if configured."""
    if settings.openclaw_api_key:
        if not x_api_key or x_api_key != settings.openclaw_api_key:
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
    Get full system status for OpenClaw.
    
    Returns sensor states, connection status, and recent alert info.
    OpenClaw can poll this endpoint to show sensor status in its dashboard.
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
    from .sensor_types import parse_sensor, get_sensor_type_display, format_sensor_summary
    
    unifi = request.app.state.unifi
    rules_engine = request.app.state.rules
    now = datetime.now(timezone.utc)
    
    sensors = []
    for sensor_id, sensor in unifi.get_sensors().items():
        state_info = rules_engine._sensor_states.get(sensor_id, {})
        state_since = state_info.get("since")
        parsed = parse_sensor(sensor)
        
        duration_min = None
        if state_since:
            duration_min = int((now - state_since).total_seconds() / 60)
        
        temp_c = parsed.temperature.value if parsed.temperature else None
        temp_f = (temp_c * 9/5) + 32 if temp_c is not None else None
        
        sensors.append(SensorStatusResponse(
            id=sensor_id,
            name=sensor.name,
            model=parsed.model.value,
            type=get_sensor_type_display(parsed.model, parsed.mount_type),
            capabilities=[c.value for c in parsed.capabilities],
            state=format_sensor_summary(parsed),
            state_duration_minutes=duration_min,
            battery_percent=parsed.battery_percent,
            is_online=parsed.is_online,
            last_updated=state_since,
            is_open=parsed.is_open,
            temperature_c=temp_c,
            temperature_f=temp_f,
            humidity_pct=parsed.humidity.value if parsed.humidity else None,
            light_lux=parsed.light.value if parsed.light else None,
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
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_api_key),
):
    """
    Register a webhook for OpenClaw to receive alerts.
    
    SynthWarden will POST AlertPayload to this URL when events occur.
    """
    await _load_webhooks()
    
    webhook_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    # Save to database
    db_webhook = Webhook(
        id=webhook_id,
        url=webhook.url,
        secret=webhook.secret,
        events=json.dumps(webhook.events),
        sensor_ids=json.dumps(webhook.sensor_ids) if webhook.sensor_ids else None,
        created_at=now,
    )
    session.add(db_webhook)
    await session.commit()
    
    # Update cache
    _webhooks_cache[webhook_id] = {
        "id": webhook_id,
        "url": webhook.url,
        "secret": webhook.secret,
        "events": webhook.events,
        "sensor_ids": webhook.sensor_ids,
        "created_at": now,
    }
    
    logger.info(f"Registered webhook {webhook_id} for {webhook.url}")
    
    return WebhookResponse(
        id=webhook_id,
        url=webhook.url,
        events=webhook.events,
        created_at=now,
    )


@router.delete("/webhooks/{webhook_id}")
async def unregister_webhook(
    webhook_id: str,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_api_key),
):
    """Unregister a webhook."""
    await _load_webhooks()
    
    if webhook_id not in _webhooks_cache:
        raise HTTPException(status_code=404, detail="Webhook not found")
    
    # Delete from database
    result = await session.execute(select(Webhook).where(Webhook.id == webhook_id))
    db_webhook = result.scalar_one_or_none()
    if db_webhook:
        await session.delete(db_webhook)
        await session.commit()
    
    # Remove from cache
    del _webhooks_cache[webhook_id]
    return {"status": "deleted"}


@router.get("/webhooks", response_model=list[WebhookResponse])
async def list_webhooks(
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_api_key),
):
    """List all registered webhooks."""
    await _load_webhooks()
    
    return [
        WebhookResponse(
            id=w["id"],
            url=w["url"],
            events=w["events"],
            created_at=w["created_at"],
        )
        for w in _webhooks_cache.values()
    ]


# === Webhook Dispatch (called by rules engine) ===

async def dispatch_to_openclaw(
    event: str,
    sensor_id: str,
    sensor_name: str,
    state: str,
    message: str,
    rule_name: Optional[str] = None,
):
    """
    Send alert to all registered OpenClaw webhooks.
    
    Called by the rules engine when an alert triggers.
    """
    await _load_webhooks()
    
    payload = AlertPayload(
        event=event,
        sensor_id=sensor_id,
        sensor_name=sensor_name,
        state=state,
        message=message,
        triggered_at=datetime.now(timezone.utc),
        rule_name=rule_name,
    )
    
    for webhook_id, webhook in _webhooks_cache.items():
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


# === Summary endpoint for OpenClaw dashboard ===

@router.get("/summary")
async def get_summary(
    request: Request,
    _: bool = Depends(verify_api_key),
):
    """
    Get a quick summary string for OpenClaw dashboard.
    
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
