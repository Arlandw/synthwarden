"""SynthWarden database models and initialization."""

from datetime import datetime
from typing import Optional
import json

from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import settings

Base = declarative_base()


class Sensor(Base):
    """Cached sensor data from UniFi."""
    __tablename__ = "sensors"
    
    id = Column(String, primary_key=True)
    name = Column(String)
    type = Column(String)  # door, motion, temperature, humidity
    last_state = Column(String)
    last_state_changed = Column(DateTime)
    battery_percent = Column(Integer)
    is_online = Column(Boolean, default=True)
    raw_data = Column(Text)  # JSON


class Rule(Base):
    """Notification rules."""
    __tablename__ = "rules"
    
    id = Column(String, primary_key=True)
    name = Column(String)
    sensor_id = Column(String)
    trigger_type = Column(String)  # state_change, duration, threshold
    trigger_config = Column(Text)  # JSON
    conditions = Column(Text)  # JSON
    destinations = Column(Text)  # JSON
    cooldown_minutes = Column(Integer, default=30)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Channel(Base):
    """Notification channels (Discord, Telegram, Email)."""
    __tablename__ = "channels"
    
    id = Column(String, primary_key=True)
    name = Column(String)
    type = Column(String)  # discord, telegram, email
    config = Column(Text)  # JSON (encrypted sensitive fields)
    created_at = Column(DateTime, default=datetime.utcnow)


class AlertLog(Base):
    """Alert history."""
    __tablename__ = "alert_log"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(String)
    sensor_id = Column(String)
    triggered_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    destinations_sent = Column(Text)  # JSON
    event_data = Column(Text)  # JSON


class SensorState(Base):
    """Sensor state tracking for duration alerts."""
    __tablename__ = "sensor_state"
    
    sensor_id = Column(String, primary_key=True)
    current_state = Column(String)
    state_since = Column(DateTime)
    alert_sent = Column(Boolean, default=False)


class Webhook(Base):
    """Registered Clawdbot webhooks (persisted)."""
    __tablename__ = "webhooks"
    
    id = Column(String, primary_key=True)
    url = Column(String, nullable=False)
    secret = Column(String, nullable=True)  # For HMAC signing
    events = Column(Text)  # JSON array: ["alert", "state_change", "connection_lost"]
    sensor_ids = Column(Text, nullable=True)  # JSON array or null for all
    created_at = Column(DateTime, default=datetime.utcnow)


# Async engine and session
engine = create_async_engine(settings.database_url, echo=settings.debug)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """Get database session."""
    async with async_session() as session:
        yield session
