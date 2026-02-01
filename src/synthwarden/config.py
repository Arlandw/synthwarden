"""SynthWarden configuration."""

from typing import Optional
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    """Application settings from environment variables."""
    
    # UniFi Protect
    unifi_host: str = "192.168.1.1"
    unifi_user: str = "admin"
    unifi_pass: str = ""
    unifi_verify_ssl: bool = False
    
    # Database
    database_url: str = "sqlite+aiosqlite:///data/synthwarden.db"
    
    # Security
    secret_key: str = "change-me-in-production"
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    
    # OpenClaw Integration
    openclaw_api_key: Optional[str] = None  # Optional API key for OpenClaw endpoints
    
    # Paths
    data_dir: Path = Path("data")
    
    class Config:
        env_prefix = ""
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Ignore unknown env vars like TZ


settings = Settings()

# Ensure data directory exists
settings.data_dir.mkdir(parents=True, exist_ok=True)
