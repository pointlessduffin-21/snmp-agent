"""
Hostname Resolution Utilities.

Provides functions to resolve hostnames from IP addresses using:
- Reverse DNS lookup
- NetBIOS name resolution (Windows)
- mDNS/Bonjour discovery
"""

import socket
import logging
import subprocess
import re
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ResolvedNames:
    """All resolved names for a device."""
    dns_name: str = ""
    mdns_name: str = ""
    netbios_name: str = ""
    best_name: str = ""


def resolve_hostname(ip: str) -> str:
    """
    Resolve hostname from IP address using multiple methods.
    
    Args:
        ip: IP address to resolve
        
    Returns:
        Hostname if found, otherwise returns the IP address
    """
    # Try reverse DNS first
    try:
        hostname, _, _ = socket.gethostbyaddr(ip)
        if hostname and hostname != ip:
            # Remove domain suffix and .local for cleaner display
            hostname = hostname.replace('.local', '').split('.')[0]
            logger.debug(f"Resolved {ip} -> {hostname} via DNS")
            return hostname
    except (socket.herror, socket.gaierror, OSError) as e:
        logger.debug(f"DNS lookup failed for {ip}: {e}")
    
    # Return IP if all methods fail
    return ip


def resolve_all_names(ip: str) -> ResolvedNames:
    """
    Resolve all possible names for an IP address.
    
    Args:
        ip: IP address to resolve
        
    Returns:
        ResolvedNames with all discovered names
    """
    names = ResolvedNames()
    
    # Try reverse DNS
    try:
        hostname, aliases, _ = socket.gethostbyaddr(ip)
        if hostname and hostname != ip:
            full_name = hostname
            # Check if it's an mDNS name
            if '.local' in hostname.lower():
                names.mdns_name = hostname.replace('.local', '').split('.')[0]
            else:
                names.dns_name = hostname.split('.')[0]
    except (socket.herror, socket.gaierror, OSError):
        pass
    
    # Try mDNS query (using dns-sd on macOS)
    mdns = resolve_mdns(ip)
    if mdns:
        names.mdns_name = mdns
    
    # Try NetBIOS query
    netbios = resolve_netbios(ip)
    if netbios:
        names.netbios_name = netbios
    
    # Determine best name: prefer NetBIOS > mDNS > DNS
    if names.netbios_name:
        names.best_name = names.netbios_name
    elif names.mdns_name:
        names.best_name = names.mdns_name
    elif names.dns_name:
        names.best_name = names.dns_name
    else:
        names.best_name = ip
    
    return names


