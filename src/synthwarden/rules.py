"""Rule engine for processing sensor events."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Set
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .database import async_session, Rule, SensorState, AlertLog, Channel
from .unifi import UniFiClient
from .notifiers import send_notification
from .openclaw import dispatch_to_openclaw

logger = logging.getLogger(__name__)


class RuleEngine:
    """Processes sensor events against configured rules."""
    
    def __init__(self, unifi: UniFiClient):
        self.unifi = unifi
        self._running = False
        self._shutdown_event = asyncio.Event()  # For graceful shutdown
        
        # Shared state - protected by lock
        self._sensor_states: dict[str, dict] = {}
        self._cooldowns: dict[str, datetime] = {}
        self._state_lock = asyncio.Lock()  # Protects _sensor_states and _cooldowns
        
        # Debounce: track recently processed events to avoid duplicates
        self._recent_events: dict[str, datetime] = {}
        self._debounce_seconds = 2.0  # Ignore duplicate events within this window
        
        # Track background tasks to avoid fire-and-forget
        self._pending_tasks: Set[asyncio.Task] = set()
        
        # Register for UniFi events
        self.unifi.on_event(self._handle_event)
    
    async def run(self):
        """Main rule engine loop."""
        self._running = True
        self._shutdown_event.clear()
        logger.info("Rule engine started")
        
        # Initialize state from current sensor values
        await self._init_sensor_states()
        
        while self._running:
            try:
                # Poll sensor states (workaround for WebSocket issues)
                await self._poll_sensor_states()
                # Check duration-based rules
                await self._check_duration_rules()
                # Check battery levels
                await self._check_battery_rules()
                # Check offline sensors
                await self._check_offline_rules()
                # Clean up completed tasks
                self._cleanup_tasks()
            except asyncio.CancelledError:
                logger.info("Rule engine cancelled")
                raise  # Re-raise to properly handle cancellation
            except Exception as e:
                logger.exception(f"Rule engine error: {e}")
            
            # Wait with graceful shutdown support
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=10.0
                )
                # If we get here, shutdown was requested
                break
            except asyncio.TimeoutError:
                # Normal timeout, continue loop
                pass
        
        logger.info("Rule engine stopped")
    
    def _cleanup_tasks(self):
        """Remove completed tasks from tracking set."""
        done = {t for t in self._pending_tasks if t.done()}
        for task in done:
            # Log any exceptions from fire-and-forget tasks
            if task.exception():
                logger.error(f"Background task failed: {task.exception()}")
        self._pending_tasks -= done
    
    async def _init_sensor_states(self):
        """Initialize state tracking from database, then sync with current values."""
        now = datetime.now(timezone.utc)
        
        # Load persisted state from database
        async with async_session() as session:
            result = await session.execute(select(SensorState))
            db_states = {s.sensor_id: s for s in result.scalars().all()}
        
        async with self._state_lock:
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
                        logger.debug(f"Restored {sensor.name}: {current_state} since {db_state.state_since}")
                    else:
                        # State changed or new sensor - use current time
                        self._sensor_states[sensor_id] = {
                            "state": current_state,
                            "since": now,
                            "name": sensor.name,
                        }
                        # Persist to DB
                        await self._persist_sensor_state(sensor_id, current_state, now)
                        logger.debug(f"Initialized {sensor.name}: {current_state} (new)")
    
    async def _persist_sensor_state(self, sensor_id: str, state: str, since: datetime):
        """Persist sensor state to database using atomic upsert."""
        async with async_session() as session:
            # Use SQLite's INSERT OR REPLACE for atomic upsert
            stmt = sqlite_insert(SensorState).values(
                sensor_id=sensor_id,
                current_state=state,
                state_since=since,
                alert_sent=False,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["sensor_id"],
                set_={
                    "current_state": state,
                    "state_since": since,
                    "alert_sent": False,
                },
            )
            await session.execute(stmt)
            await session.commit()
    
    async def _poll_sensor_states(self):
        """Poll current sensor states and detect changes."""
        now = datetime.now(timezone.utc)
        
        # Refresh data from UniFi (run in thread if blocking)
        try:
            await asyncio.wait_for(self.unifi._client.update(), timeout=30)
        except asyncio.TimeoutError:
            logger.warning("UniFi update timed out")
            return
        except Exception as e:
            logger.error(f"UniFi update failed: {e}")
            return
        
        for sensor_id, sensor in self.unifi.get_sensors().items():
            if hasattr(sensor, 'is_opened'):
                new_state = "open" if sensor.is_opened else "closed"
                
                async with self._state_lock:
                    current = self._sensor_states.get(sensor_id, {})
                    
                    if current.get("state") != new_state:
                        # Check debounce - skip if recently processed
                        if self._is_debounced(sensor_id):
                            continue
                        
                        # State changed
                        logger.debug(f"Sensor {sensor.name} changed: {current.get('state')} → {new_state}")
                        self._sensor_states[sensor_id] = {
                            "state": new_state,
                            "since": now,
                            "name": sensor.name,
                        }
                        self._recent_events[sensor_id] = now
                
                # Persist to database (outside lock to avoid holding it during I/O)
                if current.get("state") != new_state and not self._is_debounced(sensor_id):
                    await self._persist_sensor_state(sensor_id, new_state, now)
                    # Trigger state_change rules
                    await self._process_state_change(sensor_id, sensor.name, new_state)
    
    def _is_debounced(self, sensor_id: str) -> bool:
        """Check if sensor event should be debounced."""
        last_event = self._recent_events.get(sensor_id)
        if last_event:
            elapsed = (datetime.now(timezone.utc) - last_event).total_seconds()
            return elapsed < self._debounce_seconds
        return False
    
    def stop(self):
        """Stop the rule engine gracefully."""
        self._running = False
        self._shutdown_event.set()
        
        # Cancel any pending tasks
        for task in self._pending_tasks:
            task.cancel()
    
    def _handle_event(self, msg):
        """Handle real-time sensor events from WebSocket."""
        try:
            # Extract sensor data from event
            if hasattr(msg, 'new_obj') and msg.new_obj:
                obj = msg.new_obj
                if hasattr(obj, 'is_opened'):
                    # Create task and track it
                    task = asyncio.create_task(
                        self._handle_event_async(obj.id, obj.name, obj.is_opened)
                    )
                    self._pending_tasks.add(task)
                    task.add_done_callback(lambda t: self._pending_tasks.discard(t))
        except Exception as e:
            logger.exception(f"Event handling error: {e}")
    
    async def _handle_event_async(self, sensor_id: str, sensor_name: str, is_opened: bool):
        """Async handler for WebSocket events."""
        new_state = "open" if is_opened else "closed"
        now = datetime.now(timezone.utc)
        
        async with self._state_lock:
            # Check debounce
            if self._is_debounced(sensor_id):
                return
            
            current = self._sensor_states.get(sensor_id, {})
            if current.get("state") == new_state:
                return  # No actual change
            
            # Update state
            self._sensor_states[sensor_id] = {
                "state": new_state,
                "since": now,
                "name": sensor_name,
            }
            self._recent_events[sensor_id] = now
        
        # Process outside lock
        await self._persist_sensor_state(sensor_id, new_state, now)
        await self._process_state_change(sensor_id, sensor_name, new_state)
    
    async def _process_state_change(self, sensor_id: str, sensor_name: str, new_state: str):
        """Process a sensor state change."""
        logger.info(f"Sensor {sensor_name} changed to {new_state}")
        
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
                
                # "any" matches both open and closed
                if target_state == "any" or (target_state and new_state == target_state):
                    if self._check_conditions(rule) and await self._check_cooldown(rule):
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
                async with self._state_lock:
                    sensor_state = self._sensor_states.get(rule.sensor_id)
                    if not sensor_state:
                        continue
                    # Copy to avoid holding lock
                    sensor_state = sensor_state.copy()
                
                trigger_config = json.loads(rule.trigger_config) if rule.trigger_config else {}
                target_state = trigger_config.get("state", "open")
                duration_min = trigger_config.get("duration_min", 10)
                
                # Check if sensor is in target state
                if sensor_state["state"] != target_state:
                    continue
                
                # Check duration
                time_in_state = (now - sensor_state["since"]).total_seconds() / 60
                logger.debug(f"{sensor_state['name']} is {sensor_state['state']} for {time_in_state:.1f} min (threshold: {duration_min})")
                
                if time_in_state >= duration_min:
                    if self._check_conditions(rule) and await self._check_cooldown(rule):
                        logger.debug(f"TRIGGERING ALERT for {sensor_state['name']}")
                        await self._trigger_alert(
                            rule,
                            sensor_state["name"],
                            f"{target_state} for {int(time_in_state)} min",
                            session,
                        )
    
    async def _check_battery_rules(self):
        """Check battery_low rules."""
        async with async_session() as session:
            result = await session.execute(
                select(Rule).where(
                    Rule.trigger_type == "battery_low",
                    Rule.enabled == True,
                )
            )
            rules = result.scalars().all()
            
            for rule in rules:
                sensor = self.unifi.get_sensor(rule.sensor_id)
                if not sensor:
                    continue
                
                trigger_config = json.loads(rule.trigger_config) if rule.trigger_config else {}
                threshold = trigger_config.get("threshold", 20)
                
                battery = getattr(getattr(sensor, "battery_status", None), "percentage", None)
                if battery is None:
                    continue
                
                if battery < threshold:
                    if self._check_conditions(rule) and await self._check_cooldown(rule):
                        await self._trigger_alert(
                            rule,
                            sensor.name,
                            f"low battery ({battery}%)",
                            session,
                        )
    
    async def _check_offline_rules(self):
        """Check offline rules for disconnected sensors."""
        async with async_session() as session:
            result = await session.execute(
                select(Rule).where(
                    Rule.trigger_type == "offline",
                    Rule.enabled == True,
                )
            )
            rules = result.scalars().all()
            
            for rule in rules:
                sensor = self.unifi.get_sensor(rule.sensor_id)
                if not sensor:
                    continue
                
                is_connected = sensor.is_connected if hasattr(sensor, "is_connected") else True
                
                if not is_connected:
                    if self._check_conditions(rule) and await self._check_cooldown(rule):
                        await self._trigger_alert(
                            rule,
                            sensor.name,
                            "offline",
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
    
    async def _check_cooldown(self, rule: Rule) -> bool:
        """Check if rule is in cooldown period (async for lock safety)."""
        now = datetime.now(timezone.utc)
        
        async with self._state_lock:
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
        async with self._state_lock:
            self._cooldowns[rule.id] = now
        
        # Parse destinations
        destinations = json.loads(rule.destinations) if rule.destinations else []
        results = []
        
        # Send notifications
        for dest in destinations:
            try:
                # If destination has a channel_id, look up the channel config
                channel_config = dest.copy()
                if dest.get("channel_id"):
                    result = await session.execute(
                        select(Channel).where(Channel.id == dest["channel_id"])
                    )
                    channel = result.scalar_one_or_none()
                    if channel and channel.config:
                        # Merge channel config with destination
                        stored_config = json.loads(channel.config) if isinstance(channel.config, str) else channel.config
                        channel_config.update(stored_config)
                
                success = await send_notification(
                    channel_type=dest.get("type"),
                    channel_config=channel_config,
                    rule_name=rule.name,
                    sensor_name=sensor_name,
                    state=state_desc,
                )
                results.append({"channel": dest.get("type"), "success": success})
            except Exception as e:
                logger.exception(f"Notification failed: {e}")
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
        
        # Push to registered OpenClaw webhooks
        await dispatch_to_openclaw(
            event="alert",
            sensor_id=rule.sensor_id,
            sensor_name=sensor_name,
            state=state_desc,
            message=f"{sensor_name} is {state_desc}",
            rule_name=rule.name,
        )
