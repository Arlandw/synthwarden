"""User configuration management for SynthWarden.

Handles user-editable config (UniFi credentials, sensor nicknames, preferences)
separate from the environment-based system settings.
"""

import json
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


class UniFiConfig(BaseModel):
    """UniFi Protect connection settings."""
    host: str = ""
    port: int = 443
    username: str = ""
    password: str = ""
    verify_ssl: bool = False


class SensorConfig(BaseModel):
    """Per-sensor configuration."""
    name: str  # User-friendly nickname
    monitor: bool = True  # Whether to include in monitoring
    hidden: bool = False  # Hide from UI


class UserConfig(BaseModel):
    """User configuration for SynthWarden."""
    
    # UniFi Protect connection
    unifi: UniFiConfig = Field(default_factory=UniFiConfig)
    
    # Sensor configurations (keyed by sensor UUID)
    sensors: dict[str, SensorConfig] = Field(default_factory=dict)
    
    # General preferences
    preferences: dict = Field(default_factory=lambda: {
        "default_cooldown_minutes": 30,
        "web_port": 8099,
        "theme": "dark",
    })
    
    # Setup state
    setup_complete: bool = False


class UserConfigManager:
    """Manages user configuration file."""
    
    # Use /app/data in container (mounted volume) for persistence
    DEFAULT_PATH = Path("/app/data/config.json") if Path("/app/data").exists() else Path.home() / ".synthwarden" / "config.json"
    
    def __init__(self, path: Optional[Path] = None):
        self.path = path or self.DEFAULT_PATH
        self._config: Optional[UserConfig] = None
    
    def ensure_dir(self):
        """Ensure config directory exists."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
    
    def exists(self) -> bool:
        """Check if config file exists."""
        return self.path.exists()
    
    def load(self) -> UserConfig:
        """Load config from file, or return defaults."""
        if self._config:
            return self._config
        
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                self._config = UserConfig.model_validate(data)
            except Exception:
                self._config = UserConfig()
        else:
            self._config = UserConfig()
        
        return self._config
    
    def save(self, config: Optional[UserConfig] = None):
        """Save config to file."""
        if config:
            self._config = config
        
        if not self._config:
            return
        
        self.ensure_dir()
        self.path.write_text(
            json.dumps(self._config.model_dump(), indent=2)
        )
    
    def update_unifi(self, host: str, username: str, password: str, 
                     port: int = 443, verify_ssl: bool = False):
        """Update UniFi connection settings."""
        config = self.load()
        config.unifi = UniFiConfig(
            host=host,
            port=port,
            username=username,
            password=password,
            verify_ssl=verify_ssl,
        )
        self.save()
    
    def set_sensor_name(self, sensor_id: str, name: str):
        """Set a friendly name for a sensor."""
        config = self.load()
        if sensor_id in config.sensors:
            config.sensors[sensor_id].name = name
        else:
            config.sensors[sensor_id] = SensorConfig(name=name)
        self.save()
    
    def set_sensor_monitoring(self, sensor_id: str, enabled: bool):
        """Enable/disable monitoring for a sensor."""
        config = self.load()
        if sensor_id in config.sensors:
            config.sensors[sensor_id].monitor = enabled
        else:
            config.sensors[sensor_id] = SensorConfig(name=sensor_id[:8], monitor=enabled)
        self.save()
    
    def get_sensor_display_name(self, sensor_id: str, default_name: str) -> str:
        """Get display name for a sensor (user name or default)."""
        config = self.load()
        sensor_cfg = config.sensors.get(sensor_id)
        return sensor_cfg.name if sensor_cfg else default_name
    
    def is_sensor_monitored(self, sensor_id: str) -> bool:
        """Check if sensor should be monitored."""
        config = self.load()
        sensor_cfg = config.sensors.get(sensor_id)
        return sensor_cfg.monitor if sensor_cfg else True
    
    def mark_setup_complete(self):
        """Mark initial setup as complete."""
        config = self.load()
        config.setup_complete = True
        self.save()
    
    def needs_setup(self) -> bool:
        """Check if initial setup is needed."""
        config = self.load()
        return not config.setup_complete or not config.unifi.host


# Global instance
_manager: Optional[UserConfigManager] = None


def get_config_manager() -> UserConfigManager:
    """Get the global config manager instance."""
    global _manager
    if _manager is None:
        _manager = UserConfigManager()
    return _manager


def get_user_config() -> UserConfig:
    """Convenience function to get current user config."""
    return get_config_manager().load()
