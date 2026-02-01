#!/usr/bin/env python3
"""Test vendor lookup."""
import sys
sys.path.insert(0, '/app')

from src.core.hostname_resolver import get_vendor_from_mac

macs = [
    '98:E7:43:20:F0:44',  # Dell
    'BC:24:11:B9:AC:38',  # Proxmox
    '84:2F:57:24:50:B6',  # Apple
    '74:56:3C:8D:FD:F2',  # GIGA-BYTE
]

print("Testing vendor lookup from MAC addresses:")
for mac in macs:
    vendor = get_vendor_from_mac(mac)
    print(f"  {mac} -> {vendor}")
