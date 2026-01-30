"""Web UI routes for SynthWarden."""

import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session, Rule, AlertLog

router = APIRouter(tags=["ui"])

# Setup templates
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Main dashboard page."""
    from .sensor_types import parse_sensor, format_sensor_summary
    
    unifi = request.app.state.unifi
    rules_engine = request.app.state.rules
    now = datetime.now(timezone.utc)
    
    # Get sensors
    sensors = []
    for sensor_id, sensor in unifi.get_sensors().items():
        state_info = rules_engine._sensor_states.get(sensor_id, {})
        state_since = state_info.get("since")
        duration_min = None
        if state_since:
            duration_min = int((now - state_since).total_seconds() / 60)
        
        parsed = parse_sensor(sensor)
        
        sensors.append({
            "id": sensor_id,
            "name": sensor.name,
            "state": format_sensor_summary(parsed),
            "state_duration_minutes": duration_min,
            "battery_percent": parsed.battery_percent,
            "is_online": parsed.is_online,
            "temperature_c": parsed.temperature.value if parsed.temperature else None,
            "humidity_pct": parsed.humidity.value if parsed.humidity else None,
            "light_lux": parsed.light.value if parsed.light else None,
        })
    
    # Get rules
    result = await session.execute(select(Rule).where(Rule.enabled == True))
    rules = result.scalars().all()
    
    # Get alerts today
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(AlertLog).where(AlertLog.triggered_at >= today_start.replace(tzinfo=None))
    )
    alerts_today = len(result.scalars().all())
    
    # Get recent alerts
    result = await session.execute(
        select(AlertLog).order_by(desc(AlertLog.triggered_at)).limit(5)
    )
    recent_alerts = []
    for alert in result.scalars().all():
        event_data = json.loads(alert.event_data) if alert.event_data else {}
        recent_alerts.append({
            "sensor_name": event_data.get("sensor_name", "Unknown"),
            "state": event_data.get("state", "Unknown"),
            "triggered_at": alert.triggered_at,
        })
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active": "dashboard",
        "sensors": sensors,
        "rules": rules,
        "alerts_today": alerts_today,
        "recent_alerts": recent_alerts,
    })


@router.get("/rules", response_class=HTMLResponse)
async def rules_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Rules management page."""
    unifi = request.app.state.unifi
    
    # Get all rules
    result = await session.execute(select(Rule).order_by(desc(Rule.created_at)))
    db_rules = result.scalars().all()
    
    # Get sensors for the form
    sensors = [
        {"id": s_id, "name": s.name}
        for s_id, s in unifi.get_sensors().items()
    ]
    
    # Parse rules
    rules = []
    sensor_map = {s["id"]: s["name"] for s in sensors}
    for r in db_rules:
        rules.append({
            "id": r.id,
            "name": r.name,
            "sensor_id": r.sensor_id,
            "sensor_name": sensor_map.get(r.sensor_id),
            "trigger_type": r.trigger_type,
            "trigger_config": json.loads(r.trigger_config) if r.trigger_config else {},
            "cooldown_minutes": r.cooldown_minutes,
            "enabled": r.enabled,
        })
    
    return templates.TemplateResponse("rules.html", {
        "request": request,
        "active": "rules",
        "rules": rules,
        "sensors": sensors,
    })


