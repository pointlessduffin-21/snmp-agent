import logging
import asyncio
import json
from typing import Optional, Any
from amqtt.client import MQTTClient
from amqtt.mqtt.constants import QOS_0
from ..core.config import Config

logger = logging.getLogger(__name__)

class MQTTBrokerService:
    """Service to publish metrics to an external MQTT broker."""

    def __init__(self, config: Config):
        self.config = config
        self._client: Optional[MQTTClient] = None
        self._running = False
        self._client_connected = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._reconnect_interval = 5  # seconds, initial
        self._max_reconnect_interval = 300  # seconds, cap

    @property
    def broker_url(self) -> str:
        return f"mqtt://{self.config.mqtt.host}:{self.config.mqtt.port}/"

    async def _connect(self) -> bool:
        """Attempt a single connection to the broker. Returns True on success."""
        try:
            self._client = MQTTClient()
            await self._client.connect(self.broker_url)
            self._client_connected = True
            self._reconnect_interval = 5  # reset backoff on success
            logger.info(f"Connected to MQTT Broker at {self.config.mqtt.host}:{self.config.mqtt.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MQTT Broker: {e}")
            self._client_connected = False
            return False

    async def start(self):
        """Start the MQTT client."""
        if not self.config.mqtt.enabled:
            logger.info("MQTT disabled in config")
            return

        self._running = True
        await self._connect()

        # Start background reconnect loop
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        """Background task that reconnects when the connection is lost."""
        while self._running:
            await asyncio.sleep(self._reconnect_interval)

            if self._running and not self._client_connected:
                logger.info(f"Attempting MQTT reconnect (interval: {self._reconnect_interval}s)")
                connected = await self._connect()
                if not connected:
                    # Exponential backoff capped at max
                    self._reconnect_interval = min(
                        self._reconnect_interval * 2,
                        self._max_reconnect_interval,
                    )

    async def publish(self, topic: str, payload: Any):
        """Publish a message to an MQTT topic."""
        if not self._running or not self._client or not self._client_connected:
            return False

        try:
            if isinstance(payload, dict):
                message = json.dumps(payload).encode('utf-8')
            else:
                message = str(payload).encode('utf-8')

            await self._client.publish(topic, message, qos=QOS_0)
            return True
        except Exception as e:
            logger.error(f"Failed to publish to {topic}: {e}")
            self._client_connected = False
            return False

    async def stop(self):
        """Stop the MQTT client."""
        self._running = False

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        if self._client and self._client_connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client_connected = False
        logger.info("MQTT Client stopped")
