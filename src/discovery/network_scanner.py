"""
Network Scanner for Machine Discovery.

Discovers machines on the network using various methods:
ping sweep, ARP scanning, and static configuration.
"""

import asyncio
import ipaddress
import logging
import platform
import re
import socket
import subprocess
from typing import List, Set, Optional, Dict
from datetime import datetime

from ..core.models import MachineInfo
from ..core.config import DiscoveryConfig
from ..core.hostname_resolver import resolve_hostname, resolve_all_names, get_mac_address, get_vendor_from_mac


logger = logging.getLogger(__name__)


class NetworkScanner:
    """
    Discovers machines on the network.

    Supports multiple discovery methods:
    - Ping sweep (ICMP)
    - ARP table reading
    - Static host configuration
    """

    def __init__(self, config: Optional[DiscoveryConfig] = None):
        self.config = config or DiscoveryConfig()
        self._is_windows = platform.system() == "Windows"

    async def discover_all(self) -> List[MachineInfo]:
        """
        Run all configured discovery methods and return unique machines.
        """
        discovered: Set[str] = set()
        machines: List[MachineInfo] = []
        machines_by_ip: Dict[str, MachineInfo] = {}

        # Get ARP data FIRST so we have MAC addresses available
        arp_data: Dict[str, str] = {}
        if self.config.use_arp_scan:
            try:
                arp_data = await self.arp_scan()
                logger.info(f"ARP scan found {len(arp_data)} MAC addresses")
            except Exception as e:
                logger.error(f"Error reading ARP table: {e}")

        # Add static hosts first
        for host in self.config.static_hosts:
            if host and host not in self.config.exclude_ips:
                discovered.add(host)
                mac = arp_data.get(host, "")
                machine = await self._enrich_machine_info(host, "static", mac=mac)
                machines.append(machine)
                machines_by_ip[host] = machine

        # Scan subnets
        for subnet in self.config.subnets:
            try:
                hosts = await self.ping_sweep(subnet)
                for ip in hosts:
                    if ip not in discovered and ip not in self.config.exclude_ips:
                        discovered.add(ip)
                        mac = arp_data.get(ip, "")
                        machine = await self._enrich_machine_info(ip, "ping", mac=mac)
                        machines.append(machine)
                        machines_by_ip[ip] = machine
            except Exception as e:
                logger.error(f"Error scanning subnet {subnet}: {e}")

        # Add ARP-only entries (hosts not found by ping but in ARP table)
        for ip, mac in arp_data.items():
            if ip not in discovered and ip not in self.config.exclude_ips:
                discovered.add(ip)
                machine = await self._enrich_machine_info(ip, "arp", mac=mac)
                machines.append(machine)
                machines_by_ip[ip] = machine

        logger.info(f"Discovered {len(machines)} machines")
        return machines

    async def _enrich_machine_info(self, ip: str, method: str, mac: str = "") -> MachineInfo:
        """Enrich machine info with hostname, MAC address, and vendor.

        Uses FAST resolution (DNS only, short timeout) to avoid slow scans.
        SNMP collection will get proper hostnames for SNMP-enabled devices.
        """
        loop = asyncio.get_event_loop()

        # Fast DNS lookup only
        hostname = "unknown"
        try:
            hostname = await loop.run_in_executor(None, self._quick_dns, ip)
        except Exception:
            pass

        # Look up MAC if not already known
        if not mac:
            mac = await loop.run_in_executor(None, get_mac_address, ip) or ""

        vendor = get_vendor_from_mac(mac) if mac else "Unknown"

        return MachineInfo(
            ip=ip,
            hostname=hostname,
            collection_method=method,
            last_seen=datetime.now(),
            mac_address=mac,
            vendor=vendor,
        )

    @staticmethod
    def _quick_dns(ip: str) -> str:
        """Fast DNS reverse lookup with scoped timeout."""
        original_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(1.0)
        try:
            result = socket.gethostbyaddr(ip)
            return result[0].split('.')[0] if result[0] else "unknown"
        except (socket.herror, socket.gaierror, OSError):
            return "unknown"
        finally:
            socket.setdefaulttimeout(original_timeout)

    async def ping_sweep(self, subnet: str) -> List[str]:
        """
        Perform a ping sweep on a subnet.

        Args:
            subnet: CIDR notation subnet (e.g., "192.168.1.0/24")

        Returns:
            List of responding IP addresses
        """
        try:
            network = ipaddress.ip_network(subnet, strict=False)
        except ValueError as e:
            logger.error(f"Invalid subnet {subnet}: {e}")
            return []

        # Limit to reasonable size
        if network.num_addresses > 1024:
            logger.warning(f"Subnet {subnet} too large, limiting to first 256 hosts")
            hosts = list(network.hosts())[:256]
        else:
            hosts = list(network.hosts())

        logger.info(f"Scanning {len(hosts)} hosts in {subnet}")

        # Run pings concurrently with semaphore to limit parallelism
        semaphore = asyncio.Semaphore(50)

        async def ping_with_semaphore(ip: str) -> Optional[str]:
            async with semaphore:
                result = await self._ping(str(ip))
                if result:
                    return str(ip)
                return None

        tasks = [ping_with_semaphore(str(ip)) for ip in hosts]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return [ip for ip in results if ip and isinstance(ip, str)]

    async def _ping(self, ip: str) -> Optional[MachineInfo]:
        """Ping a single IP address and return MachineInfo if successful."""
        try:
            if self._is_windows:
                cmd = ["ping", "-n", "1", "-w", str(self.config.ping_timeout_ms), ip]
            else:
                timeout_sec = max(1, self.config.ping_timeout_ms // 1000)
                cmd = ["ping", "-c", "1", "-W", str(timeout_sec), ip]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

            try:
                await asyncio.wait_for(proc.wait(), timeout=self.config.ping_timeout_ms / 1000 + 1)
                if proc.returncode == 0:
                    return MachineInfo(
                        ip=ip,
                        hostname="unknown",
                        is_online=True,
                        last_seen=datetime.now(),
                        collection_method="ping",
                    )
                return None
            except asyncio.TimeoutError:
                proc.kill()
                return None

        except Exception as e:
            logger.debug(f"Ping error for {ip}: {e}")
            return None

    async def arp_scan(self) -> Dict[str, str]:
        """
        Read the ARP table to find known hosts.

        Returns:
            Dict mapping IP addresses to MAC addresses
        """
        hosts: Dict[str, str] = {}

        try:
            cmd = ["arp", "-a"]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await proc.communicate()
            output = stdout.decode("utf-8", errors="ignore")

            for line in output.split("\n"):
                if self._is_windows:
                    match = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-f-]+)", line, re.I)
                else:
                    match = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-f:]+)", line, re.I)

                if match:
                    ip = match.group(1)
                    mac = match.group(2).upper().replace("-", ":")
                    if mac and "incomplete" not in line.lower():
                        hosts[ip] = mac

        except Exception as e:
            logger.error(f"Error reading ARP table: {e}")

        logger.info(f"Found {len(hosts)} hosts in ARP table")
        return hosts

    async def check_host_alive(self, ip: str) -> bool:
        """Check if a specific host is alive."""
        return await self._ping(ip) is not None

    async def resolve_hostname(self, ip: str) -> str:
        """Attempt to resolve hostname for an IP address."""
        try:
            hostname = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: socket.gethostbyaddr(ip)[0]
            )
            return hostname
        except Exception:
            return ip


async def discover_network(
    subnets: List[str] = None,
    include_arp: bool = True,
) -> List[str]:
    """
    Convenience function to discover hosts on the network.

    Args:
        subnets: List of CIDR subnets to scan
        include_arp: Whether to include ARP table entries

    Returns:
        List of discovered IP addresses
    """
    config = DiscoveryConfig(
        subnets=subnets or ["192.168.1.0/24"],
        use_arp_scan=include_arp,
    )

    scanner = NetworkScanner(config)
    machines = await scanner.discover_all()
    return [m.ip for m in machines]
