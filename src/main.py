"""
SNMP Agent Server - Main Entry Point.

Starts the SNMP agent server that aggregates hardware metrics
from all discovered machines on the network.
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from .core.config import Config, get_default_config_path
from .core.data_manager import DataManager
from .collectors.local_collector import LocalCollector
from .collectors.snmp_collector import SNMPCollector
from .collectors.ssh_collector import SSHCollector
from .discovery.network_scanner import NetworkScanner
from .agent.snmp_agent import SimpleSNMPAgent


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class SNMPAgentApplication:
    """
    Main application that coordinates all components.
    
    - Discovers machines on the network
    - Collects hardware metrics from all machines
    - Serves the aggregated data via SNMP
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.data_manager = DataManager(config)
        self.scanner = NetworkScanner(config.discovery)
        self.local_collector = LocalCollector()
        self.snmp_collector = SNMPCollector(
            community=config.collection.snmp_community,
            port=config.collection.snmp_port,
            timeout=config.collection.timeout_seconds,
        )
        self.ssh_collector = SSHCollector(
            username=config.collection.ssh_username,
            password=config.collection.ssh_password,
            key_path=config.collection.ssh_key_path,
        ) if config.collection.collect_remote_ssh else None
        
        self.agent = SimpleSNMPAgent(self.data_manager, config.snmp.port)
        
        self._running = False
        self._discovery_task = None
        self._collection_task = None
    
    async def start(self):
        """Start the application."""
        logger.info("Starting SNMP Agent Application...")
        self._running = True
        
        # Collect local metrics first
        if self.config.collection.collect_local:
            logger.info("Collecting local machine metrics...")
            local_snapshot = self.local_collector.collect_all()
            await self.data_manager.update_snapshot(local_snapshot)
            logger.info(f"Local machine: {local_snapshot.machine.hostname}")
        
        # Start the SNMP agent
        await self.agent.start()
        
        # Start background tasks
        self._discovery_task = asyncio.create_task(self._discovery_loop())
        self._collection_task = asyncio.create_task(self._collection_loop())
        
        logger.info("SNMP Agent Application started successfully")
        logger.info(f"Listening on port {self.config.snmp.port}")
        logger.info(f"Community string: {self.config.snmp.community_read}")
        logger.info(f"Enterprise OID: {self.config.snmp.enterprise_oid}")
    
    async def stop(self):
        """Stop the application."""
        logger.info("Stopping SNMP Agent Application...")
        self._running = False
        
        if self._discovery_task:
            self._discovery_task.cancel()
            try:
                await self._discovery_task
            except asyncio.CancelledError:
                pass
        
        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass
        
        await self.agent.stop()
        logger.info("SNMP Agent Application stopped")
    
    async def _discovery_loop(self):
        """Periodically discover machines on the network."""
        while self._running:
            try:
                if self.config.discovery.enabled:
                    logger.info("Running network discovery...")
                    machines = await self.scanner.discover_all()
                    
                    for machine in machines:
                        await self.data_manager.add_machine(machine)
                    
                    logger.info(f"Discovered {len(machines)} machines")
            except Exception as e:
                logger.error(f"Discovery error: {e}")
            
            await asyncio.sleep(self.config.discovery.scan_interval_seconds)
    
    async def _collection_loop(self):
        """Periodically collect metrics from all machines."""
        while self._running:
            try:
                await self._collect_all_metrics()
            except Exception as e:
                logger.error(f"Collection error: {e}")
            
            await asyncio.sleep(self.config.collection.interval_seconds)
    
    async def _collect_all_metrics(self):
        """Collect metrics from all known machines."""
        machines = self.data_manager.machines
        logger.debug(f"Collecting metrics from {len(machines)} machines")
        
        for machine in machines:
            try:
                snapshot = None
                
                # Try collection methods in order
                if machine.ip == self.local_collector._local_ip:
                    # Local machine
                    snapshot = self.local_collector.collect_all()
                elif self.config.collection.collect_remote_snmp:
                    # Try SNMP first
                    snapshot = await self.snmp_collector.collect_all(machine.ip)
                
                if not snapshot and self.ssh_collector and self.config.collection.collect_remote_ssh:
                    # Fall back to SSH
                    snapshot = self.ssh_collector.collect_all(machine.ip)
                
                if snapshot:
                    await self.data_manager.update_snapshot(snapshot)
                    logger.debug(f"Updated metrics for {machine.ip}")
                else:
                    logger.debug(f"Could not collect metrics from {machine.ip}")
                    
            except Exception as e:
                logger.error(f"Error collecting from {machine.ip}: {e}")
        
        # Log aggregated stats
        stats = self.data_manager.get_aggregated_stats()
        logger.info(
            f"Stats: {stats['machine_count']} machines, "
            f"Avg CPU: {stats['avg_cpu_percent']:.1f}%, "
            f"Memory: {stats['used_memory_gb']:.1f}/{stats['total_memory_gb']:.1f} GB"
        )
    
    def print_status(self):
        """Print current status."""
        stats = self.data_manager.get_aggregated_stats()
        print("\n" + "=" * 60)
        print("SNMP Agent Status")
        print("=" * 60)
        print(f"Machines monitored: {stats['machine_count']}")
        print(f"  Online: {stats['online_count']}")
        print(f"  Offline: {stats['offline_count']}")
        print(f"Average CPU Usage: {stats['avg_cpu_percent']:.1f}%")
        print(f"Total Memory: {stats['total_memory_gb']:.1f} GB")
        print(f"Used Memory: {stats['used_memory_gb']:.1f} GB ({stats['memory_usage_percent']:.1f}%)")
        print(f"Total Storage: {stats['total_storage_gb']:.1f} GB")
        print(f"Used Storage: {stats['used_storage_gb']:.1f} GB ({stats['storage_usage_percent']:.1f}%)")
        print("=" * 60)
        
        # Print per-machine details
        print("\nMachine Details:")
        print("-" * 60)
        for ip, snapshot in self.data_manager.snapshots.items():
            m = snapshot.machine
            c = snapshot.cpu
            mem = snapshot.memory
            print(f"\n{m.hostname} ({m.ip})")
            print(f"  OS: {m.os_type} | Uptime: {m.uptime_seconds // 3600}h")
            print(f"  CPU: {c.usage_percent:.1f}% ({c.core_count} cores @ {c.frequency_mhz:.0f} MHz)")
            if c.temperature_celsius:
                print(f"  CPU Temp: {c.temperature_celsius:.1f}°C")
            print(f"  RAM: {mem.used_gb:.1f}/{mem.total_gb:.1f} GB ({mem.usage_percent:.1f}%)")
            if snapshot.storage.devices:
                total_storage = snapshot.storage.total_bytes / (1024**3)
                used_storage = snapshot.storage.used_bytes / (1024**3)
                print(f"  Storage: {used_storage:.1f}/{total_storage:.1f} GB")


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
        default=None,
        help="SNMP port to listen on (default: 1161)"
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
        "--host",
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


async def main():
    """Main entry point."""
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
        print(f"Generated sample configuration: {config_path}")
        return
    
    # Load configuration
    config_path = args.config or get_default_config_path()
    logger.info(f"Loading configuration from {config_path}")
    config = Config.from_yaml(config_path)
    
    # Apply command line overrides
    if args.port:
        config.snmp.port = args.port
    if args.community:
        config.snmp.community_read = args.community
    if args.subnets:
        config.discovery.subnets = args.subnets
    if args.hosts:
        config.discovery.static_hosts = args.hosts
    if args.local_only:
        config.discovery.enabled = False
        config.collection.collect_remote_snmp = False
        config.collection.collect_remote_ssh = False
    
    # Create and start application
    app = SNMPAgentApplication(config)
    
    # Setup signal handlers
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(app.stop())
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        await app.start()
        
        # Keep running until stopped
        while app._running:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        await app.stop()


def run():
    """Entry point for the application."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete")


if __name__ == "__main__":
    run()
