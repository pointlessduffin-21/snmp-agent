"""
Data Manager - Aggregation layer for hardware metrics.

Coordinates collection from multiple sources and maintains
the current state of all monitored machines.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
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
    
    def __init__(self, config: Config):
        self.config = config
        self._snapshots: Dict[str, HardwareSnapshot] = {}
        self._machines: Dict[str, MachineInfo] = {}
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=10)
        self._running = False
        self._collection_task: Optional[asyncio.Task] = None
        
    @property
    def machines(self) -> List[MachineInfo]:
        """Get list of all known machines."""
        return list(self._machines.values())
    
    @property
    def snapshots(self) -> Dict[str, HardwareSnapshot]:
        """Get all current snapshots keyed by IP."""
        return self._snapshots.copy()
    
    def get_snapshot(self, ip: str) -> Optional[HardwareSnapshot]:
        """Get snapshot for a specific machine."""
        return self._snapshots.get(ip)
    
    def get_machine(self, ip: str) -> Optional[MachineInfo]:
        """Get machine info by IP."""
        return self._machines.get(ip)
    
    async def add_machine(self, machine: MachineInfo):
        """Add or update a machine in the registry, merging with existing data."""
        async with self._lock:
            if machine.ip in self._machines:
                existing = self._machines[machine.ip]
                # Merge data into existing
                self._merge_machines(existing, machine)
            else:
                self._machines[machine.ip] = machine
                print(f"[ADD] {machine.ip}: hostname={machine.hostname}, method={machine.collection_method}")

    def _merge_machines(self, existing: MachineInfo, new_info: MachineInfo):
        """Internal helper to merge machine info."""
        print(f"[MERGE] {existing.ip}: existing hostname={existing.hostname}, snmp={getattr(existing, 'snmp_active', False)}, method={existing.collection_method}")
        print(f"[MERGE] {existing.ip}: new hostname={new_info.hostname}, snmp={getattr(new_info, 'snmp_active', False)}, method={new_info.collection_method}")
        
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
        for field in ['dns_name', 'mdns_name', 'netbios_name', 'snmp_sysname', 'sys_descr']:
            if hasattr(new_info, field) and getattr(new_info, field):
                setattr(existing, field, getattr(new_info, field))

        if new_info.is_online:
            existing.is_online = True
        existing.last_seen = new_info.last_seen
        
        # Preserve snmp_active
        if hasattr(new_info, 'snmp_active') and new_info.snmp_active:
            existing.snmp_active = True
        elif not hasattr(existing, 'snmp_active'):
            existing.snmp_active = False
            
        # Method priority
        method_priority = {'snmp': 4, 'ssh': 3, 'local': 2, 'arp': 1, 'ping': 1, '?': 0}
        existing_prio = method_priority.get(existing.collection_method, 0)
        new_prio = method_priority.get(new_info.collection_method, 0)
        if new_prio > existing_prio:
            existing.collection_method = new_info.collection_method
            
        print(f"[MERGE] {existing.ip}: result hostname={existing.hostname}, snmp={getattr(existing, 'snmp_active', False)}, method={existing.collection_method}")

    async def remove_machine(self, ip: str):
        """Remove a machine from the registry."""
        async with self._lock:
            if ip in self._machines:
                del self._machines[ip]
            if ip in self._snapshots:
                del self._snapshots[ip]
            logger.info(f"Removed machine: {ip}")
    
    async def update_snapshot(self, snapshot: HardwareSnapshot):
        """Update the snapshot for a machine, preserving discovery data."""
        async with self._lock:
            ip = snapshot.machine.ip
            
            if ip in self._machines:
                existing = self._machines[ip]
                # Merge new info from snapshot into existing machine object
                self._merge_machines(existing, snapshot.machine)
                # Point snapshot at our authoritative machine object
                snapshot.machine = existing
            else:
                self._machines[ip] = snapshot.machine
            
            self._snapshots[ip] = snapshot
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
            logger.info(f"Updated {len(snapshots)} snapshots")

    async def update_custom_metric(self, ip: str, oid: str, value: Any):
        """Update a custom metric for a machine."""
        async with self._lock:
            if ip in self._snapshots:
                snapshot = self._snapshots[ip]
                # Ensure custom_metrics dict exists (for backward compatibility if pickle loaded old obj)
                if not hasattr(snapshot, 'custom_metrics'):
                    snapshot.custom_metrics = {}
                
                snapshot.custom_metrics[oid] = value
                logger.debug(f"Updated custom metric for {ip}: {oid}={value}")
            else:
                logger.warning(f"Cannot update custom metric for unknown machine: {ip}")
    
    def get_machines_by_status(self, online: bool = True) -> List[MachineInfo]:
        """Get machines filtered by online status."""
        return [m for m in self._machines.values() if m.is_online == online]
    
    def get_stale_machines(self, max_age_seconds: int = 300) -> List[MachineInfo]:
        """Get machines that haven't been updated recently."""
        cutoff = datetime.now() - timedelta(seconds=max_age_seconds)
        stale = []
        for ip, snapshot in self._snapshots.items():
            if snapshot.timestamp < cutoff:
                stale.append(snapshot.machine)
        return stale
    
    def get_aggregated_stats(self) -> dict:
        """Get aggregated statistics across all machines."""
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
