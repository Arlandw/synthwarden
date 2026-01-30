"""UniFi Protect Sensor Type Definitions and Utilities.

Supports all UniFi sensor models:
- UFP-SENSE (UP Sense) - All-in-one smart sensor
- USL-Entry-US - Entry/door sensor (standalone door/window)
- USL-Environmental-US - Environmental sensor (temp/humidity/light)
- Future models as they're released
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Any


class SensorModel(str, Enum):
    """Known UniFi sensor models."""
    UP_SENSE = "UFP-SENSE"
    ENTRY = "USL-Entry-US"
    ENVIRONMENTAL = "USL-Environmental-US"
    UNKNOWN = "unknown"
    
    @classmethod
    def from_string(cls, value: str) -> "SensorModel":
        """Parse sensor model from string."""
        for model in cls:
            if model.value == value:
                return model
        return cls.UNKNOWN


class MountType(str, Enum):
    """Sensor mount types."""
    DOOR = "door"
    WINDOW = "window"
    GARAGE = "garage"
    WALL = "wall"
    LEAK = "leak"
    NONE = "none"
    
    @classmethod
    def from_string(cls, value: str) -> "MountType":
        """Parse mount type from string."""
        if value is None:
            return cls.NONE
        # Handle MountType.DOOR format
        if "." in str(value):
            value = str(value).split(".")[-1]
        for mt in cls:
            if mt.value.lower() == str(value).lower():
                return mt
        return cls.NONE


class SensorCapability(str, Enum):
    """Individual sensor capabilities."""
    CONTACT = "contact"  # Door/window open/close
    MOTION = "motion"
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    LIGHT = "light"
    ALARM = "alarm"  # Smoke/CO alarm sound detection
    LEAK = "leak"  # Water leak detection
    TAMPER = "tamper"  # Tampering detection


@dataclass
class SensorReading:
    """A sensor reading with value, unit, and timestamp."""
    value: Any
    unit: str
    timestamp: Optional[datetime] = None


@dataclass 
class SensorState:
    """Complete state of a sensor at a point in time."""
    sensor_id: str
    name: str
    model: SensorModel
    mount_type: MountType
    capabilities: list[SensorCapability]
    is_online: bool
    battery_percent: Optional[int]
    
    # State values (None if capability not present)
    is_open: Optional[bool] = None  # Contact sensor
    is_motion: Optional[bool] = None  # Motion detected
    temperature: Optional[SensorReading] = None
    humidity: Optional[SensorReading] = None
    light: Optional[SensorReading] = None
    is_alarm: Optional[bool] = None
    is_leak: Optional[bool] = None
    is_tampered: Optional[bool] = None
    
    # Timestamps
    last_contact_change: Optional[datetime] = None
    last_motion: Optional[datetime] = None
    last_updated: Optional[datetime] = None


def parse_sensor(sensor: Any) -> SensorState:
    """Parse a uiprotect Sensor object into our SensorState."""
    sensor_id = sensor.id if hasattr(sensor, 'id') else str(sensor)
    
    # Determine model
    model_str = getattr(sensor, 'type', 'unknown')
    model = SensorModel.from_string(str(model_str))
    
    # Determine mount type
    mount_raw = getattr(sensor, 'mount_type', None)
    mount_type = MountType.from_string(str(mount_raw) if mount_raw else None)
    
    # Detect capabilities
    capabilities = []
    
    if getattr(sensor, 'is_contact_sensor_enabled', False):
        capabilities.append(SensorCapability.CONTACT)
    elif hasattr(sensor, 'is_opened'):
        # Fallback: if it has is_opened, it's a contact sensor
        capabilities.append(SensorCapability.CONTACT)
        
    if getattr(sensor, 'is_motion_sensor_enabled', False):
        capabilities.append(SensorCapability.MOTION)
        
    if getattr(sensor, 'is_temperature_sensor_enabled', False):
        capabilities.append(SensorCapability.TEMPERATURE)
        
    if getattr(sensor, 'is_humidity_sensor_enabled', False):
        capabilities.append(SensorCapability.HUMIDITY)
        
    if getattr(sensor, 'is_light_sensor_enabled', False):
        capabilities.append(SensorCapability.LIGHT)
        
    if getattr(sensor, 'is_alarm_sensor_enabled', False):
        capabilities.append(SensorCapability.ALARM)
        
    if getattr(sensor, 'is_leak_sensor_enabled', False):
        capabilities.append(SensorCapability.LEAK)
    
    # Battery
    battery = None
    if hasattr(sensor, 'battery_status') and sensor.battery_status:
        battery = getattr(sensor.battery_status, 'percentage', None)
    
    # Online status
    is_online = getattr(sensor, 'is_connected', True)
    
    # Build state
    state = SensorState(
        sensor_id=sensor_id,
        name=sensor.name,
        model=model,
        mount_type=mount_type,
        capabilities=capabilities,
        is_online=is_online,
        battery_percent=battery,
    )
    
    # Contact state
    if hasattr(sensor, 'is_opened'):
        state.is_open = sensor.is_opened
        
    # Motion state
    if hasattr(sensor, 'is_motion_detected'):
        state.is_motion = sensor.is_motion_detected
        
    # Environmental readings
    if hasattr(sensor, 'stats') and sensor.stats:
        stats = sensor.stats
        
        if hasattr(stats, 'temperature') and stats.temperature:
            temp_val = getattr(stats.temperature, 'value', None)
            if temp_val is not None:
                state.temperature = SensorReading(value=temp_val, unit="°C")
                
        if hasattr(stats, 'humidity') and stats.humidity:
            hum_val = getattr(stats.humidity, 'value', None)
            if hum_val is not None:
                state.humidity = SensorReading(value=hum_val, unit="%")
                
        if hasattr(stats, 'light') and stats.light:
            light_val = getattr(stats.light, 'value', None)
            if light_val is not None:
                state.light = SensorReading(value=light_val, unit="lux")
    
    # Alarm/Leak/Tamper
    state.is_alarm = getattr(sensor, 'is_alarm_detected', False)
    state.is_leak = getattr(sensor, 'is_leak_detected', False)
    state.is_tampered = getattr(sensor, 'is_tampering_detected', False)
    
    # Timestamps
    if hasattr(sensor, 'last_contact_event') and sensor.last_contact_event:
        state.last_contact_change = sensor.last_contact_event
    if hasattr(sensor, 'last_motion_event') and sensor.last_motion_event:
        state.last_motion = sensor.last_motion_event
    
    state.last_updated = datetime.now()
    
    return state


def get_sensor_type_display(model: SensorModel, mount_type: MountType) -> str:
    """Get a human-readable sensor type string."""
    if model == SensorModel.ENVIRONMENTAL:
        return "Environmental"
    elif model == SensorModel.ENTRY:
        return "Entry Sensor"
    elif model == SensorModel.UP_SENSE:
        if mount_type == MountType.GARAGE:
            return "Garage Sensor"
        elif mount_type == MountType.DOOR:
            return "Door Sensor"
        elif mount_type == MountType.WINDOW:
            return "Window Sensor"
        elif mount_type == MountType.LEAK:
            return "Leak Sensor"
        else:
            return "Smart Sensor"
    return "Sensor"


def get_sensor_icon(model: SensorModel, mount_type: MountType) -> str:
    """Get an emoji icon for the sensor type."""
    if model == SensorModel.ENVIRONMENTAL:
        return "🌡️"
    elif mount_type == MountType.GARAGE:
        return "🚗"
    elif mount_type == MountType.DOOR:
        return "🚪"
    elif mount_type == MountType.WINDOW:
        return "🪟"
    elif mount_type == MountType.LEAK:
        return "💧"
    return "📡"


def format_sensor_summary(state: SensorState) -> str:
    """Format a one-line summary of sensor state."""
    parts = []
    
    # Contact state (primary for door/window sensors)
    if SensorCapability.CONTACT in state.capabilities:
        status = "OPEN" if state.is_open else "closed"
        parts.append(status)
    
    # Motion
    if state.is_motion:
        parts.append("🏃 motion")
    
    # Environmental
    if state.temperature and state.temperature.value is not None:
        temp_f = (state.temperature.value * 9/5) + 32
        parts.append(f"{temp_f:.0f}°F")
        
    if state.humidity and state.humidity.value is not None:
        parts.append(f"{state.humidity.value:.0f}% RH")
        
    if state.light and state.light.value is not None:
        parts.append(f"{state.light.value:.0f} lux")
    
    # Alerts
    if state.is_alarm:
        parts.append("🚨 ALARM")
    if state.is_leak:
        parts.append("💧 LEAK")
    if state.is_tampered:
        parts.append("⚠️ TAMPER")
    
    return " | ".join(parts) if parts else "OK"
