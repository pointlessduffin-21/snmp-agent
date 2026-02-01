#!/usr/bin/env python3
"""
Test script for the SNMP Agent.

Tests local collection and displays results.
"""

import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.collectors.local_collector import LocalCollector, get_local_snapshot


def main():
    print("=" * 60)
    print("SNMP Agent - Local Hardware Metrics Test")
    print("=" * 60)
    
    # Get local snapshot
    print("\nCollecting local hardware metrics...")
    snapshot = get_local_snapshot()
    
    # Machine info
    m = snapshot.machine
    print(f"\n--- Machine Info ---")
    print(f"Hostname: {m.hostname}")
    print(f"IP Address: {m.ip}")
    print(f"OS: {m.os_type} {m.os_version}")
    print(f"Uptime: {m.uptime_seconds // 3600}h {(m.uptime_seconds % 3600) // 60}m")
    
    # CPU info
    c = snapshot.cpu
    print(f"\n--- CPU Info ---")
    print(f"Model: {c.model_name}")
    print(f"Architecture: {c.architecture}")
    print(f"Cores: {c.core_count} physical, {c.thread_count} logical")
    print(f"Frequency: {c.frequency_mhz:.0f} MHz (max: {c.frequency_max_mhz:.0f} MHz)")
    print(f"Current Usage: {c.usage_percent:.1f}%")
    print(f"Load Average: {c.load_1m:.2f} / {c.load_5m:.2f} / {c.load_15m:.2f}")
    if c.temperature_celsius:
        print(f"Temperature: {c.temperature_celsius:.1f}°C")
    print(f"Health Status: {'Healthy' if c.is_healthy else 'Warning'}")
    
    # Memory info
    mem = snapshot.memory
    print(f"\n--- Memory Info ---")
    print(f"Total RAM: {mem.total_gb:.2f} GB")
    print(f"Used RAM: {mem.used_gb:.2f} GB ({mem.usage_percent:.1f}%)")
    print(f"Available RAM: {mem.available_gb:.2f} GB")
    if mem.swap_total_bytes > 0:
        swap_total_gb = mem.swap_total_bytes / (1024**3)
        swap_used_gb = mem.swap_used_bytes / (1024**3)
        print(f"Swap: {swap_used_gb:.2f} / {swap_total_gb:.2f} GB ({mem.swap_usage_percent:.1f}%)")
    
    # Storage info
    print(f"\n--- Storage Info ---")
    for device in snapshot.storage.devices:
        print(f"\n  {device.device}")
        print(f"    Mount: {device.mount_point}")
        print(f"    Type: {device.fs_type} {'(SSD)' if device.is_ssd else '(HDD)' if device.fs_type else ''}")
        print(f"    Total: {device.total_gb:.2f} GB")
        print(f"    Used: {device.used_gb:.2f} GB ({device.usage_percent:.1f}%)")
        print(f"    Free: {device.free_gb:.2f} GB")
    
    if snapshot.storage.devices:
        total = snapshot.storage.total_bytes / (1024**3)
        used = snapshot.storage.used_bytes / (1024**3)
        print(f"\n  Total Storage: {used:.2f} / {total:.2f} GB")
    
    # Power info
    pwr = snapshot.power
    print(f"\n--- Power Info ---")
    if pwr.cpu_power_watts:
        print(f"CPU Power: {pwr.cpu_power_watts:.1f} W")
    else:
        print("CPU Power: Not available (requires RAPL support)")
    
    if pwr.battery_percent is not None:
        print(f"Battery: {pwr.battery_percent:.0f}%")
        print(f"Power Source: {pwr.power_source}")
        if pwr.battery_time_remaining_seconds:
            hours = pwr.battery_time_remaining_seconds // 3600
            mins = (pwr.battery_time_remaining_seconds % 3600) // 60
            print(f"Time Remaining: {hours}h {mins}m")
    else:
        print("Battery: Not present (desktop/server)")
    
    # Network info
    print(f"\n--- Network Interfaces ---")
    for iface in snapshot.network.interfaces:
        if iface.ipv4_address or iface.bytes_recv > 0:
            print(f"\n  {iface.name}")
            if iface.ipv4_address:
                print(f"    IPv4: {iface.ipv4_address}")
            if iface.mac_address:
                print(f"    MAC: {iface.mac_address}")
            if iface.speed_mbps:
                print(f"    Speed: {iface.speed_mbps} Mbps")
            sent_mb = iface.bytes_sent / (1024**2)
            recv_mb = iface.bytes_recv / (1024**2)
            print(f"    Traffic: ↑{sent_mb:.1f} MB / ↓{recv_mb:.1f} MB")
    
    # Collection stats
    print(f"\n--- Collection Stats ---")
    print(f"Collection Time: {snapshot.collection_duration_ms:.1f} ms")
    print(f"Timestamp: {snapshot.timestamp.isoformat()}")
    if snapshot.errors:
        print(f"Errors: {len(snapshot.errors)}")
        for err in snapshot.errors:
            print(f"  - {err}")
    
    # JSON output option
    print(f"\n--- JSON Summary ---")
    data = snapshot.to_dict()
    print(json.dumps(data, indent=2, default=str))
    
    print("\n" + "=" * 60)
    print("Test completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
