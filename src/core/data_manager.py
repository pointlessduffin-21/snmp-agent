"""
Data Manager - Aggregation layer for hardware metrics.

Coordinates collection from multiple sources and maintains
the current state of all monitored machines.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from .models import HardwareSnapshot, MachineInfo
from .config import Config


logger = logging.getLogger(__name__)


class DataManager:
    """
    Central data manager for hardware metrics aggregation.

    Coordinates between collectors and maintains the current
    state of all discovered machines.
    """

    def __init__(self, config: Config, db=None):
        self.config = config
        self.db = db
        self._snapshots: Dict[str, HardwareSnapshot] = {}
        self._machines: Dict[str, MachineInfo] = {}
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=10)
        self._running = False
        self._collection_task: Optional[asyncio.Task] = None

    async def get_machines(self) -> List[MachineInfo]:
        """Get list of all known machines."""
        async with self._lock:
            return list(self._machines.values())

    async def get_snapshots(self) -> Dict[str, HardwareSnapshot]:
        """Get all current snapshots keyed by IP."""
        async with self._lock:
            return self._snapshots.copy()

    async def get_snapshot(self, ip: str) -> Optional[HardwareSnapshot]:
        """Get snapshot for a specific machine."""
        async with self._lock:
            return self._snapshots.get(ip)

    async def get_machine(self, ip: str) -> Optional[MachineInfo]:
        """Get machine info by IP."""
        async with self._lock:
            return self._machines.get(ip)

    async def add_machine(self, machine: MachineInfo):
        """Add or update a machine in the registry, merging with existing data."""
        async with self._lock:
            if machine.ip in self._machines:
                existing = self._machines[machine.ip]
                self._merge_machines(existing, machine)
            else:
                self._machines[machine.ip] = machine
                logger.debug(f"Added machine {machine.ip}: hostname={machine.hostname}, method={machine.collection_method}")
            self._persist_device(machine.ip)

    def _persist_device(self, ip: str):
        """Persist a device to the database if available."""
        if not self.db or ip not in self._machines:
            return
        m = self._machines[ip]
        self.db.save_device(ip, {
            "hostname": m.hostname,
            "os_type": m.os_type,
            "os_version": m.os_version,
            "mac_address": m.mac_address,
            "vendor": m.vendor,
            "collection_method": m.collection_method,
            "snmp_active": m.snmp_active,
            "dns_name": m.dns_name,
            "mdns_name": m.mdns_name,
            "netbios_name": m.netbios_name,
            "snmp_sysname": m.snmp_sysname,
            "last_seen": m.last_seen.isoformat(),
            "is_online": m.is_online,
            "device_type": m.device_type,
        })

    def _merge_machines(self, existing: MachineInfo, new_info: MachineInfo):
        """Internal helper to merge machine info."""
        if new_info.hostname and new_info.hostname != 'unknown' and new_info.hostname != new_info.ip:
            existing.hostname = new_info.hostname

        if new_info.os_type and new_info.os_type != 'unknown':
            existing.os_type = new_info.os_type
        if new_info.os_version:
            existing.os_version = new_info.os_version
        if new_info.uptime_seconds > 0:
            existing.uptime_seconds = new_info.uptime_seconds
        if new_info.mac_address:
            existing.mac_address = new_info.mac_address
        if new_info.vendor and new_info.vendor != 'Unknown':
            existing.vendor = new_info.vendor

        # Extended fields
        for attr in ['dns_name', 'mdns_name', 'netbios_name', 'snmp_sysname', 'sys_descr']:
            new_val = getattr(new_info, attr, None)
            if new_val:
                setattr(existing, attr, new_val)

        if new_info.is_online:
            existing.is_online = True
        existing.last_seen = new_info.last_seen

        # Preserve snmp_active
        if new_info.snmp_active:
            existing.snmp_active = True

        # Method priority
        method_priority = {'snmp': 4, 'ssh': 3, 'local': 2, 'arp': 1, 'ping': 1, '?': 0}
        existing_prio = method_priority.get(existing.collection_method, 0)
        new_prio = method_priority.get(new_info.collection_method, 0)
        if new_prio > existing_prio:
            existing.collection_method = new_info.collection_method

    async def remove_machine(self, ip: str):
        """Remove a machine from the registry."""
        async with self._lock:
            if ip in self._machines:
                del self._machines[ip]
            if ip in self._snapshots:
                del self._snapshots[ip]
            if self.db:
                self.db.delete_device(ip)
            logger.info(f"Removed machine: {ip}")

    async def update_snapshot(self, snapshot: HardwareSnapshot):
        """Update the snapshot for a machine, preserving discovery data."""
        async with self._lock:
            ip = snapshot.machine.ip

            if ip in self._machines:
                existing = self._machines[ip]
                self._merge_machines(existing, snapshot.machine)
                snapshot.machine = existing
            else:
                self._machines[ip] = snapshot.machine

            self._snapshots[ip] = snapshot
            self._persist_device(ip)
            logger.debug(f"Updated snapshot for {ip}")

    async def update_snapshots(self, snapshots: List[HardwareSnapshot]):
        """Bulk update snapshots."""
        async with self._lock:
            for snapshot in snapshots:
                ip = snapshot.machine.ip
                if ip in self._machines:
                    existing = self._machines[ip]
                    self._merge_machines(existing, snapshot.machine)
                    snapshot.machine = existing
                else:
                    self._machines[ip] = snapshot.machine
                self._snapshots[ip] = snapshot
                self._persist_device(ip)
            logger.info(f"Updated {len(snapshots)} snapshots")

    async def get_machines_by_status(self, online: bool = True) -> List[MachineInfo]:
        """Get machines filtered by online status."""
        async with self._lock:
            return [m for m in self._machines.values() if m.is_online == online]

    async def get_stale_machines(self, max_age_seconds: int = 300) -> List[MachineInfo]:
        """Get machines that haven't been updated recently."""
        async with self._lock:
            cutoff = datetime.now() - timedelta(seconds=max_age_seconds)
            stale = []
            for ip, snapshot in self._snapshots.items():
                if snapshot.timestamp < cutoff:
                    stale.append(snapshot.machine)
            return stale

    async def mark_stale_offline(self, max_age_seconds: int = 300):
        """Mark stale machines as offline."""
        async with self._lock:
            cutoff = datetime.now() - timedelta(seconds=max_age_seconds)
            for ip, snapshot in self._snapshots.items():
                if snapshot.timestamp < cutoff and snapshot.machine.is_online:
                    snapshot.machine.is_online = False
                    logger.info(f"Marked {ip} as offline (stale for >{max_age_seconds}s)")

    async def get_aggregated_stats(self) -> dict:
        """Get aggregated statistics across all machines."""
        async with self._lock:
            if not self._snapshots:
                return {
                    "machine_count": 0,
                    "online_count": 0,
                    "offline_count": 0,
                }

            online = len([s for s in self._snapshots.values() if s.machine.is_online])

            total_cpu = sum(s.cpu.usage_percent for s in self._snapshots.values())
            avg_cpu = total_cpu / len(self._snapshots) if self._snapshots else 0

            total_memory = sum(s.memory.total_bytes for s in self._snapshots.values())
            used_memory = sum(s.memory.used_bytes for s in self._snapshots.values())

            total_storage = sum(s.storage.total_bytes for s in self._snapshots.values())
            used_storage = sum(s.storage.used_bytes for s in self._snapshots.values())

            return {
                "machine_count": len(self._snapshots),
                "online_count": online,
                "offline_count": len(self._snapshots) - online,
                "avg_cpu_percent": round(avg_cpu, 2),
                "total_memory_gb": round(total_memory / (1024**3), 2),
                "used_memory_gb": round(used_memory / (1024**3), 2),
                "memory_usage_percent": round(used_memory / total_memory * 100, 2) if total_memory else 0,
                "total_storage_gb": round(total_storage / (1024**3), 2),
                "used_storage_gb": round(used_storage / (1024**3), 2),
                "storage_usage_percent": round(used_storage / total_storage * 100, 2) if total_storage else 0,
            }

    def clear(self):
        """Clear all stored data."""
        self._snapshots.clear()
        self._machines.clear()
        logger.info("Cleared all data")

    def __len__(self) -> int:
        """Return number of monitored machines."""
        return len(self._machines)
