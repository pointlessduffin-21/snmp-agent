"""
SNMP Collector for Remote Machines.

Queries remote machines that have SNMP agents installed
using standard MIBs (HOST-RESOURCES-MIB, UCD-SNMP-MIB).
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any

try:
    # Try pysnmp-lextudio v6+ without v3arch first
    from pysnmp.hlapi.asyncio import (
        getCmd,
        bulkCmd,
        nextCmd,
        SnmpEngine,
        CommunityData,
        UdpTransportTarget,
        ContextData,
        ObjectType,
        ObjectIdentity,
    )
except (ImportError, AttributeError):
    # Fallback to v3arch path if available
    from pysnmp.hlapi.v3arch.asyncio import (
        get_cmd as getCmd,
        bulk_cmd as bulkCmd,
        walk_cmd as nextCmd,
        SnmpEngine,
        CommunityData,
        UdpTransportTarget,
        ContextData,
        ObjectType,
        ObjectIdentity,
    )

from ..core.models import (
    MachineInfo,
    CPUMetrics,
    MemoryMetrics,
    StorageDevice,
    StorageMetrics,
    PowerMetrics,
    NetworkMetrics,
    HardwareSnapshot,
)


logger = logging.getLogger(__name__)


# Standard SNMP OIDs from HOST-RESOURCES-MIB and UCD-SNMP-MIB
class StandardOIDs:
    """Standard SNMP OIDs for hardware metrics."""
    
    # System MIB
    SYS_DESCR = "1.3.6.1.2.1.1.1.0"
    SYS_NAME = "1.3.6.1.2.1.1.5.0"
    SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
    SYS_LOCATION = "1.3.6.1.2.1.1.6.0"
    
    # HOST-RESOURCES-MIB
    HR_SYSTEM_UPTIME = "1.3.6.1.2.1.25.1.1.0"
    HR_PROCESSOR_LOAD = "1.3.6.1.2.1.25.3.3.1.2"  # Table
    
    # hrStorageTable
    HR_STORAGE_TYPE = "1.3.6.1.2.1.25.2.3.1.2"
    HR_STORAGE_DESCR = "1.3.6.1.2.1.25.2.3.1.3"
    HR_STORAGE_ALLOCATION_UNITS = "1.3.6.1.2.1.25.2.3.1.4"
    HR_STORAGE_SIZE = "1.3.6.1.2.1.25.2.3.1.5"
    HR_STORAGE_USED = "1.3.6.1.2.1.25.2.3.1.6"
    
    # Storage types
    HR_STORAGE_TYPE_RAM = "1.3.6.1.2.1.25.2.1.2"
    HR_STORAGE_TYPE_VIRTUAL_MEM = "1.3.6.1.2.1.25.2.1.3"
    HR_STORAGE_TYPE_FIXED_DISK = "1.3.6.1.2.1.25.2.1.4"
    
    # UCD-SNMP-MIB (Linux)
    UCD_LOAD_1 = "1.3.6.1.4.1.2021.10.1.3.1"
    UCD_LOAD_5 = "1.3.6.1.4.1.2021.10.1.3.2"
    UCD_LOAD_15 = "1.3.6.1.4.1.2021.10.1.3.3"
    
    # UCD Memory
    UCD_MEM_TOTAL = "1.3.6.1.4.1.2021.4.5.0"
    UCD_MEM_AVAIL = "1.3.6.1.4.1.2021.4.6.0"
    UCD_MEM_FREE = "1.3.6.1.4.1.2021.4.11.0"
    UCD_MEM_CACHED = "1.3.6.1.4.1.2021.4.15.0"
    UCD_MEM_BUFFER = "1.3.6.1.4.1.2021.4.14.0"
    UCD_SWAP_TOTAL = "1.3.6.1.4.1.2021.4.3.0"
    UCD_SWAP_AVAIL = "1.3.6.1.4.1.2021.4.4.0"
    
    # UCD CPU
    UCD_CPU_USER = "1.3.6.1.4.1.2021.11.9.0"
    UCD_CPU_SYSTEM = "1.3.6.1.4.1.2021.11.10.0"
    UCD_CPU_IDLE = "1.3.6.1.4.1.2021.11.11.0"


class SNMPCollector:
    """
    Collects hardware metrics from remote SNMP agents.
    
    Supports SNMPv2c and SNMPv3 for querying standard MIBs.
    """
    
    def __init__(
        self,
        community: str = "public",
        port: int = 161,
        timeout: float = 2.0,
        retries: int = 1,
    ):
        self.community = community
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self._engine = SnmpEngine()
    
    async def _get_oid(self, ip: str, oid: str) -> Optional[Any]:
        """Get a single OID value from a host."""
        try:
            iterator = getCmd(
                self._engine,
                CommunityData(self.community),
                UdpTransportTarget((ip, self.port), timeout=self.timeout, retries=self.retries),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )
            
            errorIndication, errorStatus, errorIndex, varBinds = await iterator
            
            if errorIndication:
                logger.debug(f"SNMP error for {ip}: {errorIndication}")
                return None
            elif errorStatus:
                logger.debug(f"SNMP error status for {ip}: {errorStatus}")
                return None
            
            if varBinds:
                return varBinds[0][1]
                
        except Exception as e:
            logger.debug(f"Failed to get OID {oid} from {ip}: {e}")
        
        return None
    
    async def _get_oids(self, ip: str, oids: list) -> Dict[str, Any]:
        """Get multiple OIDs from a host."""
        results = {}
        
        try:
            object_types = [ObjectType(ObjectIdentity(oid)) for oid in oids]
            
            iterator = getCmd(
                self._engine,
                CommunityData(self.community),
                UdpTransportTarget((ip, self.port), timeout=self.timeout, retries=self.retries),
                ContextData(),
                *object_types,
            )
            
            errorIndication, errorStatus, errorIndex, varBinds = await iterator
            
            if errorIndication or errorStatus:
                return results
            
            for varBind in varBinds:
                oid_str = str(varBind[0])
                results[oid_str] = varBind[1]
                
        except Exception as e:
            logger.debug(f"Failed to get OIDs from {ip}: {e}")
        
        return results
    
    async def _walk_oid(self, ip: str, oid: str) -> Dict[str, Any]:
        """Walk an OID subtree - uses subprocess snmpwalk for reliability."""
        results = {}
        
        try:
            import asyncio
            import subprocess
            
            # Use subprocess snmpwalk which is more reliable
            cmd = [
                'snmpwalk', '-v2c', '-c', self.community,
                '-On',  # Numeric OID output
                '-Oq',  # Quick print
                ip, oid
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout * 3)
            
            if proc.returncode == 0:
                for line in stdout.decode('utf-8', errors='ignore').strip().split('\n'):
                    if not line.strip():
                        continue
                    # Format from -Oq is: .OID value
                    parts = line.strip().split(' ', 1)
                    if len(parts) >= 2:
                        oid_str = parts[0].lstrip('.')
                        value = parts[1].strip().strip('"')
                        results[oid_str] = value
                    elif len(parts) == 1 and parts[0]:
                        oid_str = parts[0].lstrip('.')
                        results[oid_str] = ""
                        
        except asyncio.TimeoutError:
            logger.debug(f"SNMP walk timeout for {oid} from {ip}")
        except Exception as e:
            logger.debug(f"Failed to walk OID {oid} from {ip}: {e}")
        
        return results
    
    async def check_snmp_available(self, ip: str) -> bool:
        """Check if SNMP is available on a host."""
        result = await self._get_oid(ip, StandardOIDs.SYS_NAME)
        return result is not None
    
    async def get_machine_info(self, ip: str) -> Optional[MachineInfo]:
        """Get machine information via SNMP."""
        oids = [
            StandardOIDs.SYS_NAME,
            StandardOIDs.SYS_DESCR,
            StandardOIDs.SYS_UPTIME,
        ]
        
        results = await self._get_oids(ip, oids)
        
        if not results:
            return None
        
        # Extract values
        hostname = "unknown"
        os_type = "unknown"
        uptime = 0
        
        for oid, value in results.items():
            if StandardOIDs.SYS_NAME in oid:
                hostname = str(value)
            elif StandardOIDs.SYS_DESCR in oid:
                descr = str(value).lower()
                if "linux" in descr:
                    os_type = "Linux"
                elif "windows" in descr:
                    os_type = "Windows"
                elif "darwin" in descr or "mac" in descr:
                    os_type = "Darwin"
            elif StandardOIDs.SYS_UPTIME in oid:
                try:
                    # Uptime is in hundredths of a second
                    uptime = int(value) // 100
                except (ValueError, TypeError):
                    pass
        
        return MachineInfo(
            ip=ip,
            hostname=hostname,
            os_type=os_type,
            uptime_seconds=uptime,
            last_seen=datetime.now(),
            is_online=True,
            collection_method="snmp",
            snmp_active=True,  # SNMP responded successfully
            snmp_sysname=hostname if hostname != "unknown" else "",
        )
    
    async def get_cpu_metrics(self, ip: str) -> CPUMetrics:
        """Get CPU metrics via SNMP."""
        # Get load averages from UCD-SNMP-MIB
        load_oids = [
            StandardOIDs.UCD_LOAD_1,
            StandardOIDs.UCD_LOAD_5,
            StandardOIDs.UCD_LOAD_15,
            StandardOIDs.UCD_CPU_USER,
            StandardOIDs.UCD_CPU_SYSTEM,
            StandardOIDs.UCD_CPU_IDLE,
        ]
        
        results = await self._get_oids(ip, load_oids)
        
        load_1m = load_5m = load_15m = 0.0
        cpu_usage = 0.0
        
        for oid, value in results.items():
            try:
                if StandardOIDs.UCD_LOAD_1 in oid:
                    load_1m = float(str(value))
                elif StandardOIDs.UCD_LOAD_5 in oid:
                    load_5m = float(str(value))
                elif StandardOIDs.UCD_LOAD_15 in oid:
                    load_15m = float(str(value))
                elif StandardOIDs.UCD_CPU_IDLE in oid:
                    cpu_usage = 100.0 - float(value)
            except (ValueError, TypeError):
                pass
        
        # Get processor count from hrProcessorLoad table
        processor_loads = await self._walk_oid(ip, StandardOIDs.HR_PROCESSOR_LOAD)
        core_count = len(processor_loads)
        
        # Calculate average CPU usage from processor loads if available
        if processor_loads and not cpu_usage:
            total_load = sum(int(v) for v in processor_loads.values())
            cpu_usage = total_load / len(processor_loads) if processor_loads else 0.0
        
        return CPUMetrics(
            usage_percent=cpu_usage,
            core_count=core_count,
            thread_count=core_count,  # SNMP doesn't distinguish
            load_1m=load_1m,
            load_5m=load_5m,
            load_15m=load_15m,
        )
    
    async def get_memory_metrics(self, ip: str) -> MemoryMetrics:
        """Get memory metrics via SNMP."""
        mem_oids = [
            StandardOIDs.UCD_MEM_TOTAL,
            StandardOIDs.UCD_MEM_AVAIL,
            StandardOIDs.UCD_MEM_FREE,
            StandardOIDs.UCD_MEM_CACHED,
            StandardOIDs.UCD_MEM_BUFFER,
            StandardOIDs.UCD_SWAP_TOTAL,
            StandardOIDs.UCD_SWAP_AVAIL,
        ]
        
        results = await self._get_oids(ip, mem_oids)
        
        # UCD-SNMP reports memory in KB
        total = available = free = cached = buffers = 0
        swap_total = swap_avail = 0
        
        for oid, value in results.items():
            try:
                kb_value = int(value) * 1024  # Convert to bytes
                if StandardOIDs.UCD_MEM_TOTAL in oid:
                    total = kb_value
                elif StandardOIDs.UCD_MEM_AVAIL in oid:
                    available = kb_value
                elif StandardOIDs.UCD_MEM_FREE in oid:
                    free = kb_value
                elif StandardOIDs.UCD_MEM_CACHED in oid:
                    cached = kb_value
                elif StandardOIDs.UCD_MEM_BUFFER in oid:
                    buffers = kb_value
                elif StandardOIDs.UCD_SWAP_TOTAL in oid:
                    swap_total = kb_value
                elif StandardOIDs.UCD_SWAP_AVAIL in oid:
                    swap_avail = kb_value
            except (ValueError, TypeError):
                pass
        
        # If UCD-SNMP not available, try hrStorage
        if not total:
            storage_data = await self._walk_oid(ip, StandardOIDs.HR_STORAGE_TYPE)
            # Process hrStorage for RAM type
            # This is more complex and requires correlating multiple tables
        
        used = total - available if total and available else 0
        usage_percent = (used / total * 100) if total else 0.0
        
        swap_used = swap_total - swap_avail if swap_total and swap_avail else 0
        swap_usage = (swap_used / swap_total * 100) if swap_total else 0.0
        
        return MemoryMetrics(
            total_bytes=total,
            used_bytes=used,
            available_bytes=available,
            cached_bytes=cached,
            buffers_bytes=buffers,
            usage_percent=usage_percent,
            swap_total_bytes=swap_total,
            swap_used_bytes=swap_used,
            swap_free_bytes=swap_avail,
            swap_usage_percent=swap_usage,
        )
    
    async def get_storage_metrics(self, ip: str) -> StorageMetrics:
        """Get storage metrics via SNMP hrStorageTable."""
        devices = []
        
        # Walk hrStorageTable
        types = await self._walk_oid(ip, StandardOIDs.HR_STORAGE_TYPE)
        descrs = await self._walk_oid(ip, StandardOIDs.HR_STORAGE_DESCR)
        alloc_units = await self._walk_oid(ip, StandardOIDs.HR_STORAGE_ALLOCATION_UNITS)
        sizes = await self._walk_oid(ip, StandardOIDs.HR_STORAGE_SIZE)
        useds = await self._walk_oid(ip, StandardOIDs.HR_STORAGE_USED)
        
        # Extract indexes from OIDs
        def get_index(oid: str) -> str:
            return oid.split(".")[-1]
        
        # Build storage entries
        for oid, storage_type in types.items():
            idx = get_index(oid)
            type_str = str(storage_type)
            
            # Only include fixed disk storage
            if StandardOIDs.HR_STORAGE_TYPE_FIXED_DISK not in type_str:
                continue
            
            try:
                descr_oid = f"{StandardOIDs.HR_STORAGE_DESCR}.{idx}"
                alloc_oid = f"{StandardOIDs.HR_STORAGE_ALLOCATION_UNITS}.{idx}"
                size_oid = f"{StandardOIDs.HR_STORAGE_SIZE}.{idx}"
                used_oid = f"{StandardOIDs.HR_STORAGE_USED}.{idx}"
                
                descr = str(descrs.get(descr_oid, "Unknown"))
                alloc = int(alloc_units.get(alloc_oid, 1))
                size = int(sizes.get(size_oid, 0)) * alloc
                used = int(useds.get(used_oid, 0)) * alloc
                free = size - used
                usage = (used / size * 100) if size else 0.0
                
                device = StorageDevice(
                    device=descr,
                    mount_point=descr,
                    total_bytes=size,
                    used_bytes=used,
                    free_bytes=free,
                    usage_percent=usage,
                )
                devices.append(device)
            except (ValueError, TypeError, KeyError) as e:
                logger.debug(f"Error processing storage entry: {e}")
        
        return StorageMetrics(devices=devices)
    
    async def collect_all_simple(self, ip: str) -> Optional[HardwareSnapshot]:
        """Collect all metrics using SNMP GET/WALK requests."""
        import time
        start_time = time.time()
        errors = []
        
        # Get machine info
        machine = await self.get_machine_info(ip)
        if not machine:
            return None
        
        # Initialize metrics with defaults
        cpu_metrics = CPUMetrics()
        memory_metrics = MemoryMetrics()
        storage_metrics = StorageMetrics()
        
        # --- CPU Metrics ---
        try:
            # Get load averages from UCD-SNMP-MIB
            load_oids = [
                StandardOIDs.UCD_LOAD_1,
                StandardOIDs.UCD_LOAD_5,
                StandardOIDs.UCD_LOAD_15,
            ]
            results = await self._get_oids(ip, load_oids)
            
            for oid, value in results.items():
                try:
                    if StandardOIDs.UCD_LOAD_1 in oid:
                        cpu_metrics.load_1m = float(str(value))
                    elif StandardOIDs.UCD_LOAD_5 in oid:
                        cpu_metrics.load_5m = float(str(value))
                    elif StandardOIDs.UCD_LOAD_15 in oid:
                        cpu_metrics.load_15m = float(str(value))
                except (ValueError, TypeError):
                    pass
            
            # Walk hrProcessorLoad to get per-CPU usage and core count
            processor_loads = await self._walk_oid(ip, StandardOIDs.HR_PROCESSOR_LOAD)
            if processor_loads:
                core_count = len(processor_loads)
                total_load = sum(int(v) for v in processor_loads.values() if v)
                avg_load = total_load / core_count if core_count else 0.0
                
                cpu_metrics.core_count = core_count
                cpu_metrics.thread_count = core_count
                cpu_metrics.usage_percent = avg_load
                
        except Exception as e:
            errors.append(f"CPU: {e}")
            logger.debug(f"CPU collection error for {ip}: {e}")
        
        # --- Memory Metrics ---
        try:
            mem_total = await self._get_oid(ip, StandardOIDs.UCD_MEM_TOTAL)
            mem_avail = await self._get_oid(ip, StandardOIDs.UCD_MEM_AVAIL)
            mem_cached = await self._get_oid(ip, StandardOIDs.UCD_MEM_CACHED)
            mem_buffer = await self._get_oid(ip, StandardOIDs.UCD_MEM_BUFFER)
            swap_total = await self._get_oid(ip, StandardOIDs.UCD_SWAP_TOTAL)
            swap_avail = await self._get_oid(ip, StandardOIDs.UCD_SWAP_AVAIL)
            
            if mem_total and mem_avail:
                total_bytes = int(mem_total) * 1024
                avail_bytes = int(mem_avail) * 1024
                used_bytes = total_bytes - avail_bytes
                cached_bytes = int(mem_cached) * 1024 if mem_cached else 0
                buffer_bytes = int(mem_buffer) * 1024 if mem_buffer else 0
                swap_total_bytes = int(swap_total) * 1024 if swap_total else 0
                swap_avail_bytes = int(swap_avail) * 1024 if swap_avail else 0
                swap_used_bytes = swap_total_bytes - swap_avail_bytes
                
                memory_metrics = MemoryMetrics(
                    total_bytes=total_bytes,
                    used_bytes=used_bytes,
                    available_bytes=avail_bytes,
                    cached_bytes=cached_bytes,
                    buffers_bytes=buffer_bytes,
                    usage_percent=(used_bytes / total_bytes * 100) if total_bytes else 0,
                    swap_total_bytes=swap_total_bytes,
                    swap_used_bytes=swap_used_bytes,
                    swap_free_bytes=swap_avail_bytes,
                    swap_usage_percent=(swap_used_bytes / swap_total_bytes * 100) if swap_total_bytes else 0,
                )
        except Exception as e:
            errors.append(f"Memory: {e}")
            logger.debug(f"Memory collection error for {ip}: {e}")
        
        # --- Storage Metrics ---
        try:
            devices = []
            
            # Walk hrStorageTable
            types = await self._walk_oid(ip, StandardOIDs.HR_STORAGE_TYPE)
            descrs = await self._walk_oid(ip, StandardOIDs.HR_STORAGE_DESCR)
            alloc_units = await self._walk_oid(ip, StandardOIDs.HR_STORAGE_ALLOCATION_UNITS)
            sizes = await self._walk_oid(ip, StandardOIDs.HR_STORAGE_SIZE)
            useds = await self._walk_oid(ip, StandardOIDs.HR_STORAGE_USED)
            
            # Extract index from OID
            def get_index(oid: str) -> str:
                return oid.split(".")[-1]
            
            # Helper to extract numeric value
            def extract_int(val, default=0):
                try:
                    s = str(val).strip()
                    import re
                    match = re.search(r'(\d+)', s)
                    return int(match.group(1)) if match else default
                except:
                    return default

            # Build storage entries
            for oid, storage_type in types.items():
                idx = get_index(oid)
                type_str = str(storage_type).lstrip('.')
                
                # Check for RAM (hrStorageRam .25.2.1.2) if UCD memory failed
                is_ram = type_str == '1.3.6.1.2.1.25.2.1.2' or type_str.endswith('.25.2.1.2')
                
                # Check for Virtual Memory / Paging (hrStorageVirtualMemory .25.2.1.3)
                is_virtual = type_str == '1.3.6.1.2.1.25.2.1.3' or type_str.endswith('.25.2.1.3')

                # Check for Fixed Disk
                is_fixed_disk = (
                    type_str == StandardOIDs.HR_STORAGE_TYPE_FIXED_DISK or
                    type_str.endswith('.25.2.1.4')
                )
                
                if not (is_fixed_disk or is_ram or is_virtual):
                    continue
                
                try:
                    descr_oid = f"{StandardOIDs.HR_STORAGE_DESCR}.{idx}"
                    alloc_oid = f"{StandardOIDs.HR_STORAGE_ALLOCATION_UNITS}.{idx}"
                    size_oid = f"{StandardOIDs.HR_STORAGE_SIZE}.{idx}"
                    used_oid = f"{StandardOIDs.HR_STORAGE_USED}.{idx}"
                    
                    descr = str(descrs.get(descr_oid, "Unknown"))
                    alloc = extract_int(alloc_units.get(alloc_oid, 1), 1)
                    size = extract_int(sizes.get(size_oid, 0)) * alloc
                    used = extract_int(useds.get(used_oid, 0)) * alloc
                    free = size - used
                    usage = (used / size * 100) if size else 0.0

                    # Handle RAM
                    if is_ram and memory_metrics.total_bytes == 0:
                        memory_metrics.total_bytes = size
                        memory_metrics.used_bytes = used
                        memory_metrics.available_bytes = free
                        memory_metrics.usage_percent = usage
                        continue

                    # Handle Virtual Memory (Swap)
                    if is_virtual and memory_metrics.swap_total_bytes == 0:
                        memory_metrics.swap_total_bytes = size
                        memory_metrics.swap_used_bytes = used
                        memory_metrics.swap_free_bytes = free
                        memory_metrics.swap_usage_percent = usage
                        continue
                    
                    # Only calculate storage for fixed disks
                    if not is_fixed_disk:
                        continue
                    
                    # Skip tmpfs and memory-based filesystems
                    if any(skip in descr.lower() for skip in ['tmpfs', '/dev/shm', '/run', 'run/']):
                        continue
                    
                    # Only include if there's meaningful size (> 100 MB)
                    if size > 100 * 1024 * 1024:
                        device = StorageDevice(
                            device=descr,
                            mount_point=descr,
                            total_bytes=size,
                            used_bytes=used,
                            free_bytes=free,
                            usage_percent=usage,
                        )
                        devices.append(device)
                        
                except (ValueError, TypeError, KeyError) as e:
                    logger.debug(f"Error processing storage entry {idx}: {e}")
            
            storage_metrics = StorageMetrics(devices=devices)
            
        except Exception as e:
            errors.append(f"Storage: {e}")
            logger.debug(f"Storage collection error for {ip}: {e}")
        
        duration_ms = (time.time() - start_time) * 1000
        logger.info(f"SNMP collection for {ip} completed in {duration_ms:.0f}ms - "
                    f"CPU: {cpu_metrics.usage_percent:.1f}%, "
                    f"Mem: {memory_metrics.usage_percent:.1f}%, "
                    f"Storage: {len(storage_metrics.devices)} devices")
        
        return HardwareSnapshot(
            machine=machine,
            cpu=cpu_metrics,
            memory=memory_metrics,
            storage=storage_metrics,
            power=PowerMetrics(),
            network=NetworkMetrics(),
            timestamp=datetime.now(),
            collection_duration_ms=duration_ms,
            errors=errors,
        )
    
    async def collect_all(self, ip: str) -> Optional[HardwareSnapshot]:
        """Collect all available metrics from a remote host."""
        return await self.collect_all_simple(ip)

