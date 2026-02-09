"""
SNMP Agent Server - Main Entry Point.

Starts the SNMP agent server with web UI that aggregates hardware metrics
from all discovered machines on the network.
"""

import argparse
import logging
from pathlib import Path

from .core.config import Config, get_default_config_path
from .web.api import start_web_server


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="SNMP Agent Server for Hardware Metrics Aggregation"
    )

    parser.add_argument(
        "-c", "--config",
        default=None,
        help="Path to configuration file (YAML)"
    )

    parser.add_argument(
        "-p", "--port",
        type=int,
        default=8000,
        help="Web server port (default: 8000)"
    )

    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)"
    )

    parser.add_argument(
        "--community",
        default=None,
        help="SNMP community string (default: public)"
    )

    parser.add_argument(
        "--subnet",
        action="append",
        dest="subnets",
        help="Subnet to scan (can be specified multiple times)"
    )

    parser.add_argument(
        "--static-host",
        action="append",
        dest="hosts",
        help="Static host to monitor (can be specified multiple times)"
    )

    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Only monitor the local machine"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    parser.add_argument(
        "--generate-config",
        action="store_true",
        help="Generate a sample configuration file"
    )

    return parser.parse_args()


def run():
    """Entry point for the application."""
    args = parse_args()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Generate sample config if requested
    if args.generate_config:
        config = Config()
        config_path = "config/config.yaml"
        Path("config").mkdir(exist_ok=True)
        config.to_yaml(config_path)
        logger.info(f"Generated sample configuration: {config_path}")
        return

    # Load configuration
    config_path = args.config or get_default_config_path()
    logger.info(f"Loading configuration from {config_path}")
    config = Config.from_yaml(config_path)

    # Apply command line overrides
    if args.community:
        config.collection.snmp_community = args.community
    if args.subnets:
        config.discovery.subnets = args.subnets
    if args.hosts:
        config.discovery.static_hosts = args.hosts
    if args.local_only:
        config.discovery.enabled = False
        config.collection.collect_remote_snmp = False
        config.collection.collect_remote_ssh = False

    # Start the web server (handles SNMP agent, MQTT, discovery, and collection)
    start_web_server(
        host=args.host,
        port=args.port,
        app_config=config,
    )


if __name__ == "__main__":
    run()
