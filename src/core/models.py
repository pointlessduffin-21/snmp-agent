"""
Data models for hardware metrics.

These dataclasses represent the structured hardware information
collected from machines on the network.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class MachineInfo:
    """Basic machine identification information."""
    
    ip: str
    hostname: str = "unknown"
    os_type: str = "unknown"
    os_version: str = ""
    uptime_seconds: int = 0
    last_seen: datetime = field(default_factory=datetime.now)
    is_online: bool = True
    collection_method: str = "unknown"  # snmp, ssh, local, wmi
    mac_address: str = ""
    vendor: str = ""
    snmp_active: bool = False  # True if SNMP is responding
    # Extended name resolution fields
    dns_name: str = ""
    mdns_name: str = ""
    netbios_name: str = ""
    snmp_sysname: str = ""
    
    @property
    def display_name(self) -> str:
        """Get the best available display name for this device."""
        # Priority: SNMP sysName > mDNS > NetBIOS > DNS > hostname > IP
        if self.snmp_sysname and self.snmp_sysname != "unknown":
            return self.snmp_sysname
        if self.mdns_name and self.mdns_name != "unknown":
            return self.mdns_name
        if self.netbios_name and self.netbios_name != "unknown":
            return self.netbios_name
        if self.dns_name and self.dns_name != "unknown":
            return self.dns_name
        if self.hostname and self.hostname != "unknown":
            return self.hostname
        return self.ip
    
    def __post_init__(self):
        if isinstance(self.last_seen, str):
            self.last_seen = datetime.fromisoformat(self.last_seen)


@dataclass
class CPUMetrics:
    """CPU-related metrics."""
    
    usage_percent: float = 0.0
    core_count: int = 0
    thread_count: int = 0
    frequency_mhz: float = 0.0
    frequency_max_mhz: float = 0.0
    frequency_min_mhz: float = 0.0
    temperature_celsius: Optional[float] = None
    load_1m: float = 0.0
    load_5m: float = 0.0
    load_15m: float = 0.0
    model_name: str = ""
    architecture: str = ""
    
    @property
    def is_healthy(self) -> bool:
        """Check if CPU is within healthy operating parameters."""
        if self.temperature_celsius and self.temperature_celsius > 90:
            return False
        if self.usage_percent > 95:
            return False
        return True


@dataclass
class MemoryMetrics:
    """Memory/RAM metrics."""
    
    total_bytes: int = 0
    used_bytes: int = 0
    available_bytes: int = 0
    cached_bytes: int = 0
    buffers_bytes: int = 0
    usage_percent: float = 0.0
    swap_total_bytes: int = 0
    swap_used_bytes: int = 0
    swap_free_bytes: int = 0
    swap_usage_percent: float = 0.0
    
    @property
    def total_gb(self) -> float:
        """Total memory in gigabytes."""
        return self.total_bytes / (1024 ** 3)
    
    @property
    def used_gb(self) -> float:
        """Used memory in gigabytes."""
        return self.used_bytes / (1024 ** 3)
    
    @property
    def available_gb(self) -> float:
        """Available memory in gigabytes."""
        return self.available_bytes / (1024 ** 3)


@dataclass
class StorageDevice:
    """Single storage device/partition metrics."""
    
    device: str = ""
    mount_point: str = ""
    fs_type: str = ""
    total_bytes: int = 0
    used_bytes: int = 0
    free_bytes: int = 0
    usage_percent: float = 0.0
    is_removable: bool = False
    is_ssd: bool = False
    model: str = ""
    serial: str = ""
    
    @property
    def total_gb(self) -> float:
        """Total storage in gigabytes."""
        return self.total_bytes / (1024 ** 3)
    
    @property
    def used_gb(self) -> float:
        """Used storage in gigabytes."""
        return self.used_bytes / (1024 ** 3)
    
    @property
    def free_gb(self) -> float:
        """Free storage in gigabytes."""
        return self.free_bytes / (1024 ** 3)


@dataclass
class StorageMetrics:
    """Aggregated storage metrics for all devices."""
    
    devices: List[StorageDevice] = field(default_factory=list)
    
    @property
    def total_bytes(self) -> int:
        """Total storage across all devices."""
        return sum(d.total_bytes for d in self.devices)
    
    @property
    def used_bytes(self) -> int:
        """Used storage across all devices."""
        return sum(d.used_bytes for d in self.devices)
    
    @property
    def free_bytes(self) -> int:
        """Free storage across all devices."""
        return sum(d.free_bytes for d in self.devices)
    
    @property
    def usage_percent(self) -> float:
        """Average usage percentage."""
        if not self.devices:
            return 0.0
        return sum(d.usage_percent for d in self.devices) / len(self.devices)


@dataclass
class PowerMetrics:
    """Power consumption and battery metrics."""
    
    cpu_power_watts: Optional[float] = None
    package_power_watts: Optional[float] = None
    dram_power_watts: Optional[float] = None
    battery_percent: Optional[float] = None
    battery_time_remaining_seconds: Optional[int] = None
    is_plugged_in: Optional[bool] = None
    power_source: str = "unknown"  # battery, ac, ups
    
    @property
    def total_power_watts(self) -> Optional[float]:
        """Total measured power consumption."""
        powers = [p for p in [self.cpu_power_watts, self.dram_power_watts] if p is not None]
        return sum(powers) if powers else None


@dataclass
class NetworkInterface:
    """Network interface information."""
    
    name: str = ""
    mac_address: str = ""
    ipv4_address: str = ""
    ipv6_address: str = ""
    is_up: bool = False
    speed_mbps: int = 0
    bytes_sent: int = 0
    bytes_recv: int = 0
    packets_sent: int = 0
    packets_recv: int = 0
    errors_in: int = 0
    errors_out: int = 0


@dataclass
class NetworkMetrics:
    """Aggregated network metrics."""
    
    interfaces: List[NetworkInterface] = field(default_factory=list)
    
    @property
    def total_bytes_sent(self) -> int:
        """Total bytes sent across all interfaces."""
        return sum(i.bytes_sent for i in self.interfaces)
    
    @property
    def total_bytes_recv(self) -> int:
        """Total bytes received across all interfaces."""
        return sum(i.bytes_recv for i in self.interfaces)


@dataclass
class HardwareSnapshot:
    """Complete hardware snapshot for a machine at a point in time."""
    
    machine: MachineInfo
    cpu: CPUMetrics
    memory: MemoryMetrics
    storage: StorageMetrics
    power: PowerMetrics
    network: NetworkMetrics
    timestamp: datetime = field(default_factory=datetime.now)
    collection_duration_ms: float = 0.0
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert snapshot to dictionary for serialization."""
        return {
            "machine": {
                "ip": self.machine.ip,
                "hostname": self.machine.hostname,
                "os_type": self.machine.os_type,
                "os_version": self.machine.os_version,
                "uptime_seconds": self.machine.uptime_seconds,
                "is_online": self.machine.is_online,
            },
            "cpu": {
                "usage_percent": self.cpu.usage_percent,
                "core_count": self.cpu.core_count,
                "thread_count": self.cpu.thread_count,
                "frequency_mhz": self.cpu.frequency_mhz,
                "temperature_celsius": self.cpu.temperature_celsius,
                "load_1m": self.cpu.load_1m,
                "load_5m": self.cpu.load_5m,
                "load_15m": self.cpu.load_15m,
                "is_healthy": self.cpu.is_healthy,
            },
            "memory": {
                "total_bytes": self.memory.total_bytes,
                "used_bytes": self.memory.used_bytes,
                "available_bytes": self.memory.available_bytes,
                "usage_percent": self.memory.usage_percent,
                "total_gb": self.memory.total_gb,
            },
            "storage": {
                "total_bytes": self.storage.total_bytes,
                "used_bytes": self.storage.used_bytes,
                "free_bytes": self.storage.free_bytes,
                "usage_percent": self.storage.usage_percent,
                "device_count": len(self.storage.devices),
            },
            "power": {
                "cpu_power_watts": self.power.cpu_power_watts,
                "battery_percent": self.power.battery_percent,
                "is_plugged_in": self.power.is_plugged_in,
            },
            "timestamp": self.timestamp.isoformat(),
            "errors": self.errors,
        }
