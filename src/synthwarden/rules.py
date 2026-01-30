"""Rule engine for processing sensor events."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import async_session, Rule, SensorState, AlertLog
from .unifi import UniFiClient
from .notifiers import send_notification
from .clawdbot import dispatch_to_clawdbot

logger = logging.getLogger(__name__)


class RuleEngine:
    """Processes sensor events against configured rules."""
    
    def __init__(self, unifi: UniFiClient):
        self.unifi = unifi
        self._running = False
        self._sensor_states: dict[str, dict] = {}
        self._cooldowns: dict[str, datetime] = {}
        
        # Register for UniFi events
        self.unifi.on_event(self._handle_event)
    
    async def run(self):
        """Main rule engine loop."""
        self._running = True
        logger.info("Rule engine started")
        
        # Initialize state from current sensor values
        await self._init_sensor_states()
        
        while self._running:
            try:
                # Poll sensor states (workaround for WebSocket issues)
                await self._poll_sensor_states()
                # Check duration-based rules
                await self._check_duration_rules()
            except Exception as e:
                logger.error(f"Rule engine error: {e}")
            
            await asyncio.sleep(10)  # Check every 10 seconds
    
    async def _init_sensor_states(self):
        """Initialize state tracking from database, then sync with current values."""
        now = datetime.now(timezone.utc)
        
        # Load persisted state from database
        async with async_session() as session:
            result = await session.execute(select(SensorState))
            db_states = {s.sensor_id: s for s in result.scalars().all()}
        
        for sensor_id, sensor in self.unifi.get_sensors().items():
            if hasattr(sensor, 'is_opened'):
                current_state = "open" if sensor.is_opened else "closed"
                db_state = db_states.get(sensor_id)
                
                if db_state and db_state.current_state == current_state:
                    # State matches DB - use persisted timestamp
                    self._sensor_states[sensor_id] = {
                        "state": current_state,
                        "since": db_state.state_since.replace(tzinfo=timezone.utc) if db_state.state_since else now,
                        "name": sensor.name,
                    }
                    print(f"DEBUG: Restored {sensor.name}: {current_state} since {db_state.state_since}")
                else:
                    # State changed or new sensor - use current time
                    self._sensor_states[sensor_id] = {
                        "state": current_state,
                        "since": now,
                        "name": sensor.name,
                    }
                    # Persist to DB
                    await self._persist_sensor_state(sensor_id, current_state, now)
                    print(f"DEBUG: Initialized {sensor.name}: {current_state} (new)")
    
    async def _persist_sensor_state(self, sensor_id: str, state: str, since: datetime):
        """Persist sensor state to database."""
        async with async_session() as session:
            # Upsert pattern
            result = await session.execute(
                select(SensorState).where(SensorState.sensor_id == sensor_id)
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                existing.current_state = state
                existing.state_since = since
                existing.alert_sent = False
            else:
                session.add(SensorState(
                    sensor_id=sensor_id,
                    current_state=state,
                    state_since=since,
                    alert_sent=False,
                ))
            await session.commit()
    
    async def _poll_sensor_states(self):
        """Poll current sensor states and detect changes."""
        now = datetime.now(timezone.utc)
        # Refresh data from UniFi
        await self.unifi._client.update()
        
        for sensor_id, sensor in self.unifi.get_sensors().items():
            if hasattr(sensor, 'is_opened'):
                new_state = "open" if sensor.is_opened else "closed"
                current = self._sensor_states.get(sensor_id, {})
                
                if current.get("state") != new_state:
                    # State changed
                    print(f"DEBUG: Sensor {sensor.name} changed: {current.get('state')} → {new_state}")
                    self._sensor_states[sensor_id] = {
                        "state": new_state,
                        "since": now,
                        "name": sensor.name,
                    }
                    # Persist to database
                    await self._persist_sensor_state(sensor_id, new_state, now)
                    
                    # Trigger state_change rules
                    await self._process_state_change(sensor_id, sensor.name, new_state)
    
    def stop(self):
        """Stop the rule engine."""
        self._running = False
    
    def _handle_event(self, msg):
        """Handle real-time sensor events from WebSocket."""
        try:
            # Extract sensor data from event
            if hasattr(msg, 'new_obj') and msg.new_obj:
                obj = msg.new_obj
                if hasattr(obj, 'is_opened'):
                    # Door sensor state change
                    asyncio.create_task(self._process_state_change(
                        sensor_id=obj.id,
                        sensor_name=obj.name,
                        new_state="open" if obj.is_opened else "closed",
                    ))
        except Exception as e:
            logger.error(f"Event handling error: {e}")
    
    async def _process_state_change(self, sensor_id: str, sensor_name: str, new_state: str):
        """Process a sensor state change."""
        now = datetime.now(timezone.utc)
        
        # Update state tracking
        prev_state = self._sensor_states.get(sensor_id, {}).get("state")
        self._sensor_states[sensor_id] = {
            "state": new_state,
            "since": now,
            "name": sensor_name,
        }
        
        if prev_state == new_state:
            return  # No actual change
        
        logger.info(f"Sensor {sensor_name} changed: {prev_state} → {new_state}")
        
        # Check immediate rules (state_change triggers)
        async with async_session() as session:
            result = await session.execute(
                select(Rule).where(
                    Rule.sensor_id == sensor_id,
                    Rule.trigger_type == "state_change",
                    Rule.enabled == True,
                )
            )
            rules = result.scalars().all()
            
            for rule in rules:
                trigger_config = json.loads(rule.trigger_config) if rule.trigger_config else {}
                target_state = trigger_config.get("state")
                
                if target_state and new_state == target_state:
                    if self._check_conditions(rule) and self._check_cooldown(rule):
                        await self._trigger_alert(rule, sensor_name, new_state, session)
    
    async def _check_duration_rules(self):
        """Check duration-based rules (e.g., open > 10 min)."""
        now = datetime.now(timezone.utc)
        
        async with async_session() as session:
            result = await session.execute(
                select(Rule).where(
                    Rule.trigger_type == "duration",
                    Rule.enabled == True,
                )
            )
            rules = result.scalars().all()
            
            for rule in rules:
                sensor_state = self._sensor_states.get(rule.sensor_id)
                if not sensor_state:
                    print(f"DEBUG: No state for sensor {rule.sensor_id}")
                    continue
                
                trigger_config = json.loads(rule.trigger_config) if rule.trigger_config else {}
                target_state = trigger_config.get("state", "open")
                duration_min = trigger_config.get("duration_min", 10)
                
                # Check if sensor is in target state
                if sensor_state["state"] != target_state:
                    continue
                
                # Check duration
                time_in_state = (now - sensor_state["since"]).total_seconds() / 60
                print(f"DEBUG: {sensor_state['name']} is {sensor_state['state']} for {time_in_state:.1f} min (threshold: {duration_min})")
                
                if time_in_state >= duration_min:
                    if self._check_conditions(rule) and self._check_cooldown(rule):
                        print(f"DEBUG: TRIGGERING ALERT for {sensor_state['name']}")
                        await self._trigger_alert(
                            rule,
                            sensor_state["name"],
                            f"{target_state} for {int(time_in_state)} min",
                            session,
                        )
    
    def _check_conditions(self, rule: Rule) -> bool:
        """Check if rule conditions are met (time windows, etc.)."""
        if not rule.conditions:
            return True
        
        conditions = json.loads(rule.conditions)
        now = datetime.now()
        
        # Time window check
        time_start = conditions.get("time_start")
        time_end = conditions.get("time_end")
        
        if time_start and time_end:
            current_time = now.strftime("%H:%M")
            
            if time_start <= time_end:
                # Normal range (e.g., 09:00 to 17:00)
                if not (time_start <= current_time <= time_end):
                    return False
            else:
                # Overnight range (e.g., 22:00 to 06:00)
                if not (current_time >= time_start or current_time <= time_end):
                    return False
        
        # Day of week check
        days = conditions.get("days")
        if days:
            current_day = now.strftime("%A").lower()
            if current_day not in [d.lower() for d in days]:
                return False
        
        return True
    
    def _check_cooldown(self, rule: Rule) -> bool:
        """Check if rule is in cooldown period."""
        now = datetime.now(timezone.utc)
        last_triggered = self._cooldowns.get(rule.id)
        
        if last_triggered:
            cooldown = timedelta(minutes=rule.cooldown_minutes or 30)
            if now - last_triggered < cooldown:
                return False
        
        return True
    
    async def _trigger_alert(
        self,
        rule: Rule,
        sensor_name: str,
        state_desc: str,
        session: AsyncSession,
    ):
        """Trigger an alert for a rule."""
        now = datetime.now(timezone.utc)
        
        logger.info(f"Triggering alert: {rule.name} - {sensor_name} {state_desc}")
        
        # Update cooldown
        self._cooldowns[rule.id] = now
        
        # Parse destinations
        destinations = json.loads(rule.destinations) if rule.destinations else []
        results = []
        
        # Send notifications
        for dest in destinations:
            try:
                success = await send_notification(
                    channel_type=dest.get("type"),
                    channel_config=dest,
                    rule_name=rule.name,
                    sensor_name=sensor_name,
                    state=state_desc,
                )
                results.append({"channel": dest.get("type"), "success": success})
            except Exception as e:
                logger.error(f"Notification failed: {e}")
                results.append({"channel": dest.get("type"), "success": False, "error": str(e)})
        
        # Log alert
        alert = AlertLog(
            rule_id=rule.id,
            sensor_id=rule.sensor_id,
            triggered_at=now,
            destinations_sent=json.dumps(results),
            event_data=json.dumps({"sensor_name": sensor_name, "state": state_desc}),
        )
        session.add(alert)
        await session.commit()
        
        # Push to registered Clawdbot webhooks
        await dispatch_to_clawdbot(
            event="alert",
            sensor_id=rule.sensor_id,
            sensor_name=sensor_name,
            state=state_desc,
            message=f"{sensor_name} is {state_desc}",
            rule_name=rule.name,
        )
