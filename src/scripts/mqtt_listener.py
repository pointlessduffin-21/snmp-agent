import asyncio
import logging
import sys

# Try to import amqtt, handle if not installed
try:
    from amqtt.client import MQTTClient
    from amqtt.mqtt.constants import QOS_0
except ImportError:
    print("Error: 'amqtt' library not found.")
    print("Please install it using: pip install amqtt")
    print("Or run this script inside the Docker container.")
    sys.exit(1)

# Configure logging
logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def listen():
    client = MQTTClient()
    # Connect to localhost. 
    # If running inside container, this connects to the internal broker on localhost (if embedded) 
    # OR to the external mqtt service if configured.
    # However, for localhost testing from host, use localhost:1883
    
    # Check args
    url = "mqtt://localhost:1883/"
    if len(sys.argv) > 1:
        url = sys.argv[1]
    
    print(f"Connecting to {url}...")
    
    try:
        await client.connect(url)
        print(f"Connected!")
        
        # Subscribe to all topics
        await client.subscribe([('#', QOS_0)])
        print("Subscribed to all topics (#)")
        print("Waiting for messages... (Press Ctrl+C to stop)")
        print("-" * 50)
        
        while True:
            message = await client.deliver_message()
            packet = message.publish_packet
            topic = packet.variable_header.topic_name
            payload = packet.payload.data.decode('utf-8')
            print(f"[{topic}] {payload}")
            
    except Exception as e:
        print(f"Error: {e}")
        try:
            await client.disconnect()
        except:
            pass

if __name__ == '__main__':
    try:
        # Check for --help
        if len(sys.argv) > 1 and sys.argv[1] in ['-h', '--help']:
            print("Usage: python3 mqtt_listener.py [url]")
            print("Default: mqtt://localhost:1883/")
            sys.exit(0)
            
        asyncio.run(listen())
    except KeyboardInterrupt:
        print("\nStopping...")
