"""API routes for SynthWarden."""

from datetime import datetime
from typing import Optional
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session, Sensor, Rule, Channel, AlertLog

router = APIRouter()


# === Pydantic Models ===

class SensorResponse(BaseModel):
    id: str
    name: str
    model: str  # UFP-SENSE, USL-Entry-US, USL-Environmental-US
    type: str  # Human-readable: "Garage Sensor", "Environmental", etc.
    mount_type: str  # door, window, garage, wall, leak, none
    capabilities: list[str]  # contact, motion, temperature, humidity, light, alarm, leak
    state: Optional[str]  # Summary string
    state_since: Optional[datetime]
    battery_percent: Optional[int]
    is_online: bool
    # Detailed values
    is_open: Optional[bool] = None
    is_motion: Optional[bool] = None
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    light_lux: Optional[float] = None
    is_alarm: Optional[bool] = None
    is_leak: Optional[bool] = None


class RuleCreate(BaseModel):
    name: str
    sensor_id: str
    trigger_type: str  # state_change, duration, threshold
    trigger_config: dict
    conditions: Optional[dict] = None
    destinations: list[dict]
    cooldown_minutes: int = 30
    enabled: bool = True


class RuleResponse(BaseModel):
    id: str
    name: str
    sensor_id: str
    trigger_type: str
    trigger_config: dict
    conditions: Optional[dict]
    destinations: list[dict]
    cooldown_minutes: int
    enabled: bool
    created_at: datetime


class ChannelCreate(BaseModel):
    name: str
    type: str  # discord, telegram, email
    config: dict


class ChannelResponse(BaseModel):
    id: str
    name: str
    type: str
    created_at: datetime


class AlertResponse(BaseModel):
    id: int
    rule_id: str
    sensor_id: str
    triggered_at: datetime
    resolved_at: Optional[datetime]
    event_data: dict


# === Sensors ===

@router.get("/sensors", response_model=list[SensorResponse])
async def list_sensors(request: Request):
    """List all sensors from UniFi Protect."""
    from .sensor_types import parse_sensor, get_sensor_type_display, format_sensor_summary
    
    unifi = request.app.state.unifi
    rules_engine = request.app.state.rules
    
    sensors = []
    for sensor_id, sensor in unifi.get_sensors().items():
        state_info = rules_engine._sensor_states.get(sensor_id, {})
        parsed = parse_sensor(sensor)
        
        sensors.append(SensorResponse(
            id=sensor_id,
            name=sensor.name,
            model=parsed.model.value,
            type=get_sensor_type_display(parsed.model, parsed.mount_type),
            mount_type=parsed.mount_type.value,
            capabilities=[c.value for c in parsed.capabilities],
            state=format_sensor_summary(parsed),
            state_since=state_info.get("since"),
            battery_percent=parsed.battery_percent,
            is_online=parsed.is_online,
            is_open=parsed.is_open,
            is_motion=parsed.is_motion,
            temperature_c=parsed.temperature.value if parsed.temperature else None,
            humidity_pct=parsed.humidity.value if parsed.humidity else None,
            light_lux=parsed.light.value if parsed.light else None,
            is_alarm=parsed.is_alarm,
            is_leak=parsed.is_leak,
        ))
    
    return sensors


@router.get("/sensors/{sensor_id}", response_model=SensorResponse)
async def get_sensor(sensor_id: str, request: Request):
    """Get a specific sensor."""
    from .sensor_types import parse_sensor, get_sensor_type_display, format_sensor_summary
    
    unifi = request.app.state.unifi
    sensor = unifi.get_sensor(sensor_id)
    
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    
    state_info = request.app.state.rules._sensor_states.get(sensor_id, {})
    parsed = parse_sensor(sensor)
    
    return SensorResponse(
        id=sensor_id,
        name=sensor.name,
        model=parsed.model.value,
        type=get_sensor_type_display(parsed.model, parsed.mount_type),
        mount_type=parsed.mount_type.value,
        capabilities=[c.value for c in parsed.capabilities],
        state=format_sensor_summary(parsed),
        state_since=state_info.get("since"),
        battery_percent=parsed.battery_percent,
        is_online=parsed.is_online,
        is_open=parsed.is_open,
        is_motion=parsed.is_motion,
        temperature_c=parsed.temperature.value if parsed.temperature else None,
        humidity_pct=parsed.humidity.value if parsed.humidity else None,
        light_lux=parsed.light.value if parsed.light else None,
        is_alarm=parsed.is_alarm,
        is_leak=parsed.is_leak,
    )


# === Rules ===

@router.get("/rules", response_model=list[RuleResponse])
async def list_rules(session: AsyncSession = Depends(get_session)):
    """List all notification rules."""
    result = await session.execute(select(Rule).order_by(desc(Rule.created_at)))
    rules = result.scalars().all()
    
    return [
        RuleResponse(
            id=r.id,
            name=r.name,
            sensor_id=r.sensor_id,
            trigger_type=r.trigger_type,
            trigger_config=json.loads(r.trigger_config) if r.trigger_config else {},
            conditions=json.loads(r.conditions) if r.conditions else None,
            destinations=json.loads(r.destinations) if r.destinations else [],
            cooldown_minutes=r.cooldown_minutes,
            enabled=r.enabled,
            created_at=r.created_at,
        )
        for r in rules
    ]


