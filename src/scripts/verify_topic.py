import asyncio
import os
from amqtt.client import MQTTClient
from amqtt.mqtt.constants import QOS_0

async def verify_device_topic():
    client = MQTTClient()
    
    host = os.getenv('MQTT_HOST', 'localhost')
    port = os.getenv('MQTT_PORT', '1883')
    broker_url = f'mqtt://{host}:{port}/'
    
    print(f"Connecting to broker at {broker_url}...")
    await client.connect(broker_url)
    
    topic = "#"
    print(f"Subscribing to {topic}...")
    
    await client.subscribe([
        (topic, QOS_0),
    ])
    
    print("Waiting for messages... (Press Ctrl+C to stop)")
    try:
        while True:
            message = await client.deliver_message()
            packet = message.publish_packet
            topic_name = packet.variable_header.topic_name
            data = packet.payload.data.decode()
            print(f"Received: {topic_name} => {data[:100]}...") # Truncate long JSON
    except KeyboardInterrupt:
        pass
    finally:
        await client.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(verify_device_topic())
    except KeyboardInterrupt:
        pass
