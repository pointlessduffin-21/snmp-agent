"""
MIB Definitions for Hardware Metrics.

Defines the custom OID structure for exposing aggregated
hardware metrics via SNMP.
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class OIDDefinition:
    """Definition for a single OID."""
    oid: str
    name: str
    value_type: str  # Integer, String, Counter64, Gauge32, etc.
    access: str = "read-only"
    description: str = ""


class MIBDefinitions:
    """
    Custom MIB structure for hardware metrics aggregation.
    
    Base OID: .1.3.6.1.4.1.99999 (Private Enterprise - placeholder)
    
    Structure:
    .1.3.6.1.4.1.99999
      └── .1 (hwAggregator)
            ├── .1 (hwAgentInfo)
            │     ├── .1 (agentVersion)
            │     ├── .2 (agentUptime)
            │     └── .3 (machineCount)
            ├── .2 (machineTable)
            │     └── .1 (machineEntry)
            │           ├── .1 (machineIndex)
            │           ├── .2 (machineIP)
            │           ├── .3 (machineHostname)
            │           ├── .4 (machineOSType)
            │           ├── .5 (machineUptime)
            │           └── .6 (machineStatus)
            ├── .3 (cpuTable)
            │     └── .1 (cpuEntry)
            │           ├── .1 (cpuIndex) - same as machineIndex
            │           ├── .2 (cpuUsagePercent)
            │           ├── .3 (cpuCoreCount)
            │           ├── .4 (cpuThreadCount)
            │           ├── .5 (cpuFrequencyMHz)
            │           ├── .6 (cpuTemperature)
            │           ├── .7 (cpuLoad1m)
            │           ├── .8 (cpuLoad5m)
            │           └── .9 (cpuLoad15m)
            ├── .4 (memoryTable)
            │     └── .1 (memoryEntry)
            │           ├── .1 (memIndex)
            │           ├── .2 (memTotalBytes)
            │           ├── .3 (memUsedBytes)
            │           ├── .4 (memAvailableBytes)
            │           ├── .5 (memUsagePercent)
            │           ├── .6 (swapTotalBytes)
            │           └── .7 (swapUsedBytes)
            ├── .5 (storageTable)
            │     └── .1 (storageEntry)
            │           ├── .1 (storageIndex) - composite: machineIndex.deviceIndex
            │           ├── .2 (storageMachineIndex)
            │           ├── .3 (storageDevice)
            │           ├── .4 (storageMountPoint)
            │           ├── .5 (storageFSType)
            │           ├── .6 (storageTotalBytes)
            │           ├── .7 (storageUsedBytes)
            │           ├── .8 (storageFreeBytes)
            │           └── .9 (storageUsagePercent)
            └── .6 (powerTable)
                  └── .1 (powerEntry)
                        ├── .1 (powerIndex)
                        ├── .2 (powerCPUWatts)
                        ├── .3 (powerBatteryPercent)
                        └── .4 (powerPluggedIn)
    """
    
    # Base OID - can be customized
    # Using a placeholder private enterprise number
    BASE_OID = "1.3.6.1.4.1.99999"
    
    # Main tree
    HW_AGGREGATOR = f"{BASE_OID}.1"
    
    # Agent info (scalars)
    AGENT_INFO = f"{HW_AGGREGATOR}.1"
    AGENT_VERSION = f"{AGENT_INFO}.1.0"
    AGENT_UPTIME = f"{AGENT_INFO}.2.0"
    MACHINE_COUNT = f"{AGENT_INFO}.3.0"
    
    # Machine table
    MACHINE_TABLE = f"{HW_AGGREGATOR}.2"
    MACHINE_ENTRY = f"{MACHINE_TABLE}.1"
    MACHINE_INDEX = f"{MACHINE_ENTRY}.1"
    MACHINE_IP = f"{MACHINE_ENTRY}.2"
    MACHINE_HOSTNAME = f"{MACHINE_ENTRY}.3"
    MACHINE_OS_TYPE = f"{MACHINE_ENTRY}.4"
    MACHINE_UPTIME = f"{MACHINE_ENTRY}.5"
    MACHINE_STATUS = f"{MACHINE_ENTRY}.6"
    MACHINE_LAST_SEEN = f"{MACHINE_ENTRY}.7"
    
    # CPU table
    CPU_TABLE = f"{HW_AGGREGATOR}.3"
    CPU_ENTRY = f"{CPU_TABLE}.1"
    CPU_INDEX = f"{CPU_ENTRY}.1"
    CPU_USAGE_PERCENT = f"{CPU_ENTRY}.2"
    CPU_CORE_COUNT = f"{CPU_ENTRY}.3"
    CPU_THREAD_COUNT = f"{CPU_ENTRY}.4"
    CPU_FREQUENCY_MHZ = f"{CPU_ENTRY}.5"
    CPU_TEMPERATURE = f"{CPU_ENTRY}.6"
    CPU_LOAD_1M = f"{CPU_ENTRY}.7"
    CPU_LOAD_5M = f"{CPU_ENTRY}.8"
    CPU_LOAD_15M = f"{CPU_ENTRY}.9"
    CPU_MODEL = f"{CPU_ENTRY}.10"
    
    # Memory table
    MEMORY_TABLE = f"{HW_AGGREGATOR}.4"
    MEMORY_ENTRY = f"{MEMORY_TABLE}.1"
    MEM_INDEX = f"{MEMORY_ENTRY}.1"
    MEM_TOTAL_BYTES = f"{MEMORY_ENTRY}.2"
    MEM_USED_BYTES = f"{MEMORY_ENTRY}.3"
    MEM_AVAILABLE_BYTES = f"{MEMORY_ENTRY}.4"
    MEM_USAGE_PERCENT = f"{MEMORY_ENTRY}.5"
    SWAP_TOTAL_BYTES = f"{MEMORY_ENTRY}.6"
    SWAP_USED_BYTES = f"{MEMORY_ENTRY}.7"
    
    # Storage table
    STORAGE_TABLE = f"{HW_AGGREGATOR}.5"
    STORAGE_ENTRY = f"{STORAGE_TABLE}.1"
    STORAGE_INDEX = f"{STORAGE_ENTRY}.1"
    STORAGE_MACHINE_INDEX = f"{STORAGE_ENTRY}.2"
    STORAGE_DEVICE = f"{STORAGE_ENTRY}.3"
    STORAGE_MOUNT_POINT = f"{STORAGE_ENTRY}.4"
    STORAGE_FS_TYPE = f"{STORAGE_ENTRY}.5"
    STORAGE_TOTAL_BYTES = f"{STORAGE_ENTRY}.6"
    STORAGE_USED_BYTES = f"{STORAGE_ENTRY}.7"
    STORAGE_FREE_BYTES = f"{STORAGE_ENTRY}.8"
    STORAGE_USAGE_PERCENT = f"{STORAGE_ENTRY}.9"
    
    # Power table
    POWER_TABLE = f"{HW_AGGREGATOR}.6"
    POWER_ENTRY = f"{POWER_TABLE}.1"
    POWER_INDEX = f"{POWER_ENTRY}.1"
    POWER_CPU_WATTS = f"{POWER_ENTRY}.2"
    POWER_BATTERY_PERCENT = f"{POWER_ENTRY}.3"
    POWER_PLUGGED_IN = f"{POWER_ENTRY}.4"
    
    # Network table
    NETWORK_TABLE = f"{HW_AGGREGATOR}.7"
    NETWORK_ENTRY = f"{NETWORK_TABLE}.1"
    NET_INDEX = f"{NETWORK_ENTRY}.1"
    NET_MACHINE_INDEX = f"{NETWORK_ENTRY}.2"
    NET_INTERFACE_NAME = f"{NETWORK_ENTRY}.3"
    NET_IP_ADDRESS = f"{NETWORK_ENTRY}.4"
    NET_MAC_ADDRESS = f"{NETWORK_ENTRY}.5"
    NET_BYTES_SENT = f"{NETWORK_ENTRY}.6"
    NET_BYTES_RECV = f"{NETWORK_ENTRY}.7"
    
    @classmethod
    def get_all_scalar_oids(cls) -> Dict[str, OIDDefinition]:
        """Get all scalar OID definitions."""
        return {
            cls.AGENT_VERSION: OIDDefinition(
                oid=cls.AGENT_VERSION,
                name="agentVersion",
                value_type="OctetString",
                description="Version of the SNMP aggregator agent",
            ),
            cls.AGENT_UPTIME: OIDDefinition(
                oid=cls.AGENT_UPTIME,
                name="agentUptime",
                value_type="TimeTicks",
                description="Uptime of the agent in hundredths of seconds",
            ),
            cls.MACHINE_COUNT: OIDDefinition(
                oid=cls.MACHINE_COUNT,
                name="machineCount",
                value_type="Integer32",
                description="Number of machines being monitored",
            ),
        }
    
    @classmethod
    def get_machine_table_oids(cls) -> Dict[str, OIDDefinition]:
        """Get machine table column definitions."""
        return {
            cls.MACHINE_INDEX: OIDDefinition(
                oid=cls.MACHINE_INDEX,
                name="machineIndex",
                value_type="Integer32",
                description="Unique index for this machine",
            ),
            cls.MACHINE_IP: OIDDefinition(
                oid=cls.MACHINE_IP,
                name="machineIP",
                value_type="IpAddress",
                description="IP address of the machine",
            ),
            cls.MACHINE_HOSTNAME: OIDDefinition(
                oid=cls.MACHINE_HOSTNAME,
                name="machineHostname",
                value_type="OctetString",
                description="Hostname of the machine",
            ),
            cls.MACHINE_OS_TYPE: OIDDefinition(
                oid=cls.MACHINE_OS_TYPE,
                name="machineOSType",
                value_type="OctetString",
                description="Operating system type",
            ),
            cls.MACHINE_UPTIME: OIDDefinition(
                oid=cls.MACHINE_UPTIME,
                name="machineUptime",
                value_type="TimeTicks",
                description="Machine uptime in hundredths of seconds",
            ),
            cls.MACHINE_STATUS: OIDDefinition(
                oid=cls.MACHINE_STATUS,
                name="machineStatus",
                value_type="Integer32",
                description="Status: 1=online, 2=offline, 3=unknown",
            ),
        }
    
    @classmethod
    def get_cpu_table_oids(cls) -> Dict[str, OIDDefinition]:
        """Get CPU table column definitions."""
        return {
            cls.CPU_INDEX: OIDDefinition(
                oid=cls.CPU_INDEX,
                name="cpuIndex",
                value_type="Integer32",
                description="Index matching machineIndex",
            ),
            cls.CPU_USAGE_PERCENT: OIDDefinition(
                oid=cls.CPU_USAGE_PERCENT,
                name="cpuUsagePercent",
                value_type="Integer32",
                description="Current CPU usage percentage (0-100)",
            ),
            cls.CPU_CORE_COUNT: OIDDefinition(
                oid=cls.CPU_CORE_COUNT,
                name="cpuCoreCount",
                value_type="Integer32",
                description="Number of physical CPU cores",
            ),
            cls.CPU_THREAD_COUNT: OIDDefinition(
                oid=cls.CPU_THREAD_COUNT,
                name="cpuThreadCount",
                value_type="Integer32",
                description="Number of logical CPU threads",
            ),
            cls.CPU_FREQUENCY_MHZ: OIDDefinition(
                oid=cls.CPU_FREQUENCY_MHZ,
                name="cpuFrequencyMHz",
                value_type="Integer32",
                description="Current CPU frequency in MHz",
            ),
            cls.CPU_TEMPERATURE: OIDDefinition(
                oid=cls.CPU_TEMPERATURE,
                name="cpuTemperature",
                value_type="Integer32",
                description="CPU temperature in degrees Celsius",
            ),
            cls.CPU_LOAD_1M: OIDDefinition(
                oid=cls.CPU_LOAD_1M,
                name="cpuLoad1m",
                value_type="OctetString",
                description="1-minute load average",
            ),
            cls.CPU_LOAD_5M: OIDDefinition(
                oid=cls.CPU_LOAD_5M,
                name="cpuLoad5m",
                value_type="OctetString",
                description="5-minute load average",
            ),
            cls.CPU_LOAD_15M: OIDDefinition(
                oid=cls.CPU_LOAD_15M,
                name="cpuLoad15m",
                value_type="OctetString",
                description="15-minute load average",
            ),
        }


def oid_to_tuple(oid_string: str) -> tuple:
    """Convert OID string to tuple of integers."""
    return tuple(int(x) for x in oid_string.split(".") if x)


def tuple_to_oid(oid_tuple: tuple) -> str:
    """Convert OID tuple to string."""
    return ".".join(str(x) for x in oid_tuple)