@router.post("/rules", response_model=RuleResponse)
async def create_rule(rule: RuleCreate, session: AsyncSession = Depends(get_session)):
    """Create a new notification rule."""
    db_rule = Rule(
        id=str(uuid.uuid4()),
        name=rule.name,
        sensor_id=rule.sensor_id,
        trigger_type=rule.trigger_type,
        trigger_config=json.dumps(rule.trigger_config),
        conditions=json.dumps(rule.conditions) if rule.conditions else None,
        destinations=json.dumps(rule.destinations),
        cooldown_minutes=rule.cooldown_minutes,
        enabled=rule.enabled,
    )
    
    session.add(db_rule)
    await session.commit()
    await session.refresh(db_rule)
    
    return RuleResponse(
        id=db_rule.id,
        name=db_rule.name,
        sensor_id=db_rule.sensor_id,
        trigger_type=db_rule.trigger_type,
        trigger_config=json.loads(db_rule.trigger_config),
        conditions=json.loads(db_rule.conditions) if db_rule.conditions else None,
        destinations=json.loads(db_rule.destinations),
        cooldown_minutes=db_rule.cooldown_minutes,
        enabled=db_rule.enabled,
        created_at=db_rule.created_at,
    )


@router.patch("/rules/{rule_id}")
async def update_rule(rule_id: str, updates: dict, session: AsyncSession = Depends(get_session)):
    """Update a rule."""
    result = await session.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    for key, value in updates.items():
        if key in ["trigger_config", "conditions", "destinations"]:
            setattr(rule, key, json.dumps(value))
        elif hasattr(rule, key):
            setattr(rule, key, value)
    
    await session.commit()
    return {"status": "updated"}


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str, session: AsyncSession = Depends(get_session)):
    """Delete a rule."""
    result = await session.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    await session.delete(rule)
    await session.commit()
    return {"status": "deleted"}


# === Channels ===

@router.get("/channels", response_model=list[ChannelResponse])
async def list_channels(session: AsyncSession = Depends(get_session)):
    """List notification channels."""
    result = await session.execute(select(Channel))
    channels = result.scalars().all()
    
    return [
        ChannelResponse(
            id=c.id,
            name=c.name,
            type=c.type,
            created_at=c.created_at,
        )
        for c in channels
    ]


@router.post("/channels", response_model=ChannelResponse)
async def create_channel(channel: ChannelCreate, session: AsyncSession = Depends(get_session)):
    """Create a notification channel."""
    db_channel = Channel(
        id=str(uuid.uuid4()),
        name=channel.name,
        type=channel.type,
        config=json.dumps(channel.config),
    )
    
    session.add(db_channel)
    await session.commit()
    await session.refresh(db_channel)
    
    return ChannelResponse(
        id=db_channel.id,
        name=db_channel.name,
        type=db_channel.type,
        created_at=db_channel.created_at,
    )


@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: str, session: AsyncSession = Depends(get_session)):
    """Delete a notification channel."""
    result = await session.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    await session.delete(channel)
    await session.commit()
    
    return {"success": True}


@router.post("/channels/{channel_id}/test")
async def test_channel(channel_id: str, session: AsyncSession = Depends(get_session)):
    """Send a test notification to a channel."""
    from .notifiers import send_notification
    
    result = await session.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    config = json.loads(channel.config)
    config["type"] = channel.type
    
    success = await send_notification(
        channel_type=channel.type,
        channel_config=config,
        rule_name="Test Notification",
        sensor_name="Test Sensor",
        state="test",
    )
    
    return {"success": success}


# === Sensor History ===

class SensorHistoryEvent(BaseModel):
    event_type: str  # "state_change", "alert", "battery_low", etc.
    timestamp: datetime
    state: Optional[str] = None
    message: str
    rule_name: Optional[str] = None


@router.get("/sensors/{sensor_id}/history", response_model=list[SensorHistoryEvent])
async def get_sensor_history(
    sensor_id: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """Get activity history for a specific sensor."""
    # Get alerts for this sensor
    result = await session.execute(
        select(AlertLog)
        .where(AlertLog.sensor_id == sensor_id)
        .order_by(desc(AlertLog.triggered_at))
        .limit(limit)
    )
    alerts = result.scalars().all()
    
    events = []
    for alert in alerts:
        event_data = json.loads(alert.event_data) if alert.event_data else {}
        events.append(SensorHistoryEvent(
            event_type="alert",
            timestamp=alert.triggered_at,
            state=event_data.get("state"),
            message=f"{event_data.get('sensor_name', 'Sensor')} — {event_data.get('state', 'unknown')}",
            rule_name=None,  # Would need to join with rules table
        ))
    
    return events


# === Alert History ===

@router.get("/alerts", response_model=list[AlertResponse])
async def list_alerts(
    limit: int = 50,
    sensor_id: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """List alert history."""
    query = select(AlertLog).order_by(desc(AlertLog.triggered_at)).limit(limit)
    
    if sensor_id:
        query = query.where(AlertLog.sensor_id == sensor_id)
    
    result = await session.execute(query)
    alerts = result.scalars().all()
    
    return [
        AlertResponse(
            id=a.id,
            rule_id=a.rule_id,
            sensor_id=a.sensor_id,
            triggered_at=a.triggered_at,
            resolved_at=a.resolved_at,
            event_data=json.loads(a.event_data) if a.event_data else {},
        )
        for a in alerts
    ]


# === Status ===

@router.get("/status")
async def get_status(request: Request):
    """Get system status."""
    unifi = request.app.state.unifi
    
    return {
        "unifi_connected": unifi.connected,
        "sensor_count": len(unifi.get_sensors()),
        "version": "0.1.0",
    }
