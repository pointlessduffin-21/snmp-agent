"""
SNMP Agent Server.

Main SNMP agent implementation that serves aggregated hardware metrics
from all discovered machines on the network.
"""

import asyncio
import logging
import time
import random
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from pysnmp.proto import rfc1902

from .mib_definitions import MIBDefinitions, oid_to_tuple, tuple_to_oid
from ..core.models import HardwareSnapshot
from ..core.data_manager import DataManager


logger = logging.getLogger(__name__)


class _SNMPProtocol(asyncio.DatagramProtocol):
    """UDP protocol handler for SNMP requests."""

    def __init__(self, agent: "SimpleSNMPAgent"):
        self.agent = agent
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        try:
            response = self.agent.handle_snmp_message(data)
            if response:
                self.transport.sendto(response, addr)
        except Exception as e:
            logger.error(f"SNMP datagram error from {addr}: {e}")

    def error_received(self, exc):
        logger.error(f"SNMP UDP error: {exc}")


class _TrapProtocol(asyncio.DatagramProtocol):
    """UDP protocol handler for incoming SNMP traps."""

    def __init__(self, agent: "SimpleSNMPAgent"):
        self.agent = agent
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        try:
            self.agent.handle_trap_message(data, addr)
        except Exception as e:
            logger.error(f"Trap datagram error from {addr}: {e}")

    def error_received(self, exc):
        logger.error(f"Trap UDP error: {exc}")


