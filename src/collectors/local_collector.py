"""
Local Hardware Metrics Collector.

Collects hardware metrics from the local machine using psutil.
"""

import logging
import os
import platform
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import psutil

from ..core.models import (
    MachineInfo,
    CPUMetrics,
    MemoryMetrics,
    StorageDevice,
    StorageMetrics,
    PowerMetrics,
    NetworkInterface,
    NetworkMetrics,
    HardwareSnapshot,
)


logger = logging.getLogger(__name__)


class LocalCollector:
    """
    Collects hardware metrics from the local machine.
    
    Uses psutil for cross-platform hardware monitoring.
    """
    
    def __init__(self):
        self._hostname = socket.gethostname()
        self._local_ip = self._get_local_ip()
        
    def _get_local_ip(self) -> str:
        """Get the primary local IP address."""
        try:
            # Connect to a public DNS to determine local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    
    def get_machine_info(self) -> MachineInfo:
        """Get basic machine information."""
        try:
            boot_time = psutil.boot_time()
            uptime = int(time.time() - boot_time)
        except Exception:
            uptime = 0
        
        return MachineInfo(
            ip=self._local_ip,
            hostname=self._hostname,
            os_type=platform.system(),
            os_version=platform.release(),
            uptime_seconds=uptime,
            last_seen=datetime.now(),
            is_online=True,
            collection_method="local",
        )
    
    def get_cpu_metrics(self) -> CPUMetrics:
        """Get CPU metrics."""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
        except Exception:
            cpu_percent = 0.0
        
        try:
            cpu_freq = psutil.cpu_freq()
            freq_current = cpu_freq.current if cpu_freq else 0.0
            freq_max = cpu_freq.max if cpu_freq else 0.0
            freq_min = cpu_freq.min if cpu_freq else 0.0
        except Exception:
            freq_current = freq_max = freq_min = 0.0
        
        try:
            load_avg = os.getloadavg()
            load_1m, load_5m, load_15m = load_avg
        except (AttributeError, OSError):
            # Windows doesn't have getloadavg
            load_1m = load_5m = load_15m = 0.0
        
        # Try to get CPU temperature
        temperature = self._get_cpu_temperature()
        
        # Get CPU model name
        model_name = self._get_cpu_model()
        
        return CPUMetrics(
            usage_percent=cpu_percent,
            core_count=psutil.cpu_count(logical=False) or 0,
            thread_count=psutil.cpu_count(logical=True) or 0,
            frequency_mhz=freq_current,
            frequency_max_mhz=freq_max,
            frequency_min_mhz=freq_min,
            temperature_celsius=temperature,
            load_1m=load_1m,
            load_5m=load_5m,
            load_15m=load_15m,
            model_name=model_name,
            architecture=platform.machine(),
        )
    
    def _get_cpu_temperature(self) -> Optional[float]:
        """Attempt to get CPU temperature."""
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                # Try common sensor names
                for name in ["coretemp", "cpu_thermal", "k10temp", "cpu-thermal"]:
                    if name in temps:
                        readings = temps[name]
                        if readings:
                            return readings[0].current
                # Fall back to first available sensor
                for sensor_list in temps.values():
                    if sensor_list:
                        return sensor_list[0].current
        except (AttributeError, Exception):
            pass
        return None
    
    def _get_cpu_model(self) -> str:
        """Get CPU model name."""
        try:
            if platform.system() == "Darwin":
                import subprocess
                result = subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    capture_output=True,
                    text=True,
                )
                return result.stdout.strip()
            elif platform.system() == "Linux":
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if "model name" in line:
                            return line.split(":")[1].strip()
            elif platform.system() == "Windows":
                import subprocess
                result = subprocess.run(
                    ["wmic", "cpu", "get", "name"],
                    capture_output=True,
                    text=True,
                )
                lines = result.stdout.strip().split("\n")
                if len(lines) > 1:
                    return lines[1].strip()
        except Exception:
            pass
        return platform.processor()
    
    def get_memory_metrics(self) -> MemoryMetrics:
        """Get memory/RAM metrics."""
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        return MemoryMetrics(
            total_bytes=mem.total,
            used_bytes=mem.used,
            available_bytes=mem.available,
            cached_bytes=getattr(mem, "cached", 0),
            buffers_bytes=getattr(mem, "buffers", 0),
            usage_percent=mem.percent,
            swap_total_bytes=swap.total,
            swap_used_bytes=swap.used,
            swap_free_bytes=swap.free,
            swap_usage_percent=swap.percent,
        )
    
    def get_storage_metrics(self) -> StorageMetrics:
        """Get storage metrics for all mounted filesystems."""
        devices = []
        
        for partition in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                
                # Try to determine if SSD
                is_ssd = self._is_ssd(partition.device)
                
                device = StorageDevice(
                    device=partition.device,
                    mount_point=partition.mountpoint,
                    fs_type=partition.fstype,
                    total_bytes=usage.total,
                    used_bytes=usage.used,
                    free_bytes=usage.free,
                    usage_percent=usage.percent,
                    is_removable="removable" in partition.opts.lower() if partition.opts else False,
                    is_ssd=is_ssd,
                )
                devices.append(device)
            except (PermissionError, OSError) as e:
                logger.debug(f"Could not access {partition.mountpoint}: {e}")
        
        return StorageMetrics(devices=devices)
    
    def _is_ssd(self, device: str) -> bool:
        """Attempt to determine if a device is an SSD."""
        try:
            if platform.system() == "Linux":
                # Check rotational flag
                device_name = Path(device).name
                if device_name.startswith("sd") or device_name.startswith("nvme"):
                    # For NVMe, always SSD
                    if device_name.startswith("nvme"):
                        return True
                    # Check rotational
                    base_device = device_name.rstrip("0123456789")
                    rotational_path = Path(f"/sys/block/{base_device}/queue/rotational")
                    if rotational_path.exists():
                        return rotational_path.read_text().strip() == "0"
            elif platform.system() == "Darwin":
                # macOS: assume SSD unless otherwise known
                return True
        except Exception:
            pass
        return False
    
    def get_power_metrics(self) -> PowerMetrics:
        """Get power consumption and battery metrics."""
        battery = None
        try:
            battery = psutil.sensors_battery()
        except Exception:
            pass
        
        cpu_power = self._get_cpu_power()
        
        if battery:
            return PowerMetrics(
                cpu_power_watts=cpu_power,
                battery_percent=battery.percent,
                battery_time_remaining_seconds=battery.secsleft if battery.secsleft > 0 else None,
                is_plugged_in=battery.power_plugged,
                power_source="ac" if battery.power_plugged else "battery",
            )
        else:
            return PowerMetrics(
                cpu_power_watts=cpu_power,
                battery_percent=None,
                is_plugged_in=None,
                power_source="ac",  # Assume desktop/server
            )
    
    def _get_cpu_power(self) -> Optional[float]:
        """
        Attempt to get CPU power consumption using Intel RAPL.
        
        Note: Requires root/admin privileges on most systems.
        """
        try:
            if platform.system() == "Linux":
                # Try Intel RAPL interface
                rapl_path = Path("/sys/class/powercap/intel-rapl")
                if rapl_path.exists():
                    # Read package power
                    for domain in rapl_path.iterdir():
                        if domain.name.startswith("intel-rapl:"):
                            energy_file = domain / "energy_uj"
                            if energy_file.exists():
                                # Read two samples to calculate power
                                energy1 = int(energy_file.read_text())
                                time.sleep(0.1)
                                energy2 = int(energy_file.read_text())
                                power_uw = (energy2 - energy1) / 0.1
                                return power_uw / 1_000_000  # Convert to watts
        except (PermissionError, Exception):
            pass
        return None
    
    def get_network_metrics(self) -> NetworkMetrics:
        """Get network interface metrics."""
        interfaces = []
        
        try:
            stats = psutil.net_io_counters(pernic=True)
            addrs = psutil.net_if_addrs()
            if_stats = psutil.net_if_stats()
        except Exception as e:
            logger.error(f"Error getting network info: {e}")
            return NetworkMetrics(interfaces=[])
        
        for name, io in stats.items():
            # Skip loopback
            if name.lower().startswith("lo"):
                continue
            
            iface = NetworkInterface(
                name=name,
                bytes_sent=io.bytes_sent,
                bytes_recv=io.bytes_recv,
                packets_sent=io.packets_sent,
                packets_recv=io.packets_recv,
                errors_in=io.errin,
                errors_out=io.errout,
            )
            
            # Add addresses
            if name in addrs:
                for addr in addrs[name]:
                    if addr.family.name == "AF_INET":
                        iface.ipv4_address = addr.address
                    elif addr.family.name == "AF_INET6":
                        iface.ipv6_address = addr.address
                    elif addr.family.name == "AF_LINK" or addr.family.name == "AF_PACKET":
                        iface.mac_address = addr.address
            
            # Add interface stats
            if name in if_stats:
                iface.is_up = if_stats[name].isup
                iface.speed_mbps = if_stats[name].speed
            
            interfaces.append(iface)
        
        return NetworkMetrics(interfaces=interfaces)
    
    def collect_all(self) -> HardwareSnapshot:
        """Collect all hardware metrics and return a complete snapshot."""
        start_time = time.time()
        errors = []
        
        # Collect each metric type with error handling
        try:
            machine = self.get_machine_info()
        except Exception as e:
            errors.append(f"Machine info: {e}")
            machine = MachineInfo(ip=self._local_ip)
        
        try:
            cpu = self.get_cpu_metrics()
        except Exception as e:
            errors.append(f"CPU metrics: {e}")
            cpu = CPUMetrics()
        
        try:
            memory = self.get_memory_metrics()
        except Exception as e:
            errors.append(f"Memory metrics: {e}")
            memory = MemoryMetrics()
        
        try:
            storage = self.get_storage_metrics()
        except Exception as e:
            errors.append(f"Storage metrics: {e}")
            storage = StorageMetrics()
        
        try:
            power = self.get_power_metrics()
        except Exception as e:
            errors.append(f"Power metrics: {e}")
            power = PowerMetrics()
        
        try:
            network = self.get_network_metrics()
        except Exception as e:
            errors.append(f"Network metrics: {e}")
            network = NetworkMetrics()
        
        duration_ms = (time.time() - start_time) * 1000
        
        return HardwareSnapshot(
            machine=machine,
            cpu=cpu,
            memory=memory,
            storage=storage,
            power=power,
            network=network,
            timestamp=datetime.now(),
            collection_duration_ms=duration_ms,
            errors=errors,
        )


# Convenience function for quick local metrics
def get_local_snapshot() -> HardwareSnapshot:
    """Get a hardware snapshot of the local machine."""
    collector = LocalCollector()
    return collector.collect_all()
