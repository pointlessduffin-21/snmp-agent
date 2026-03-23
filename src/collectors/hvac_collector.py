"""
HVAC/PACU SNMP Collector.

Collects metrics from Precision Air Conditioning Units using
vendor-specific SNMP OID profiles.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

from pysnmp.hlapi.asyncio import (
    getCmd,
    walkCmd,
    SnmpEngine,
    CommunityData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
)

from ..core.models import MachineInfo, HVACMetrics, HardwareSnapshot, CPUMetrics, MemoryMetrics, StorageMetrics, PowerMetrics, NetworkMetrics
from .hvac_profiles import HVACProfile, HVAC_PROFILES, detect_hvac_profile, VENDOR_ENTERPRISE_OIDS


logger = logging.getLogger(__name__)


# Standard OIDs for device identification
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"


class HVACCollector:
    """Collects metrics from HVAC/PACU units via SNMP."""

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
        """Get a single OID value."""
        try:
            iterator = getCmd(
                self._engine,
                CommunityData(self.community),
                UdpTransportTarget((ip, self.port), timeout=self.timeout, retries=self.retries),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )
            errorIndication, errorStatus, errorIndex, varBinds = await iterator

            if errorIndication or errorStatus:
                return None
            if varBinds:
                return varBinds[0][1]
        except Exception as e:
            logger.debug(f"HVAC get OID {oid} from {ip}: {e}")
        return None

    async def _get_oids(self, ip: str, oids: list) -> Dict[str, Any]:
        """Get multiple OIDs in a single request."""
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
            logger.debug(f"HVAC get OIDs from {ip}: {e}")
        return results

    async def _walk_oid(self, ip: str, oid: str) -> Dict[str, Any]:
        """Walk an OID subtree."""
        results = {}
        try:
            async for (errorIndication, errorStatus, errorIndex, varBinds) in walkCmd(
                self._engine,
                CommunityData(self.community),
                UdpTransportTarget((ip, self.port), timeout=self.timeout, retries=self.retries),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
                lexicographicMode=False,
            ):
                if errorIndication or errorStatus:
                    break
                for varBind in varBinds:
                    results[str(varBind[0])] = varBind[1]
        except Exception as e:
            logger.debug(f"HVAC walk {oid} from {ip}: {e}")
        return results

    async def detect_device(self, ip: str) -> Optional[str]:
        """Detect if a device is HVAC and return the profile key.

        Returns profile key (e.g. 'liebert') or None.
        """
        results = await self._get_oids(ip, [SYS_OBJECT_ID, SYS_DESCR])

        sys_obj_id = ""
        sys_descr = ""

        for oid, value in results.items():
            if SYS_OBJECT_ID in oid:
                sys_obj_id = str(value)
            elif SYS_DESCR in oid:
                sys_descr = str(value)

        return detect_hvac_profile(sys_obj_id, sys_descr)

    def _safe_float(self, value: Any, scale: float = 1.0) -> Optional[float]:
        """Safely convert SNMP value to scaled float."""
        if value is None:
            return None
        try:
            raw = float(str(value).strip())
            return round(raw * scale, 1)
        except (ValueError, TypeError):
            return None

    def _safe_int(self, value: Any) -> Optional[int]:
        """Safely convert SNMP value to int."""
        if value is None:
            return None
        try:
            return int(str(value).strip())
        except (ValueError, TypeError):
            return None

    async def collect_all(self, ip: str, profile_key: Optional[str] = None) -> Optional[HardwareSnapshot]:
        """Collect all HVAC metrics from a device.

        Args:
            ip: Device IP address
            profile_key: HVAC profile to use (auto-detected if None)

        Returns:
            HardwareSnapshot with HVAC metrics populated, or None on failure.
        """
        start_time = time.time()
        errors = []

        # Auto-detect profile if not specified
        if not profile_key:
            profile_key = await self.detect_device(ip)
        if not profile_key or profile_key not in HVAC_PROFILES:
            return None

        profile = HVAC_PROFILES[profile_key]

        # Get basic device info
        info_results = await self._get_oids(ip, [SYS_NAME, SYS_DESCR, SYS_UPTIME])
        hostname = "unknown"
        sys_descr = ""
        uptime = 0

        for oid, value in info_results.items():
            if SYS_NAME in oid:
                hostname = str(value) or "unknown"
            elif SYS_DESCR in oid:
                sys_descr = str(value)
            elif SYS_UPTIME in oid:
                try:
                    uptime = int(value) // 100
                except (ValueError, TypeError):
                    pass

        machine = MachineInfo(
            ip=ip,
            hostname=hostname,
            os_type="HVAC",
            os_version=sys_descr[:100] if sys_descr else "",
            uptime_seconds=uptime,
            last_seen=datetime.now(),
            is_online=True,
            collection_method="snmp",
            snmp_active=True,
            snmp_sysname=hostname if hostname != "unknown" else "",
            device_type="hvac",
        )

        # Collect all HVAC-specific OIDs
        oids_to_fetch = []
        oid_map = {}  # oid -> field name

        for field_name in [
            "supply_temp_oid", "return_temp_oid", "setpoint_temp_oid", "outdoor_temp_oid",
            "supply_humidity_oid", "return_humidity_oid", "setpoint_humidity_oid",
            "unit_status_oid", "compressor_status_oid", "fan_speed_oid", "airflow_oid",
            "cooling_capacity_oid", "heating_capacity_oid", "power_consumption_oid",
        ]:
            oid_value = getattr(profile, field_name, "")
            if oid_value:
                oids_to_fetch.append(oid_value)
                oid_map[oid_value] = field_name

        raw_values = {}
        if oids_to_fetch:
            # Fetch in batches of 10 (some SNMP agents can't handle too many varbinds)
            for i in range(0, len(oids_to_fetch), 10):
                batch = oids_to_fetch[i:i+10]
                results = await self._get_oids(ip, batch)
                for oid, value in results.items():
                    # Map back to field name
                    for req_oid, fname in oid_map.items():
                        if req_oid in oid:
                            raw_values[fname] = value
                            break

        # Build HVAC metrics
        hvac = HVACMetrics(vendor_profile=profile_key)

        hvac.supply_temp_c = self._safe_float(
            raw_values.get("supply_temp_oid"), profile.temp_scale)
        hvac.return_temp_c = self._safe_float(
            raw_values.get("return_temp_oid"), profile.temp_scale)
        hvac.setpoint_temp_c = self._safe_float(
            raw_values.get("setpoint_temp_oid"), profile.temp_scale)
        hvac.outdoor_temp_c = self._safe_float(
            raw_values.get("outdoor_temp_oid"), profile.temp_scale)

        hvac.supply_humidity_pct = self._safe_float(
            raw_values.get("supply_humidity_oid"), profile.humidity_scale)
        hvac.return_humidity_pct = self._safe_float(
            raw_values.get("return_humidity_oid"), profile.humidity_scale)
        hvac.setpoint_humidity_pct = self._safe_float(
            raw_values.get("setpoint_humidity_oid"), profile.humidity_scale)

        hvac.fan_speed_rpm = self._safe_int(raw_values.get("fan_speed_oid"))
        hvac.airflow_cfm = self._safe_float(
            raw_values.get("airflow_oid"), profile.airflow_scale)
        hvac.cooling_capacity_pct = self._safe_float(
            raw_values.get("cooling_capacity_oid"), 0.1)
        hvac.heating_capacity_pct = self._safe_float(
            raw_values.get("heating_capacity_oid"), 0.1)
        hvac.power_watts = self._safe_float(
            raw_values.get("power_consumption_oid"))

        # Parse unit status
        status_raw = self._safe_int(raw_values.get("unit_status_oid"))
        if status_raw is not None:
            hvac.unit_status = profile.status_map.get(status_raw, f"unknown({status_raw})")
        else:
            hvac.unit_status = "unknown"

        compressor_raw = self._safe_int(raw_values.get("compressor_status_oid"))
        if compressor_raw is not None:
            hvac.compressor_running = compressor_raw in (1, 2)  # vendor-dependent, 1 usually = on

        # Walk alarm table if defined
        if profile.alarm_table_oid:
            try:
                alarms = await self._walk_oid(ip, profile.alarm_table_oid)
                hvac.active_alarms = [str(v) for v in alarms.values() if str(v).strip()]
            except Exception as e:
                errors.append(f"Alarms: {e}")

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"HVAC collection for {ip} ({profile.vendor}) completed in {duration_ms:.0f}ms - "
            f"Supply: {hvac.supply_temp_c}°C, Return: {hvac.return_temp_c}°C, "
            f"Humidity: {hvac.supply_humidity_pct}%, Status: {hvac.unit_status}"
        )

        return HardwareSnapshot(
            machine=machine,
            cpu=CPUMetrics(),
            memory=MemoryMetrics(),
            storage=StorageMetrics(),
            power=PowerMetrics(),
            network=NetworkMetrics(),
            hvac=hvac,
            timestamp=datetime.now(),
            collection_duration_ms=duration_ms,
            errors=errors,
        )