class SimpleSNMPAgent:
    """
    SNMP agent that serves aggregated hardware metrics over UDP.

    Listens on a UDP port and responds to SNMPv2c GET, GETNEXT,
    and GETBULK requests using collected metrics data.
    Also receives SNMP traps on a separate port and stores them.
    """

    TRAP_BUFFER_SIZE = 500  # Max traps to keep in memory

    def __init__(
        self,
        data_manager: DataManager,
        port: int = 1161,
        trap_port: int = 1162,
        community: str = "public",
    ):
        self.data_manager = data_manager
        self.port = port
        self.trap_port = trap_port
        self.community = community
        self._udp_transport = None
        self._trap_transport = None
        self._running = False
        self._start_time = time.time()
        self._mib = MIBDefinitions()
        self._oid_data: Dict[str, Any] = {}
        self._sorted_oids: List[str] = []
        self._ip_to_index: Dict[str, int] = {}
        # Trap storage (ring buffer)
        self._traps: deque = deque(maxlen=self.TRAP_BUFFER_SIZE)
        self._trap_count: int = 0

    async def start(self):
        """Start the SNMP agent with a real UDP server and trap receiver."""
        logger.info(f"Starting SNMP Agent on UDP port {self.port}")

        self._running = True
        asyncio.create_task(self._update_loop())

        # Wait for first data update so we have OIDs to serve
        await self._update_data()

        # Bind UDP socket for GET/GETNEXT/GETBULK
        loop = asyncio.get_event_loop()
        self._udp_transport, _ = await loop.create_datagram_endpoint(
            lambda: _SNMPProtocol(self),
            local_addr=("0.0.0.0", self.port),
        )
        logger.info(f"SNMP Agent listening on UDP port {self.port}")

        # Bind UDP socket for trap receiver
        self._trap_transport, _ = await loop.create_datagram_endpoint(
            lambda: _TrapProtocol(self),
            local_addr=("0.0.0.0", self.trap_port),
        )
        logger.info(f"SNMP Trap receiver listening on UDP port {self.trap_port}")

    async def stop(self):
        """Stop the agent."""
        self._running = False
        if self._udp_transport:
            self._udp_transport.close()
            self._udp_transport = None
        if self._trap_transport:
            self._trap_transport.close()
            self._trap_transport = None
        logger.info("SNMP Agent stopped")

    async def _update_loop(self):
        """Update data periodically."""
        while self._running:
            await self._update_data()
            await asyncio.sleep(5)

    async def _update_data(self):
        """Update OID data from snapshots."""
        self._oid_data.clear()
        self._ip_to_index.clear()

        snapshots = await self.data_manager.get_snapshots()

        # Build index mapping
        for idx, ip in enumerate(sorted(snapshots.keys()), start=1):
            self._ip_to_index[ip] = idx

        # Agent scalars
        uptime = int((time.time() - self._start_time) * 100)
        self._oid_data[MIBDefinitions.AGENT_VERSION] = "1.0.0"
        self._oid_data[MIBDefinitions.AGENT_UPTIME] = uptime
        self._oid_data[MIBDefinitions.MACHINE_COUNT] = len(snapshots)

        # Build entries for each machine
        for ip, snapshot in snapshots.items():
            idx = self._ip_to_index[ip]
            self._add_machine_oids(idx, snapshot)

        # Pre-sort OIDs for efficient GETNEXT/GETBULK
        self._sorted_oids = sorted(
            self._oid_data.keys(),
            key=lambda o: tuple(int(p) for p in o.split(".")),
        )

    def _add_machine_oids(self, idx: int, snapshot: HardwareSnapshot):
        """Add OIDs for a machine."""
        m = snapshot.machine
        c = snapshot.cpu
        mem = snapshot.memory

        # Machine table
        self._oid_data[f"{MIBDefinitions.MACHINE_INDEX}.{idx}"] = idx
        self._oid_data[f"{MIBDefinitions.MACHINE_IP}.{idx}"] = m.ip
        self._oid_data[f"{MIBDefinitions.MACHINE_HOSTNAME}.{idx}"] = m.hostname
        self._oid_data[f"{MIBDefinitions.MACHINE_OS_TYPE}.{idx}"] = m.os_type
        self._oid_data[f"{MIBDefinitions.MACHINE_UPTIME}.{idx}"] = m.uptime_seconds * 100
        self._oid_data[f"{MIBDefinitions.MACHINE_STATUS}.{idx}"] = 1 if m.is_online else 2

        # CPU table
        self._oid_data[f"{MIBDefinitions.CPU_INDEX}.{idx}"] = idx
        self._oid_data[f"{MIBDefinitions.CPU_USAGE_PERCENT}.{idx}"] = int(c.usage_percent)
        self._oid_data[f"{MIBDefinitions.CPU_CORE_COUNT}.{idx}"] = c.core_count
        self._oid_data[f"{MIBDefinitions.CPU_THREAD_COUNT}.{idx}"] = c.thread_count
        self._oid_data[f"{MIBDefinitions.CPU_FREQUENCY_MHZ}.{idx}"] = int(c.frequency_mhz)
        self._oid_data[f"{MIBDefinitions.CPU_TEMPERATURE}.{idx}"] = int(c.temperature_celsius or 0)
        self._oid_data[f"{MIBDefinitions.CPU_LOAD_1M}.{idx}"] = f"{c.load_1m:.2f}"
        self._oid_data[f"{MIBDefinitions.CPU_LOAD_5M}.{idx}"] = f"{c.load_5m:.2f}"
        self._oid_data[f"{MIBDefinitions.CPU_LOAD_15M}.{idx}"] = f"{c.load_15m:.2f}"
        self._oid_data[f"{MIBDefinitions.CPU_MODEL}.{idx}"] = c.model_name

        # Memory table
        self._oid_data[f"{MIBDefinitions.MEM_INDEX}.{idx}"] = idx
        self._oid_data[f"{MIBDefinitions.MEM_TOTAL_BYTES}.{idx}"] = mem.total_bytes
        self._oid_data[f"{MIBDefinitions.MEM_USED_BYTES}.{idx}"] = mem.used_bytes
        self._oid_data[f"{MIBDefinitions.MEM_AVAILABLE_BYTES}.{idx}"] = mem.available_bytes
        self._oid_data[f"{MIBDefinitions.MEM_USAGE_PERCENT}.{idx}"] = int(mem.usage_percent)

        # Storage entries
        for dev_idx, device in enumerate(snapshot.storage.devices, start=1):
            key = f"{idx}.{dev_idx}"
            self._oid_data[f"{MIBDefinitions.STORAGE_DEVICE}.{key}"] = device.device
            self._oid_data[f"{MIBDefinitions.STORAGE_MOUNT_POINT}.{key}"] = device.mount_point
            self._oid_data[f"{MIBDefinitions.STORAGE_FS_TYPE}.{key}"] = device.fs_type
            self._oid_data[f"{MIBDefinitions.STORAGE_TOTAL_BYTES}.{key}"] = device.total_bytes
            self._oid_data[f"{MIBDefinitions.STORAGE_USED_BYTES}.{key}"] = device.used_bytes
            self._oid_data[f"{MIBDefinitions.STORAGE_FREE_BYTES}.{key}"] = device.free_bytes
            self._oid_data[f"{MIBDefinitions.STORAGE_USAGE_PERCENT}.{key}"] = int(device.usage_percent)

    # -- SNMP protocol handling --

    def _oid_to_tuple(self, oid_str: str) -> Tuple:
        """Convert dotted OID string to tuple of ints."""
        return tuple(int(p) for p in oid_str.strip(".").split("."))

    def _get_next_oid(self, oid_str: str) -> Optional[str]:
        """Return the next OID lexicographically after *oid_str*."""
        target = self._oid_to_tuple(oid_str)
        for candidate in self._sorted_oids:
            if self._oid_to_tuple(candidate) > target:
                return candidate
        return None

    def _to_snmp_value(self, value: Any):
        """Convert a Python value to a pysnmp rfc1902 object."""
        if isinstance(value, int):
            if value > 2147483647:
                return rfc1902.Counter64(value)
            return rfc1902.Integer32(value)
        return rfc1902.OctetString(str(value))

    def handle_snmp_message(self, data: bytes) -> Optional[bytes]:
        """Decode an SNMP request, look up OIDs, return encoded response."""
        from pysnmp.proto import api
        from pysnmp.proto import rfc1905
        from pyasn1.codec.ber import decoder, encoder

        try:
            msg_ver = api.decodeMessageVersion(data)
            if msg_ver not in api.protoModules:
                return None
            pMod = api.protoModules[msg_ver]

            req_msg, _ = decoder.decode(data, asn1Spec=pMod.Message())
            community = pMod.apiMessage.getCommunity(req_msg)
            if str(community) != self.community:
                return None

            req_pdu = pMod.apiMessage.getPDU(req_msg)
            var_binds = pMod.apiPDU.getVarBinds(req_pdu)

            # Build response scaffolding
            rsp_msg = pMod.Message()
            pMod.apiMessage.setDefaults(rsp_msg)
            pMod.apiMessage.setCommunity(rsp_msg, community)

            rsp_pdu = pMod.GetResponsePDU()
            pMod.apiPDU.setDefaults(rsp_pdu)
            pMod.apiPDU.setRequestID(rsp_pdu, pMod.apiPDU.getRequestID(req_pdu))

            rsp_var_binds = []

            # -- GET --
            if req_pdu.isSameTypeWith(pMod.GetRequestPDU()):
                for oid, _ in var_binds:
                    oid_str = ".".join(str(x) for x in oid)
                    value = self._oid_data.get(oid_str)
                    if value is not None:
                        rsp_var_binds.append((oid, self._to_snmp_value(value)))
                    else:
                        rsp_var_binds.append((oid, rfc1905.noSuchInstance))

            # -- GETNEXT --
            elif req_pdu.isSameTypeWith(pMod.GetNextRequestPDU()):
                for oid, _ in var_binds:
                    oid_str = ".".join(str(x) for x in oid)
                    next_oid = self._get_next_oid(oid_str)
                    if next_oid:
                        rsp_var_binds.append((
                            rfc1902.ObjectIdentifier(next_oid),
                            self._to_snmp_value(self._oid_data[next_oid]),
                        ))
                    else:
                        rsp_var_binds.append((oid, rfc1905.endOfMibView))

            # -- GETBULK --
            elif req_pdu.isSameTypeWith(pMod.GetBulkRequestPDU()):
                non_rep = pMod.apiBulkPDU.getNonRepeaters(req_pdu)
                max_rep = pMod.apiBulkPDU.getMaxRepetitions(req_pdu)

                # Non-repeaters (single GETNEXT each)
                for i in range(min(int(non_rep), len(var_binds))):
                    oid, _ = var_binds[i]
                    oid_str = ".".join(str(x) for x in oid)
                    next_oid = self._get_next_oid(oid_str)
                    if next_oid:
                        rsp_var_binds.append((
                            rfc1902.ObjectIdentifier(next_oid),
                            self._to_snmp_value(self._oid_data[next_oid]),
                        ))
                    else:
                        rsp_var_binds.append((oid, rfc1905.endOfMibView))

                # Repeaters
                for i in range(int(non_rep), len(var_binds)):
                    oid, _ = var_binds[i]
                    cur = ".".join(str(x) for x in oid)
                    for _ in range(int(max_rep)):
                        next_oid = self._get_next_oid(cur)
                        if next_oid:
                            rsp_var_binds.append((
                                rfc1902.ObjectIdentifier(next_oid),
                                self._to_snmp_value(self._oid_data[next_oid]),
                            ))
                            cur = next_oid
                        else:
                            rsp_var_binds.append((
                                rfc1902.ObjectIdentifier(cur),
                                rfc1905.endOfMibView,
                            ))
                            break

            pMod.apiPDU.setVarBinds(rsp_pdu, rsp_var_binds)
            pMod.apiMessage.setPDU(rsp_msg, rsp_pdu)
            return encoder.encode(rsp_msg)

        except Exception as e:
            logger.error(f"SNMP processing error: {e}", exc_info=True)
            return None

    # -- Trap handling --

    def handle_trap_message(self, data: bytes, addr: tuple):
        """Decode an incoming SNMP trap and store it."""
        from pysnmp.proto import api
        from pyasn1.codec.ber import decoder

        try:
            msg_ver = api.decodeMessageVersion(data)
            if msg_ver not in api.protoModules:
                logger.warning(f"Trap from {addr}: unsupported SNMP version")
                return
            pMod = api.protoModules[msg_ver]
            req_msg, _ = decoder.decode(data, asn1Spec=pMod.Message())
            community = str(pMod.apiMessage.getCommunity(req_msg))
            req_pdu = pMod.apiMessage.getPDU(req_msg)

            # Parse trap-specific fields
            trap_entry = {
                "id": self._trap_count + 1,
                "timestamp": datetime.now().isoformat(),
                "source_ip": addr[0],
                "source_port": addr[1],
                "community": community,
                "version": "v2c" if msg_ver == api.protoVersion2c else "v1",
                "var_binds": [],
                "trap_oid": "",
                "uptime": 0,
            }

            if msg_ver == api.protoVersion2c:
                # SNMPv2c trap/inform
                var_binds = pMod.apiPDU.getVarBinds(req_pdu)
                for oid, val in var_binds:
                    oid_str = ".".join(str(x) for x in oid)
                    val_str = str(val.prettyPrint()) if hasattr(val, 'prettyPrint') else str(val)
                    # sysUpTime.0
                    if oid_str == "1.3.6.1.2.1.1.3.0":
                        trap_entry["uptime"] = int(val) if str(val).isdigit() else 0
                    # snmpTrapOID.0
                    elif oid_str == "1.3.6.1.6.3.1.1.4.1.0":
                        trap_entry["trap_oid"] = val_str
                    trap_entry["var_binds"].append({
                        "oid": oid_str,
                        "value": val_str,
                    })
            elif msg_ver == api.protoVersion1:
                # SNMPv1 trap
                trap_entry["trap_oid"] = str(pMod.apiTrapPDU.getEnterprise(req_pdu).prettyPrint())
                trap_entry["uptime"] = int(pMod.apiTrapPDU.getTimeStamp(req_pdu))
                var_binds = pMod.apiTrapPDU.getVarBinds(req_pdu)
                for oid, val in var_binds:
                    trap_entry["var_binds"].append({
                        "oid": ".".join(str(x) for x in oid),
                        "value": str(val.prettyPrint()) if hasattr(val, 'prettyPrint') else str(val),
                    })

            self._traps.append(trap_entry)
            self._trap_count += 1
            logger.info(f"Trap #{self._trap_count} received from {addr[0]}: {trap_entry['trap_oid']}")

        except Exception as e:
            logger.error(f"Trap decode error from {addr}: {e}", exc_info=True)

    def get_traps(self, limit: int = 100, offset: int = 0) -> List[dict]:
        """Get stored traps (newest first)."""
        traps = list(reversed(self._traps))
        return traps[offset:offset + limit]

    def get_trap_count(self) -> int:
        """Get total number of traps received."""
        return self._trap_count

    def clear_traps(self):
        """Clear stored traps."""
        self._traps.clear()
        logger.info("Trap buffer cleared")

    def simulate_trap(self, trap_type: str = "linkDown") -> dict:
        """Generate a simulated trap and add it to the buffer."""
        now = datetime.now()

        # Predefined trap scenarios
        scenarios = {
            "linkDown": {
                "trap_oid": "1.3.6.1.6.3.1.1.5.3",
                "label": "linkDown",
                "var_binds": [
                    {"oid": "1.3.6.1.2.1.1.3.0", "value": str(int(time.time() * 100))},
                    {"oid": "1.3.6.1.6.3.1.1.4.1.0", "value": "1.3.6.1.6.3.1.1.5.3"},
                    {"oid": "1.3.6.1.2.1.2.2.1.1.2", "value": "2"},
                    {"oid": "1.3.6.1.2.1.2.2.1.2.2", "value": "eth0"},
                    {"oid": "1.3.6.1.2.1.2.2.1.8.2", "value": "2"},
                ],
            },
            "linkUp": {
                "trap_oid": "1.3.6.1.6.3.1.1.5.4",
                "label": "linkUp",
                "var_binds": [
                    {"oid": "1.3.6.1.2.1.1.3.0", "value": str(int(time.time() * 100))},
                    {"oid": "1.3.6.1.6.3.1.1.4.1.0", "value": "1.3.6.1.6.3.1.1.5.4"},
                    {"oid": "1.3.6.1.2.1.2.2.1.1.1", "value": "1"},
                    {"oid": "1.3.6.1.2.1.2.2.1.2.1", "value": "eth0"},
                    {"oid": "1.3.6.1.2.1.2.2.1.8.1", "value": "1"},
                ],
            },
            "coldStart": {
                "trap_oid": "1.3.6.1.6.3.1.1.5.1",
                "label": "coldStart",
                "var_binds": [
                    {"oid": "1.3.6.1.2.1.1.3.0", "value": "0"},
                    {"oid": "1.3.6.1.6.3.1.1.4.1.0", "value": "1.3.6.1.6.3.1.1.5.1"},
                    {"oid": "1.3.6.1.2.1.1.1.0", "value": "Linux router 5.15.0 #1 SMP"},
                ],
            },
            "authFailure": {
                "trap_oid": "1.3.6.1.6.3.1.1.5.5",
                "label": "authenticationFailure",
                "var_binds": [
                    {"oid": "1.3.6.1.2.1.1.3.0", "value": str(int(time.time() * 100))},
                    {"oid": "1.3.6.1.6.3.1.1.4.1.0", "value": "1.3.6.1.6.3.1.1.5.5"},
                    {"oid": "1.3.6.1.2.1.1.5.0", "value": "switch-core-01"},
                ],
            },
            "cpuHigh": {
                "trap_oid": "1.3.6.1.4.1.99999.2.1",
                "label": "cpuHighUtilization",
                "var_binds": [
                    {"oid": "1.3.6.1.2.1.1.3.0", "value": str(int(time.time() * 100))},
                    {"oid": "1.3.6.1.6.3.1.1.4.1.0", "value": "1.3.6.1.4.1.99999.2.1"},
                    {"oid": "1.3.6.1.4.1.99999.1.3.1.2.1", "value": str(random.randint(85, 99))},
                    {"oid": "1.3.6.1.2.1.1.5.0", "value": "server-prod-01"},
                ],
            },
            "diskFull": {
                "trap_oid": "1.3.6.1.4.1.99999.2.2",
                "label": "diskSpaceCritical",
                "var_binds": [
                    {"oid": "1.3.6.1.2.1.1.3.0", "value": str(int(time.time() * 100))},
                    {"oid": "1.3.6.1.6.3.1.1.4.1.0", "value": "1.3.6.1.4.1.99999.2.2"},
                    {"oid": "1.3.6.1.4.1.99999.1.5.1.9.1.1", "value": str(random.randint(90, 99))},
                    {"oid": "1.3.6.1.4.1.99999.1.5.1.4.1.1", "value": "/"},
                    {"oid": "1.3.6.1.2.1.1.5.0", "value": "fileserver-01"},
                ],
            },
        }

        scenario = scenarios.get(trap_type, scenarios["linkDown"])
        sim_ips = ["192.168.0.10", "192.168.0.20", "192.168.0.30", "10.0.1.50", "172.16.0.100"]

        trap_entry = {
            "id": self._trap_count + 1,
            "timestamp": now.isoformat(),
            "source_ip": random.choice(sim_ips),
            "source_port": random.randint(30000, 65000),
            "community": "public",
            "version": "v2c",
            "trap_oid": scenario["trap_oid"],
            "uptime": int(time.time() * 100),
            "var_binds": scenario["var_binds"],
            "simulated": True,
        }

        self._traps.append(trap_entry)
        self._trap_count += 1
        logger.info(f"Simulated trap #{self._trap_count}: {scenario['label']} from {trap_entry['source_ip']}")
        return trap_entry

    # -- Public helpers (used by REST API) --

    def get(self, oid: str) -> Optional[Any]:
        """Get value for an OID."""
        return self._oid_data.get(oid)

    def walk(self, base_oid: str) -> Dict[str, Any]:
        """Walk all OIDs under a base."""
        result = {}
        for oid, value in self._oid_data.items():
            if oid.startswith(base_oid):
                result[oid] = value
        return result

    def get_all_data(self) -> Dict[str, Any]:
        """Get all OID data."""
        return self._oid_data.copy()
