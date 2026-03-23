"""
HVAC Vendor SNMP Profiles.

Maps vendor-specific SNMP OIDs to standardized HVAC metric fields.
Each profile defines how to read temperature, humidity, compressor status,
fan speed, alarms, and other PACU-specific metrics from a given vendor's MIB.

To add a new vendor:
  1. Create a dict with the same keys as the existing profiles
  2. Add the vendor's enterprise OID prefix to VENDOR_ENTERPRISE_OIDS
  3. Register it in HVAC_PROFILES
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class HVACProfile:
    """SNMP OID mapping for an HVAC vendor."""
    vendor: str
    description: str
    enterprise_prefix: str  # e.g., "1.3.6.1.4.1.476"

    # Temperature OIDs (values in tenths of degrees unless scale specified)
    supply_temp_oid: str = ""
    return_temp_oid: str = ""
    setpoint_temp_oid: str = ""
    outdoor_temp_oid: str = ""

    # Humidity OIDs (values in tenths of percent unless scale specified)
    supply_humidity_oid: str = ""
    return_humidity_oid: str = ""
    setpoint_humidity_oid: str = ""

    # Unit status OIDs
    unit_status_oid: str = ""        # operating mode / state
    compressor_status_oid: str = ""
    fan_speed_oid: str = ""
    airflow_oid: str = ""

    # Capacity / power
    cooling_capacity_oid: str = ""
    heating_capacity_oid: str = ""
    power_consumption_oid: str = ""

    # Alarm OIDs (walk these for active alarms)
    alarm_table_oid: str = ""
    alarm_description_oid: str = ""

    # Value scaling: multiply raw SNMP value by this to get real units
    temp_scale: float = 0.1    # most vendors report tenths of degrees
    humidity_scale: float = 0.1
    airflow_scale: float = 1.0

    # Status value mappings (vendor-specific int -> string)
    status_map: Dict[int, str] = field(default_factory=dict)

    # OIDs to walk for general discovery (if the specific OIDs above are empty)
    walk_bases: List[str] = field(default_factory=list)


# -- Vendor Profiles --

LIEBERT_PROFILE = HVACProfile(
    vendor="Liebert/Vertiv",
    description="Liebert DS/CRV/PDX/PCW series CRAC/CRAH units",
    enterprise_prefix="1.3.6.1.4.1.476",
    # lgpEnvTemperature measurement table
    supply_temp_oid="1.3.6.1.4.1.476.1.42.3.4.1.3.3.1.3.1",
    return_temp_oid="1.3.6.1.4.1.476.1.42.3.4.1.3.3.1.3.2",
    setpoint_temp_oid="1.3.6.1.4.1.476.1.42.3.4.1.2.3.1.3.1",
    # lgpEnvHumidity measurement table
    supply_humidity_oid="1.3.6.1.4.1.476.1.42.3.4.2.2.3.1.3.1",
    return_humidity_oid="1.3.6.1.4.1.476.1.42.3.4.2.2.3.1.3.2",
    setpoint_humidity_oid="1.3.6.1.4.1.476.1.42.3.4.2.1.3.1.3.1",
    # lgpEnvState
    unit_status_oid="1.3.6.1.4.1.476.1.42.3.4.7.1.0",
    cooling_capacity_oid="1.3.6.1.4.1.476.1.42.3.4.7.2.0",
    heating_capacity_oid="1.3.6.1.4.1.476.1.42.3.4.7.3.0",
    temp_scale=0.1,
    humidity_scale=0.1,
    status_map={1: "on", 2: "off", 3: "standby", 4: "idle"},
    walk_bases=[
        "1.3.6.1.4.1.476.1.42.3.4",   # lgpEnvironmental
        "1.3.6.1.4.1.476.1.42.3.9",   # lgpFlexible
    ],
)

APC_PROFILE = HVACProfile(
    vendor="APC/Schneider",
    description="APC InRow RD/RC/RP, ACRC, NetworkAIR series",
    enterprise_prefix="1.3.6.1.4.1.318",
    # airIRRC Unit Status
    supply_temp_oid="1.3.6.1.4.1.318.1.1.13.3.2.2.2.7.0",
    return_temp_oid="1.3.6.1.4.1.318.1.1.13.3.2.2.2.9.0",
    setpoint_temp_oid="1.3.6.1.4.1.318.1.1.13.3.2.1.2.0",
    supply_humidity_oid="1.3.6.1.4.1.318.1.1.13.3.2.2.2.8.0",
    return_humidity_oid="1.3.6.1.4.1.318.1.1.13.3.2.2.2.10.0",
    unit_status_oid="1.3.6.1.4.1.318.1.1.13.3.2.2.2.1.0",
    airflow_oid="1.3.6.1.4.1.318.1.1.13.3.2.2.2.4.0",
    cooling_capacity_oid="1.3.6.1.4.1.318.1.1.13.3.2.2.2.2.0",
    # APC reports temps in tenths of degrees
    temp_scale=0.1,
    humidity_scale=0.1,
    airflow_scale=1.0,
    status_map={1: "standby", 2: "on", 3: "idle", 4: "off"},
    walk_bases=[
        "1.3.6.1.4.1.318.1.1.13",  # airIR
    ],
)

STULZ_PROFILE = HVACProfile(
    vendor="Stulz",
    description="Stulz CyberAir/WIB8000 series CRAC units",
    enterprise_prefix="1.3.6.1.4.1.29462",
    supply_temp_oid="1.3.6.1.4.1.29462.10.2.1.1.1.1.1.1.1.1.0",
    return_temp_oid="1.3.6.1.4.1.29462.10.2.1.1.1.1.1.1.1.2.0",
    setpoint_temp_oid="1.3.6.1.4.1.29462.10.2.1.1.2.1.1.1.1.1.0",
    supply_humidity_oid="1.3.6.1.4.1.29462.10.2.1.1.1.2.1.1.1.1.0",
    setpoint_humidity_oid="1.3.6.1.4.1.29462.10.2.1.1.2.2.1.1.1.1.0",
    unit_status_oid="1.3.6.1.4.1.29462.10.2.1.1.1.3.1.1.1.1.0",
    temp_scale=0.1,
    humidity_scale=0.1,
    status_map={1: "on", 2: "off", 3: "standby"},
    walk_bases=[
        "1.3.6.1.4.1.29462.10.2.1",
    ],
)

RITTAL_PROFILE = HVACProfile(
    vendor="Rittal",
    description="Rittal LCP/CMC III cooling units",
    enterprise_prefix="1.3.6.1.4.1.2606",
    supply_temp_oid="1.3.6.1.4.1.2606.7.4.2.2.1.11.1.1",
    return_temp_oid="1.3.6.1.4.1.2606.7.4.2.2.1.11.1.2",
    setpoint_temp_oid="1.3.6.1.4.1.2606.7.4.2.2.1.11.1.3",
    supply_humidity_oid="1.3.6.1.4.1.2606.7.4.2.2.1.11.1.4",
    unit_status_oid="1.3.6.1.4.1.2606.7.4.2.2.1.11.1.6",
    fan_speed_oid="1.3.6.1.4.1.2606.7.4.2.2.1.11.1.5",
    temp_scale=0.1,
    humidity_scale=0.1,
    status_map={0: "off", 1: "on", 2: "standby"},
    walk_bases=[
        "1.3.6.1.4.1.2606.7.4",
    ],
)


# -- Profile Registry --

HVAC_PROFILES: Dict[str, HVACProfile] = {
    "liebert": LIEBERT_PROFILE,
    "apc": APC_PROFILE,
    "stulz": STULZ_PROFILE,
    "rittal": RITTAL_PROFILE,
}

# Map enterprise OID prefix -> profile key for auto-detection
VENDOR_ENTERPRISE_OIDS: Dict[str, str] = {
    "1.3.6.1.4.1.476": "liebert",
    "1.3.6.1.4.1.318": "apc",
    "1.3.6.1.4.1.29462": "stulz",
    "1.3.6.1.4.1.2606": "rittal",
}

# sysDescr keywords that hint at HVAC equipment
HVAC_SYSDESCR_KEYWORDS = [
    "liebert", "vertiv", "emerson network power",
    "apc", "schneider", "inrow", "networkair", "acrc",
    "stulz", "cyberair", "wib8000",
    "rittal", "lcp", "cmc",
    "crac", "crah", "precision air", "cooling unit",
    "hvac", "air conditioning", "air handler",
]


def detect_hvac_profile(sys_object_id: str = "", sys_descr: str = "") -> Optional[str]:
    """Detect which HVAC profile to use based on sysObjectID or sysDescr.

    Returns the profile key (e.g. "liebert") or None if not HVAC.
    """
    # Check enterprise OID prefix
    if sys_object_id:
        clean_oid = sys_object_id.lstrip(".")
        for prefix, profile_key in VENDOR_ENTERPRISE_OIDS.items():
            if clean_oid.startswith(prefix):
                return profile_key

    # Check sysDescr keywords
    if sys_descr:
        descr_lower = sys_descr.lower()
        for keyword in HVAC_SYSDESCR_KEYWORDS:
            if keyword in descr_lower:
                # Try to identify the specific vendor
                for profile_key, profile in HVAC_PROFILES.items():
                    if profile.vendor.lower().split("/")[0] in descr_lower:
                        return profile_key
                # Generic HVAC detected but unknown vendor - return first match
                return list(HVAC_PROFILES.keys())[0]

    return None