def resolve_mdns(ip: str) -> Optional[str]:
    """
    Resolve mDNS/Bonjour name for an IP address.
    
    Args:
        ip: IP address
        
    Returns:
        mDNS hostname if found
    """
    try:
        # Try using dns-sd on macOS or avahi-resolve on Linux
        import platform
        if platform.system() == "Darwin":
            # macOS: use dns-sd
            result = subprocess.run(
                ['dns-sd', '-G', 'v4', ip],
                capture_output=True,
                text=True,
                timeout=2
            )
            # Output format includes hostname
            for line in result.stdout.split('\n'):
                if '.local' in line.lower():
                    match = re.search(r'(\S+\.local)', line, re.I)
                    if match:
                        return match.group(1).replace('.local', '')
        else:
            # Linux: try avahi-resolve
            try:
                result = subprocess.run(
                    ['avahi-resolve', '-a', ip],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0 and result.stdout:
                    parts = result.stdout.strip().split()
                    if len(parts) >= 2:
                        return parts[1].replace('.local', '')
            except FileNotFoundError:
                pass
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.debug(f"mDNS lookup failed for {ip}: {e}")
    
    return None


def resolve_netbios(ip: str) -> Optional[str]:
    """
    Resolve NetBIOS/SMB name for an IP address.
    
    Args:
        ip: IP address
        
    Returns:
        NetBIOS name if found
    """
    try:
        # Try using nmblookup (Samba) or nbtscan
        result = subprocess.run(
            ['nmblookup', '-A', ip],
            capture_output=True,
            text=True,
            timeout=3
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                # Look for <00> which is the workstation service name
                if '<00>' in line and 'GROUP' not in line:
                    match = re.search(r'^\s*(\S+)\s+<00>', line)
                    if match:
                        return match.group(1)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug(f"NetBIOS lookup failed for {ip}: {e}")
    
    # Fallback: try smbclient
    try:
        result = subprocess.run(
            ['smbclient', '-L', ip, '-N', '-g'],
            capture_output=True,
            text=True,
            timeout=3
        )
        for line in result.stdout.split('\n'):
            if line.startswith('Workgroup|'):
                parts = line.split('|')
                if len(parts) >= 2:
                    return parts[1]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    return None


def get_mac_address(ip: str) -> Optional[str]:
    """
    Get MAC address for an IP from ARP table.
    
    Args:
        ip: IP address
        
    Returns:
        MAC address if found
    """
    try:
        import subprocess
        result = subprocess.run(
            ['arp', '-n', ip],
            capture_output=True,
            text=True,
            timeout=1
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if ip in line:
                    parts = line.split()
                    for part in parts:
                        if ':' in part and len(part) == 17:  # MAC format
                            return part.upper()
    except Exception as e:
        logger.debug(f"MAC lookup failed for {ip}: {e}")
    
    return None


# Common MAC OUI prefixes -> Vendor mapping (top vendors)
OUI_VENDORS = {
    # Virtual/Hypervisor
    "00:50:56": "VMware",
    "00:0C:29": "VMware",
    "00:15:5D": "Microsoft Hyper-V",
    "08:00:27": "Oracle VirtualBox",
    "52:54:00": "QEMU/KVM",
    "BC:24:11": "Proxmox VE",
    "FE:54:00": "QEMU/KVM",
    
    # Apple
    "00:1E:C2": "Apple",
    "00:03:93": "Apple",
    "F8:1E:DF": "Apple",
    "14:7D:DA": "Apple",
    "00:1F:F3": "Apple",
    "AC:DE:48": "Apple",
    "28:CF:DA": "Apple",
    "A8:66:7F": "Apple",
    "DC:A9:04": "Apple",
    "84:2F:57": "Apple",
    "3C:06:30": "Apple",
    "F0:18:98": "Apple",
    "64:A3:CB": "Apple",
    "AC:BC:32": "Apple",
    "70:CD:60": "Apple",
    "98:E7:43": "Dell Inc.",
    "A4:83:E7": "Apple",
    "78:4F:43": "Apple",
    "8C:85:90": "Apple",
    "40:98:AD": "Apple",
    "B8:E8:56": "Apple",
    "6C:40:08": "Apple",
    
    # Cloud/Web
    "00:1A:11": "Google",
    "42:01:0A": "Google Cloud",
    
    # Networking
    "00:17:88": "Philips",
    "00:1C:DF": "Belkin",
    "00:14:BF": "Linksys",
    "00:1D:7E": "Cisco",
    "00:21:55": "Cisco",
    "00:26:99": "Cisco",
    "00:22:55": "Cisco",
    "34:0A:33": "D-Link International",
    
    # Dell
    "00:1E:68": "Quanta",
    "00:1A:A0": "Dell",
    "00:15:C5": "Dell",
    "00:21:9B": "Dell",
    "18:03:73": "Dell",
    "00:0D:56": "Dell",
    "B0:83:FE": "Dell",
    "00:13:72": "Dell",
    "00:1E:4F": "Dell",
    "78:2B:CB": "Dell",
    
    # ASUS / Gigabyte / Motherboards
    "00:0E:A6": "ASUSTeK",
    "00:11:D8": "ASUSTeK",
    "00:1F:C6": "ASUSTeK",
    "BC:AE:C5": "ASUSTeK",
    "54:04:A6": "ASUSTeK",
    "00:22:15": "ASUSTeK",
    "00:24:8C": "ASUSTeK",
    "00:17:31": "ASUSTeK",
    "00:1D:60": "ASUSTeK",
    "00:26:18": "ASUSTeK",
    "04:D9:F5": "ASUSTeK",
    "74:56:3C": "GIGA-BYTE Technology",
    "E0:D5:5E": "GIGA-BYTE Technology",
    "1C:83:41": "GIGA-BYTE Technology",
    "50:E5:49": "GIGA-BYTE Technology",
    
    # Intel
    "00:21:5E": "IBM",
    "00:22:FA": "Intel",
    "00:1B:21": "Intel",
    "00:1F:3B": "Intel",
    "00:15:17": "Intel",
    "00:03:47": "Intel",
    "E4:1D:2D": "Intel",
    "00:1E:67": "Intel",
    "70:85:C2": "Intel",
    "DC:53:60": "Intel",
    
    # Huawei
    "AC:E2:D3": "Huawei",
    "00:E0:FC": "Huawei",
    "78:D7:52": "Huawei",
    "48:46:FB": "Huawei",
    "88:9F:FA": "Huawei",
    "34:29:8F": "Huawei",
    "00:0F:E2": "Huawei",
    "00:25:9E": "Huawei",
    "00:1E:10": "Huawei",
    "20:08:ED": "Huawei",
    "FC:48:EF": "Huawei",
    "00:66:4B": "Huawei",
    "28:6E:D4": "Huawei",
    "00:25:68": "Huawei",
    
    # Realtek/Ralink
    "00:0C:43": "Ralink",
    "00:17:A4": "Ralink",
    "00:E0:4C": "Realtek",
    "00:60:52": "Realtek",
    "00:BD:82": "Realtek",
    "00:0A:CD": "Realtek",
    "50:3E:AA": "Realtek",
    
    # D-Link
    "28:F0:76": "D-Link",
    "00:1E:58": "D-Link",
    "00:17:9A": "D-Link",
    "1C:AF:F7": "D-Link",
    "90:94:E4": "D-Link",
    "00:22:B0": "D-Link",
    "00:1C:F0": "D-Link",
    "1C:7E:E5": "D-Link",
    "34:08:04": "D-Link",
    "C4:A8:1D": "D-Link",
    "00:24:01": "D-Link",
    "00:15:E9": "D-Link",
    "00:55:DA": "D-Link",
    "C8:D3:A3": "D-Link",
    "28:10:7B": "D-Link",
    "00:1B:11": "D-Link",
    "00:26:5A": "D-Link",
    "00:05:5D": "D-Link",
    
    # Raspberry Pi
    "B8:27:EB": "Raspberry Pi",
    "DC:A6:32": "Raspberry Pi",
    "E4:5F:01": "Raspberry Pi",
    "2C:CF:67": "Raspberry Pi",
    
    # Others
    "00:20:91": "J & M",
    "00:1F:1F": "Edimax",
    "00:00:B4": "Edimax",
    "74:DA:38": "Edimax",
    "80:1F:02": "Edimax",
    "00:0E:2E": "Edimax",
    
    # TP-Link
    "80:E8:6F": "TP-Link",
    "30:B5:C2": "TP-Link",
    "1C:3B:F3": "TP-Link",
    "50:C7:BF": "TP-Link",
    "14:CC:20": "TP-Link",
    "B0:BE:76": "TP-Link",
    "00:27:19": "TP-Link",
    "90:F6:52": "TP-Link",
    "94:0C:6D": "TP-Link",
    "D8:07:B6": "TP-Link",
    "E8:DE:27": "TP-Link",
    "18:D6:C7": "TP-Link",
    "A0:F3:C1": "TP-Link",
    
    # Netgear
    "E4:F4:C6": "Netgear",
    "00:14:6C": "Netgear",
    "00:1E:2A": "Netgear",
    "00:1F:33": "Netgear",
    "C0:3F:0E": "Netgear",
    "20:4E:7F": "Netgear",
    "A0:21:B7": "Netgear",
    "00:24:B2": "Netgear",
    "84:1B:5E": "Netgear",
    "E0:91:F5": "Netgear",
    "9C:3D:CF": "Netgear",
    "CC:40:D0": "Netgear",
    "20:E5:2A": "Netgear",
    "00:26:F2": "Netgear",
    "6C:B0:CE": "Netgear",
    "B0:7F:B9": "Netgear",
    "30:46:9A": "Netgear",
    "10:0D:7F": "Netgear",
    "44:94:FC": "Netgear",
    "C4:04:15": "Netgear",
    "00:8E:F2": "Netgear",
    "00:1B:2F": "Netgear",
    
    # Microsoft
    "00:15:5D": "Microsoft (Hyper-V)",
    "00:03:FF": "Microsoft",
    "00:0D:3A": "Microsoft",
    "28:18:78": "Microsoft",
    "7C:1E:52": "Microsoft",
    "60:45:BD": "Microsoft",
}


def get_vendor_from_mac(mac: str) -> str:
    """
    Look up vendor from MAC address using OUI prefix.
    
    Args:
        mac: MAC address in format XX:XX:XX:XX:XX:XX
        
    Returns:
        Vendor name if found, otherwise "Unknown"
    """
    if not mac:
        return "Unknown"
    
    # Normalize MAC address
    mac = mac.upper().replace("-", ":")
    
    # Get OUI prefix (first 3 octets)
    oui = ":".join(mac.split(":")[:3])
    
    return OUI_VENDORS.get(oui, "Unknown")
