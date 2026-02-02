import logging
import asyncio
import json
from typing import Optional, Any
from amqtt.client import MQTTClient
from amqtt.mqtt.constants import QOS_0
from src.core.config import Config

logger = logging.getLogger(__name__)

class MQTTBrokerService:
    """Service to publish metrics to an external MQTT broker."""
    
    def __init__(self, config: Config):
        self.config = config
        self._client: Optional[MQTTClient] = None
        self._running = False
        self._client_connected = False

    async def start(self):
        """Start the MQTT client."""
        if not self.config.mqtt.enabled:
            logger.info("MQTT disabled in config")
            return

        try:
            logger.info(f"Connecting to MQTT Broker at {self.config.mqtt.host}:{self.config.mqtt.port}...")
            
            self._client = MQTTClient()
            # amqtt uses a URL format
            broker_url = f"mqtt://{self.config.mqtt.host}:{self.config.mqtt.port}/"
            
            await self._client.connect(broker_url)
            self._client_connected = True
            self._running = True
            logger.info("✅ Connected to MQTT Broker")
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to MQTT Broker: {e}")
            self._client_connected = False

    async def publish(self, topic: str, payload: Any):
        """Publish a message to an MQTT topic."""
        # Check if connected
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
            # Reconnect logic could go here, for now just log
            logger.error(f"Failed to publish to {topic}: {e}")
            self._client_connected = False 
            return False

    async def stop(self):
        """Stop the MQTT client."""
        if self._client and self._client_connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._running = False
        self._client_connected = False
        logger.info("MQTT Client stopped")
