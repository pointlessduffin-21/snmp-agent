#!/usr/bin/env python3
"""
Start the SNMP Agent Server with Web UI.

Usage:
    python start_web.py              # Start with web UI on port 8000
    python start_web.py --port 3000  # Custom port
"""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.core.config import Config, get_default_config_path
from src.web.api import start_web_server


def main():
    parser = argparse.ArgumentParser(
        description="SNMP Agent Server with Web UI"
    )
    
    parser.add_argument(
        "-c", "--config",
        default=None,
        help="Path to configuration file"
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
        "--subnet",
        action="append",
        dest="subnets",
        help="Subnet to scan (can be specified multiple times)"
    )
    
    parser.add_argument(
        "--community",
        default=None,
        help="SNMP community string (default: public)"
    )
    
    args = parser.parse_args()
    
    # Load config
    config_path = args.config or get_default_config_path()
    print(f"Loading configuration from: {config_path}")
    config = Config.from_yaml(config_path)
    
    # Apply command line overrides
    if args.subnets:
        config.discovery.subnets = args.subnets
    if args.community:
        config.collection.snmp_community = args.community
    
    print(f"\nStarting SNMP Agent Server with Web UI")
    print(f"=" * 60)
    print(f"Web Interface: http://{args.host}:{args.port}")
    print(f"API Documentation: http://{args.host}:{args.port}/docs")
    print(f"=" * 60)
    print(f"\nScanning subnets: {', '.join(config.discovery.subnets)}")
    print(f"Collection interval: {config.collection.interval_seconds}s")
    print(f"SNMP community: {config.collection.snmp_community}")
    print(f"\nPress Ctrl+C to stop\n")
    
    # Start web server
    start_web_server(
        host=args.host,
        port=args.port,
        app_config=config,
    )


if __name__ == "__main__":
    main()
