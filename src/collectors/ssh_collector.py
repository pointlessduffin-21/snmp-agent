"""
SSH Collector for Remote Linux Machines.

Collects hardware metrics from Linux machines via SSH commands.
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Optional, Tuple

import paramiko

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


class SSHCollector:
    """
    Collects hardware metrics from Linux machines via SSH.
    
    Uses paramiko to execute system commands and parse output.
    """
    
    def __init__(
        self,
        username: str = "root",
        password: Optional[str] = None,
        key_path: Optional[str] = None,
        port: int = 22,
        timeout: float = 10.0,
    ):
        self.username = username
        self.password = password
        self.key_path = key_path
        self.port = port
        self.timeout = timeout
    
    def _get_ssh_client(self, ip: str) -> paramiko.SSHClient:
        """Create and configure SSH client."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        connect_kwargs = {
            "hostname": ip,
            "port": self.port,
            "username": self.username,
            "timeout": self.timeout,
        }
        
        if self.key_path:
            connect_kwargs["key_filename"] = self.key_path
        elif self.password:
            connect_kwargs["password"] = self.password
        
        client.connect(**connect_kwargs)
        return client
    
    def _exec_command(self, client: paramiko.SSHClient, command: str) -> Tuple[str, str]:
        """Execute a command and return stdout and stderr."""
        stdin, stdout, stderr = client.exec_command(command, timeout=self.timeout)
        return stdout.read().decode("utf-8").strip(), stderr.read().decode("utf-8").strip()
    
    def check_ssh_available(self, ip: str) -> bool:
        """Check if SSH is available on a host."""
        try:
            client = self._get_ssh_client(ip)
            client.close()
            return True
        except Exception as e:
            logger.debug(f"SSH not available on {ip}: {e}")
            return False
    
    def get_machine_info(self, ip: str, client: paramiko.SSHClient) -> MachineInfo:
        """Get machine information via SSH."""
        hostname = "unknown"
        os_type = "Linux"
        os_version = ""
        uptime = 0
        
        try:
            out, _ = self._exec_command(client, "hostname")
            hostname = out
        except Exception:
            pass
        
        try:
            out, _ = self._exec_command(client, "uname -r")
            os_version = out
        except Exception:
            pass
        
        try:
            # Get uptime in seconds
            out, _ = self._exec_command(client, "cat /proc/uptime")
            uptime = int(float(out.split()[0]))
        except Exception:
            pass
        
        return MachineInfo(
            ip=ip,
            hostname=hostname,
            os_type=os_type,
            os_version=os_version,
            uptime_seconds=uptime,
            last_seen=datetime.now(),
            is_online=True,
            collection_method="ssh",
        )
    
    def get_cpu_metrics(self, client: paramiko.SSHClient) -> CPUMetrics:
        """Get CPU metrics via SSH."""
        usage = 0.0
        core_count = 0
        thread_count = 0
        frequency = 0.0
        freq_max = 0.0
        load_1m = load_5m = load_15m = 0.0
        model_name = ""
        temp = None
        
        # Get CPU info from /proc/cpuinfo
        try:
            out, _ = self._exec_command(client, "cat /proc/cpuinfo")
            processors = out.count("processor")
            thread_count = processors
            
            # Count physical cores
            core_ids = set()
            for line in out.split("\n"):
                if "core id" in line:
                    core_ids.add(line.split(":")[1].strip())
                if "model name" in line and not model_name:
                    model_name = line.split(":")[1].strip()
                if "cpu MHz" in line and not frequency:
                    frequency = float(line.split(":")[1].strip())
            
            core_count = len(core_ids) if core_ids else thread_count
        except Exception as e:
            logger.debug(f"Error getting CPU info: {e}")
        
        # Get load averages
        try:
            out, _ = self._exec_command(client, "cat /proc/loadavg")
            parts = out.split()
            load_1m = float(parts[0])
            load_5m = float(parts[1])
            load_15m = float(parts[2])
        except Exception:
            pass
        
        # Get CPU usage from /proc/stat
        try:
            out1, _ = self._exec_command(client, "head -1 /proc/stat")
            import time
            time.sleep(0.1)
            out2, _ = self._exec_command(client, "head -1 /proc/stat")
            
            def parse_stat(line):
                parts = line.split()[1:]
                return [int(x) for x in parts[:7]]
            
            stat1 = parse_stat(out1)
            stat2 = parse_stat(out2)
            
            delta = [stat2[i] - stat1[i] for i in range(len(stat1))]
            idle = delta[3]
            total = sum(delta)
            usage = 100.0 * (1 - idle / total) if total else 0.0
        except Exception:
            pass
        
        # Get max frequency
        try:
            out, _ = self._exec_command(
                client,
                "cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq 2>/dev/null"
            )
            freq_max = float(out) / 1000  # Convert kHz to MHz
        except Exception:
            freq_max = frequency
        
        # Try to get temperature
        try:
            out, _ = self._exec_command(
                client,
                "cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null"
            )
            temp = float(out) / 1000  # Convert millidegrees to degrees
        except Exception:
            pass
        
        return CPUMetrics(
            usage_percent=usage,
            core_count=core_count,
            thread_count=thread_count,
            frequency_mhz=frequency,
            frequency_max_mhz=freq_max,
            temperature_celsius=temp,
            load_1m=load_1m,
            load_5m=load_5m,
            load_15m=load_15m,
            model_name=model_name,
        )
    
    def get_memory_metrics(self, client: paramiko.SSHClient) -> MemoryMetrics:
        """Get memory metrics via SSH."""
        mem = {}
        
        try:
            out, _ = self._exec_command(client, "cat /proc/meminfo")
            for line in out.split("\n"):
                if ":" in line:
                    key, value = line.split(":")
                    # Remove 'kB' and convert to bytes
                    num = int(re.findall(r"\d+", value)[0]) * 1024
                    mem[key.strip()] = num
        except Exception as e:
            logger.debug(f"Error getting memory info: {e}")
            return MemoryMetrics()
        
        total = mem.get("MemTotal", 0)
        free = mem.get("MemFree", 0)
        available = mem.get("MemAvailable", free)
        cached = mem.get("Cached", 0)
        buffers = mem.get("Buffers", 0)
        used = total - available
        
        swap_total = mem.get("SwapTotal", 0)
        swap_free = mem.get("SwapFree", 0)
        swap_used = swap_total - swap_free
        
        return MemoryMetrics(
            total_bytes=total,
            used_bytes=used,
            available_bytes=available,
            cached_bytes=cached,
            buffers_bytes=buffers,
            usage_percent=(used / total * 100) if total else 0.0,
            swap_total_bytes=swap_total,
            swap_used_bytes=swap_used,
            swap_free_bytes=swap_free,
            swap_usage_percent=(swap_used / swap_total * 100) if swap_total else 0.0,
        )
    
    def get_storage_metrics(self, client: paramiko.SSHClient) -> StorageMetrics:
        """Get storage metrics via SSH."""
        devices = []
        
        try:
            # Use df command for filesystem info
            out, _ = self._exec_command(
                client,
                "df -B1 -T -x tmpfs -x devtmpfs -x squashfs 2>/dev/null"
            )
            
            for line in out.split("\n")[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 7:
                    device = StorageDevice(
                        device=parts[0],
                        fs_type=parts[1],
                        total_bytes=int(parts[2]),
                        used_bytes=int(parts[3]),
                        free_bytes=int(parts[4]),
                        usage_percent=float(parts[5].rstrip("%")),
                        mount_point=parts[6],
                    )
                    
                    # Check if SSD
                    dev_name = parts[0].split("/")[-1].rstrip("0123456789")
                    try:
                        rot_out, _ = self._exec_command(
                            client,
                            f"cat /sys/block/{dev_name}/queue/rotational 2>/dev/null"
                        )
                        device.is_ssd = rot_out.strip() == "0"
                    except Exception:
                        pass
                    
                    devices.append(device)
        except Exception as e:
            logger.debug(f"Error getting storage info: {e}")
        
        return StorageMetrics(devices=devices)
    
    def get_power_metrics(self, client: paramiko.SSHClient) -> PowerMetrics:
        """Get power metrics via SSH."""
        cpu_power = None
        battery_percent = None
        is_plugged = None
        
        # Try Intel RAPL
        try:
            out, _ = self._exec_command(
                client,
                "cat /sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj 2>/dev/null"
            )
            energy1 = int(out)
            import time
            time.sleep(0.1)
            out, _ = self._exec_command(
                client,
                "cat /sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj 2>/dev/null"
            )
            energy2 = int(out)
            cpu_power = (energy2 - energy1) / 100000  # Convert to watts
        except Exception:
            pass
        
        # Try battery info
        try:
            out, _ = self._exec_command(
                client,
                "cat /sys/class/power_supply/BAT0/capacity 2>/dev/null"
            )
            battery_percent = float(out)
            
            out, _ = self._exec_command(
                client,
                "cat /sys/class/power_supply/BAT0/status 2>/dev/null"
            )
            is_plugged = out.strip().lower() in ["charging", "full"]
        except Exception:
            pass
        
        return PowerMetrics(
            cpu_power_watts=cpu_power,
            battery_percent=battery_percent,
            is_plugged_in=is_plugged,
            power_source="battery" if battery_percent and not is_plugged else "ac",
        )
    
    def get_network_metrics(self, client: paramiko.SSHClient) -> NetworkMetrics:
        """Get network metrics via SSH."""
        interfaces = []
        
        try:
            out, _ = self._exec_command(client, "cat /proc/net/dev")
            
            for line in out.split("\n")[2:]:  # Skip header lines
                if ":" not in line:
                    continue
                
                parts = line.split(":")
                name = parts[0].strip()
                
                if name == "lo":
                    continue
                
                stats = parts[1].split()
                iface = NetworkInterface(
                    name=name,
                    bytes_recv=int(stats[0]),
                    packets_recv=int(stats[1]),
                    errors_in=int(stats[2]),
                    bytes_sent=int(stats[8]),
                    packets_sent=int(stats[9]),
                    errors_out=int(stats[10]),
                    is_up=True,
                )
                
                # Get IP address
                try:
                    ip_out, _ = self._exec_command(
                        client,
                        f"ip -4 addr show {name} 2>/dev/null | grep inet"
                    )
                    match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", ip_out)
                    if match:
                        iface.ipv4_address = match.group(1)
                except Exception:
                    pass
                
                interfaces.append(iface)
        except Exception as e:
            logger.debug(f"Error getting network info: {e}")
        
        return NetworkMetrics(interfaces=interfaces)
    
    def collect_all(self, ip: str) -> Optional[HardwareSnapshot]:
        """Collect all metrics from a remote Linux machine via SSH."""
        import time
        start_time = time.time()
        errors = []
        
        try:
            client = self._get_ssh_client(ip)
        except Exception as e:
            logger.warning(f"Failed to connect to {ip} via SSH: {e}")
            return None
        
        try:
            machine = self.get_machine_info(ip, client)
            
            try:
                cpu = self.get_cpu_metrics(client)
            except Exception as e:
                errors.append(f"CPU: {e}")
                cpu = CPUMetrics()
            
            try:
                memory = self.get_memory_metrics(client)
            except Exception as e:
                errors.append(f"Memory: {e}")
                memory = MemoryMetrics()
            
            try:
                storage = self.get_storage_metrics(client)
            except Exception as e:
                errors.append(f"Storage: {e}")
                storage = StorageMetrics()
            
            try:
                power = self.get_power_metrics(client)
            except Exception as e:
                errors.append(f"Power: {e}")
                power = PowerMetrics()
            
            try:
                network = self.get_network_metrics(client)
            except Exception as e:
                errors.append(f"Network: {e}")
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
        finally:
            client.close()
