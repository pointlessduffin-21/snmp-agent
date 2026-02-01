import logging
import asyncio
from typing import Optional
from amqtt.broker import Broker
from src.core.config import Config

logger = logging.getLogger(__name__)

class MQTTBrokerService:
    """Service to host an embedded MQTT broker."""
    
    def __init__(self, config: Config):
        self.config = config
        self.broker: Optional[Broker] = None
        self._running = False

    async def start(self):
        """Start the MQTT broker."""
        if not self.config.mqtt.enabled:
            logger.info("MQTT Broker disabled in config")
            return

        mqtt_config = {
            'listeners': {
                'default': {
                    'type': 'tcp',
                    'bind': f'{self.config.mqtt.host}:{self.config.mqtt.port}',
                },
                'ws': {
                    'type': 'ws',
                    'bind': f'{self.config.mqtt.host}:{self.config.mqtt.websocket_port}',
                }
            },
            'sys_interval': 10,
            'auth': {
                'allow_anonymous': True,
                'password_file': '',
                'plugins': ['auth.anonymous'],
            },
            'topic-check': {
                'enabled': False,
            }
        }

        try:
            logger.info(f"Starting MQTT Broker on {self.config.mqtt.host}:{self.config.mqtt.port}...")
            self.broker = Broker(mqtt_config)
            await self.broker.start()
            self._running = True
            logger.info(f"✅ MQTT Broker started successfully")
        except Exception as e:
            logger.error(f"❌ Failed to start MQTT Broker: {e}")

    async def stop(self):
        """Stop the MQTT broker."""
        if self.broker and self._running:
            logger.info("Stopping MQTT Broker...")
            await self.broker.shutdown()
            self._running = False
            logger.info("MQTT Broker stopped")