@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Alert history page."""
    result = await session.execute(
        select(AlertLog).order_by(desc(AlertLog.triggered_at)).limit(100)
    )
    
    alerts = []
    for alert in result.scalars().all():
        event_data = json.loads(alert.event_data) if alert.event_data else {}
        destinations = json.loads(alert.destinations_sent) if alert.destinations_sent else []
        success = any(d.get("success") for d in destinations) if destinations else False
        
        alerts.append({
            "triggered_at": alert.triggered_at,
            "sensor_name": event_data.get("sensor_name", "Unknown"),
            "state": event_data.get("state", "Unknown"),
            "rule_name": None,  # Would need to join with rules table
            "success": success,
        })
    
    return templates.TemplateResponse("alerts.html", {
        "request": request,
        "active": "alerts",
        "alerts": alerts,
    })


# === HTMX API endpoints ===

@router.get("/api/ui/sensors", response_class=HTMLResponse)
async def get_sensors_partial(request: Request):
    """Return sensors grid HTML for HTMX polling."""
    from .sensor_types import parse_sensor, format_sensor_summary
    
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
        
        parsed = parse_sensor(sensor)
        
        sensors.append({
            "id": sensor_id,
            "name": sensor.name,
            "state": format_sensor_summary(parsed),
            "state_duration_minutes": duration_min,
            "battery_percent": parsed.battery_percent,
            "is_online": parsed.is_online,
            "is_open": parsed.is_open,
            "temperature_c": parsed.temperature.value if parsed.temperature else None,
            "humidity_pct": parsed.humidity.value if parsed.humidity else None,
            "light_lux": parsed.light.value if parsed.light else None,
        })
    
    # Return just the sensor cards HTML
    html = ""
    for sensor in sensors:
        # Determine state class from is_open
        state_class = "state-open" if sensor.get("is_open") else "state-closed"
        state_display = sensor["state"].split("|")[0].strip() if sensor["state"] else "Unknown"
        online_class = "online" if sensor["is_online"] else "offline"
        battery_class = ""
        if sensor["battery_percent"]:
            if sensor["battery_percent"] < 20:
                battery_class = "critical"
            elif sensor["battery_percent"] < 40:
                battery_class = "low"
        
        # Environmental readings
        env_html = ""
        if sensor["temperature_c"] is not None or sensor["humidity_pct"] is not None:
            env_parts = []
            if sensor["temperature_c"] is not None:
                temp_f = int((sensor["temperature_c"] * 9/5) + 32)
                env_parts.append(f"<span>🌡️ {temp_f}°F</span>")
            if sensor["humidity_pct"] is not None:
                env_parts.append(f"<span>💧 {int(sensor['humidity_pct'])}%</span>")
            if sensor["light_lux"] is not None:
                env_parts.append(f"<span>☀️ {int(sensor['light_lux'])} lux</span>")
            if env_parts:
                env_html = f'''<div class="sensor-meta" style="margin-top: 0.5rem; border-top: 1px solid var(--border); padding-top: 0.5rem;">{''.join(env_parts)}</div>'''
        
        html += f'''
        <div class="sensor-card" onclick="openSensorModal('{sensor["id"]}')" style="cursor: pointer;">
            <div class="sensor-header">
                <span class="sensor-name">
                    <span class="status-dot {online_class}"></span>
                    {sensor["name"]}
                </span>
                <span class="sensor-state {state_class}">
                    {state_display}
                </span>
            </div>
            <div class="sensor-meta">
                {"<span class='battery " + battery_class + "'>🔋 " + str(sensor["battery_percent"]) + "%</span>" if sensor["battery_percent"] else ""}
                {"<span>⏱️ " + str(sensor["state_duration_minutes"]) + " min</span>" if sensor["state_duration_minutes"] is not None else ""}
            </div>
            {env_html}
        </div>
        '''
    
    return HTMLResponse(content=html)


@router.patch("/api/ui/rules/{rule_id}/toggle", response_class=HTMLResponse)
async def toggle_rule(
    rule_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Toggle rule enabled state."""
    result = await session.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if rule:
        rule.enabled = not rule.enabled
        await session.commit()
        active_class = "active" if rule.enabled else ""
        return HTMLResponse(
            content=f'<div class="toggle {active_class}" hx-patch="/api/ui/rules/{rule_id}/toggle" hx-swap="outerHTML"></div>'
        )
    return HTMLResponse(content="", status_code=404)


@router.delete("/api/ui/rules/{rule_id}", response_class=HTMLResponse)
async def delete_rule(
    rule_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a rule."""
    result = await session.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if rule:
        await session.delete(rule)
        await session.commit()
    
    return HTMLResponse(content="")  # Return empty to remove the row


@router.post("/api/ui/rules", response_class=HTMLResponse)
async def create_rule(
    request: Request,
    session: AsyncSession = Depends(get_session),
    name: str = Form(...),
    sensor_id: str = Form(...),
    trigger_type: str = Form(...),
    cooldown_minutes: int = Form(30),
    state: str = Form("open"),
    duration_min: int = Form(10),
    threshold: int = Form(20),
):
    """Create a new rule via form."""
    # Build trigger config
    if trigger_type == "duration":
        trigger_config = {"state": state, "duration_min": duration_min}
    elif trigger_type == "battery_low":
        trigger_config = {"threshold": threshold}
    elif trigger_type == "state_change":
        trigger_config = {"state": state}
    else:
        trigger_config = {}
    
    # Get webhook URL from existing rules or use placeholder
    result = await session.execute(select(Rule).limit(1))
    existing = result.scalar_one_or_none()
    destinations = json.loads(existing.destinations) if existing and existing.destinations else []
    
    rule_id = str(uuid.uuid4())
    rule = Rule(
        id=rule_id,
        name=name,
        sensor_id=sensor_id,
        trigger_type=trigger_type,
        trigger_config=json.dumps(trigger_config),
        destinations=json.dumps(destinations),
        cooldown_minutes=cooldown_minutes,
        enabled=True,
    )
    session.add(rule)
    await session.commit()
    
    # Get sensor name
    unifi = request.app.state.unifi
    sensor = unifi.get_sensor(sensor_id)
    sensor_name = sensor.name if sensor else sensor_id[:8]
    
    # Return new table row
    trigger_text = ""
    if trigger_type == "duration":
        trigger_text = f"{state} > {duration_min} min"
    elif trigger_type == "battery_low":
        trigger_text = f"Battery < {threshold}%"
    elif trigger_type == "offline":
        trigger_text = "Sensor offline"
    elif trigger_type == "state_change":
        trigger_text = "Any state change" if state == "any" else f"State → {state}"
    
    html = f'''
    <tr>
        <td>{name}</td>
        <td>{sensor_name}</td>
        <td>{trigger_text}</td>
        <td>{cooldown_minutes} min</td>
        <td>
            <div class="toggle active" hx-patch="/api/ui/rules/{rule_id}/toggle" hx-swap="outerHTML"></div>
        </td>
        <td>
            <button class="btn btn-danger btn-sm"
                    hx-delete="/api/ui/rules/{rule_id}"
                    hx-confirm="Delete this rule?"
                    hx-target="closest tr"
                    hx-swap="outerHTML">
                Delete
            </button>
        </td>
    </tr>
    '''
    return HTMLResponse(content=html)
