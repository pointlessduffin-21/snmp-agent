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
                # Merge: preserve existing fields that new data doesn't have
                existing = self._machines[machine.ip]
                print(f"[MERGE] {machine.ip}: existing hostname={existing.hostname}, snmp_active={getattr(existing, 'snmp_active', False)}, method={existing.collection_method}")
                print(f"[MERGE] {machine.ip}: new hostname={machine.hostname}, snmp_active={getattr(machine, 'snmp_active', False)}, method={machine.collection_method}")
                
                # Update existing with new values only if new values are meaningful
                if machine.hostname and machine.hostname != 'unknown' and machine.hostname != machine.ip:
                    existing.hostname = machine.hostname
                if machine.os_type and machine.os_type != 'unknown':
                    existing.os_type = machine.os_type
                if machine.os_version:
                    existing.os_version = machine.os_version
                if machine.uptime_seconds > 0:
                    existing.uptime_seconds = machine.uptime_seconds
                if machine.mac_address:
                    existing.mac_address = machine.mac_address
                if machine.vendor and machine.vendor != 'Unknown':
                    existing.vendor = machine.vendor
                if hasattr(machine, 'dns_name') and machine.dns_name:
                    existing.dns_name = machine.dns_name
                if hasattr(machine, 'mdns_name') and machine.mdns_name:
                    existing.mdns_name = machine.mdns_name
                if hasattr(machine, 'netbios_name') and machine.netbios_name:
                    existing.netbios_name = machine.netbios_name
                if hasattr(machine, 'sys_descr') and machine.sys_descr:
                    existing.sys_descr = machine.sys_descr
                if machine.is_online:
                    existing.is_online = True
                existing.last_seen = machine.last_seen
                
                # Preserve snmp_active if already set
                if hasattr(existing, 'snmp_active') and existing.snmp_active:
                    # Keep snmp_active=True
                    pass
                elif hasattr(machine, 'snmp_active') and machine.snmp_active:
                    existing.snmp_active = True
                
                # Preserve snmp_sysname
                if hasattr(machine, 'snmp_sysname') and machine.snmp_sysname:
                    existing.snmp_sysname = machine.snmp_sysname
                
                # Only update collection_method if new method is "better" (snmp/ssh > local > arp)
                method_priority = {'snmp': 4, 'ssh': 3, 'local': 2, 'arp': 1}
                existing_priority = method_priority.get(existing.collection_method, 0)
                new_priority = method_priority.get(machine.collection_method, 0)
                if new_priority > existing_priority:
                    existing.collection_method = machine.collection_method
                
                print(f"[MERGE] {machine.ip}: result hostname={existing.hostname}, snmp_active={getattr(existing, 'snmp_active', False)}, method={existing.collection_method}")
            else:
                self._machines[machine.ip] = machine
                print(f"[ADD] {machine.ip}: hostname={machine.hostname}, method={machine.collection_method}")
    
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
            
            # Preserve existing machine metadata if available
            if ip in self._machines:
                existing = self._machines[ip]
                machine = snapshot.machine
                
                # Merge: keep discovery data, update with new collector data
                machine.mac_address = machine.mac_address or existing.mac_address
                machine.vendor = machine.vendor if machine.vendor and machine.vendor != 'Unknown' else existing.vendor
                machine.hostname = machine.hostname if machine.hostname and machine.hostname != 'unknown' else existing.hostname
                machine.dns_name = getattr(machine, 'dns_name', '') or getattr(existing, 'dns_name', '')
                machine.mdns_name = getattr(machine, 'mdns_name', '') or getattr(existing, 'mdns_name', '')
                machine.netbios_name = getattr(machine, 'netbios_name', '') or getattr(existing, 'netbios_name', '')
            
            self._snapshots[ip] = snapshot
            self._machines[ip] = snapshot.machine
            logger.debug(f"Updated snapshot for {ip}")
    
    async def update_snapshots(self, snapshots: List[HardwareSnapshot]):
        """Bulk update snapshots."""
        async with self._lock:
            for snapshot in snapshots:
                ip = snapshot.machine.ip
                self._snapshots[ip] = snapshot
                self._machines[ip] = snapshot.machine
            logger.info(f"Updated {len(snapshots)} snapshots")
    
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
