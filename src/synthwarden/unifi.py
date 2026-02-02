"""UniFi Protect client wrapper."""

import asyncio
import logging
from typing import Callable, Optional, Set
from datetime import datetime

from uiprotect import ProtectApiClient
from uiprotect.data import WSSubscriptionMessage

logger = logging.getLogger(__name__)


class UniFiClient:
    """Wrapper around uiprotect client with reconnection logic."""
    
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        verify_ssl: bool = False,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.verify_ssl = verify_ssl
        
        self._client: Optional[ProtectApiClient] = None
        self._connected = False
        self._event_callbacks: list[Callable] = []
        self._reconnect_task: Optional[asyncio.Task] = None
        self._should_reconnect = True  # Flag to control auto-reconnect
        
        # Retry settings
        self.max_retries = 5
        self.retry_delays = [5, 10, 30, 60, 120]
        
        # Track registered callbacks to avoid duplicates
        self._registered_callbacks: Set[int] = set()
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    @property
    def client(self) -> Optional[ProtectApiClient]:
        return self._client
    
    async def connect(self) -> bool:
        """Connect to UniFi Protect with retry logic."""
        self._should_reconnect = True
        
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Connecting to UniFi Protect at {self.host} (attempt {attempt + 1})")
                
                self._client = ProtectApiClient(
                    host=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    verify_ssl=self.verify_ssl,
                )
                
                await asyncio.wait_for(self._client.update(), timeout=30)
                self._connected = True
                
                # Subscribe to events
                self._client.subscribe_websocket(self._handle_event)
                
                # Start reconnection monitor
                if self._reconnect_task is None or self._reconnect_task.done():
                    self._reconnect_task = asyncio.create_task(self._reconnect_monitor())
                
                logger.info(f"Connected to UniFi Protect. Found {len(self._client.bootstrap.sensors)} sensors.")
                return True
                
            except asyncio.TimeoutError:
                logger.warning(f"Connection timeout (attempt {attempt + 1})")
            except Exception as e:
                logger.error(f"Connection failed: {e} (attempt {attempt + 1})")
            
            if attempt < self.max_retries - 1:
                delay = self.retry_delays[min(attempt, len(self.retry_delays) - 1)]
                logger.info(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
        
        logger.error(f"Failed to connect after {self.max_retries} attempts")
        return False
    
    async def _reconnect_monitor(self):
        """Monitor connection and auto-reconnect if dropped."""
        while self._should_reconnect:
            await asyncio.sleep(30)  # Check every 30 seconds
            
            if not self._should_reconnect:
                break
            
            # Check if WebSocket is still connected
            if self._client and not self._connected:
                logger.warning("Connection lost, attempting to reconnect...")
                try:
                    await self._client.async_disconnect_ws()
                except Exception:
                    pass
                
                self._client = None
                await self.connect()
    
    async def disconnect(self):
        """Disconnect from UniFi Protect."""
        self._should_reconnect = False  # Stop auto-reconnect
        
        # Cancel reconnect monitor
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        
        if self._client:
            try:
                await self._client.async_disconnect_ws()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            self._connected = False
            self._client = None
    
    def _handle_event(self, msg: WSSubscriptionMessage):
        """Handle incoming WebSocket events."""
        for callback in self._event_callbacks:
            try:
                callback(msg)
            except Exception as e:
                logger.error(f"Event callback error: {e}")
    
    def on_event(self, callback: Callable):
        """Register event callback (prevents duplicates)."""
        callback_id = id(callback)
        if callback_id not in self._registered_callbacks:
            self._event_callbacks.append(callback)
            self._registered_callbacks.add(callback_id)
    
    def get_sensors(self) -> dict:
        """Get all sensors."""
        if not self._client or not self._client.bootstrap:
            return {}
        return self._client.bootstrap.sensors
    
    def get_sensor(self, sensor_id: str):
        """Get specific sensor by ID."""
        sensors = self.get_sensors()
        return sensors.get(sensor_id)
    
    def get_cameras(self) -> dict:
        """Get all cameras (for doorbell)."""
        if not self._client or not self._client.bootstrap:
            return {}
        return self._client.bootstrap.cameras
