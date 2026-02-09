"""
SNMP Agent Server.

Main SNMP agent implementation that serves aggregated hardware metrics
from all discovered machines on the network.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from pysnmp.hlapi.asyncio import (
    SnmpEngine,
    CommunityData,
    UsmUserData,
    UdpTransportTarget,
    ContextData,
)
from pysnmp.smi import builder, view, compiler
from pysnmp.proto import rfc1902
from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.entity import engine, config
from pysnmp.entity.rfc3413 import cmdrsp, context
from pysnmp.proto.api import v2c

from .mib_definitions import MIBDefinitions, oid_to_tuple, tuple_to_oid
from ..core.models import HardwareSnapshot
from ..core.config import SNMPConfig
from ..core.data_manager import DataManager


logger = logging.getLogger(__name__)


class SNMPAgentServer:
    """
    SNMP Agent Server for hardware metrics aggregation.
    
    Exposes collected hardware metrics via SNMP protocol,
    allowing network management tools to query the data.
    """
    
    def __init__(
        self,
        data_manager: DataManager,
        config: Optional[SNMPConfig] = None,
    ):
        self.data_manager = data_manager
        self.config = config or SNMPConfig()
        self._engine: Optional[engine.SnmpEngine] = None
        self._running = False
        self._start_time = time.time()
        self._mib = MIBDefinitions()
        
        # Cache for OID -> value mapping
        self._oid_cache: Dict[tuple, Any] = {}
        self._cache_lock = asyncio.Lock()
        
        # Index mapping: IP -> machine index
        self._ip_to_index: Dict[str, int] = {}
        
    async def start(self, host: str = "0.0.0.0", port: Optional[int] = None):
        """
        Start the SNMP agent server.
        
        Args:
            host: IP address to bind to
            port: Port to listen on (default from config)
        """
        port = port or self.config.port
        
        logger.info(f"Starting SNMP Agent on {host}:{port}")
        
        # Create SNMP engine
        self._engine = engine.SnmpEngine()
        
        # Configure transport
        config.addTransport(
            self._engine,
            udp.domainName,
            udp.UdpTransport().openServerMode((host, port))
        )
        
        # Configure community strings (SNMPv2c)
        config.addV1System(
            self._engine,
            "read-area",
            self.config.community_read
        )
        
        if self.config.community_write:
            config.addV1System(
                self._engine,
                "write-area",
                self.config.community_write
            )
        
        # Configure SNMPv3 if enabled
        if self.config.enable_v3 and self.config.v3_username:
            auth_protocol = config.usmHMACSHAAuthProtocol
            if self.config.v3_auth_protocol == "MD5":
                auth_protocol = config.usmHMACMD5AuthProtocol
            
            priv_protocol = config.usmAesCfb128Protocol
            if self.config.v3_priv_protocol == "DES":
                priv_protocol = config.usmDESPrivProtocol
            
            config.addV3User(
                self._engine,
                self.config.v3_username,
                auth_protocol,
                self.config.v3_auth_key,
                priv_protocol,
                self.config.v3_priv_key,
            )
        
        # Create SNMP context
        snmp_context = context.SnmpContext(self._engine)
        
        # Register our custom MIB instrumentation
        mib_instrum = self._engine.msgAndPduDsp.mibInstrumController
        
        # Register command responders
        cmdrsp.GetCommandResponder(self._engine, snmp_context)
        cmdrsp.NextCommandResponder(self._engine, snmp_context)
        cmdrsp.BulkCommandResponder(self._engine, snmp_context)
        
        # Start cache update loop
        self._running = True
        asyncio.create_task(self._cache_update_loop())
        
        logger.info(f"SNMP Agent started successfully on port {port}")
        
        # Run the dispatcher
        self._engine.transportDispatcher.jobStarted(1)
        
        try:
            self._engine.transportDispatcher.runDispatcher()
        except Exception as e:
            logger.error(f"SNMP dispatcher error: {e}")
            raise
    
    async def stop(self):
        """Stop the SNMP agent server."""
        logger.info("Stopping SNMP Agent...")
        self._running = False
        
        if self._engine:
            self._engine.transportDispatcher.closeDispatcher()
            self._engine = None
        
        logger.info("SNMP Agent stopped")
    
    async def _cache_update_loop(self):
        """Periodically update the OID cache from data manager."""
        while self._running:
            try:
                await self._update_cache()
            except Exception as e:
                logger.error(f"Cache update error: {e}")
            
            await asyncio.sleep(5)  # Update every 5 seconds
    
    async def _update_cache(self):
        """Update the OID cache with current data."""
        async with self._cache_lock:
            self._oid_cache.clear()
            self._ip_to_index.clear()
            
            snapshots = self.data_manager.snapshots
            
            # Update index mapping
            for idx, ip in enumerate(sorted(snapshots.keys()), start=1):
                self._ip_to_index[ip] = idx
            
            # Agent info scalars
            uptime_ticks = int((time.time() - self._start_time) * 100)
            self._set_oid(MIBDefinitions.AGENT_VERSION, "1.0.0")
            self._set_oid(MIBDefinitions.AGENT_UPTIME, uptime_ticks)
            self._set_oid(MIBDefinitions.MACHINE_COUNT, len(snapshots))
            
            # Build table entries
            for ip, snapshot in snapshots.items():
                idx = self._ip_to_index[ip]
                self._build_machine_entry(idx, snapshot)
                self._build_cpu_entry(idx, snapshot)
                self._build_memory_entry(idx, snapshot)
                self._build_storage_entries(idx, snapshot)
                self._build_power_entry(idx, snapshot)
                self._build_network_entries(idx, snapshot)
                
                # Custom/Rebroadcast OIDs
                if hasattr(snapshot, 'custom_metrics') and snapshot.custom_metrics:
                    for oid, value in snapshot.custom_metrics.items():
                        self._set_oid(oid, value)
    
    def _set_oid(self, oid: str, value: Any):
        """Set an OID value in the cache."""
        oid_tuple = oid_to_tuple(oid)
        self._oid_cache[oid_tuple] = value
    
    def _build_machine_entry(self, idx: int, snapshot: HardwareSnapshot):
        """Build machine table entry."""
        machine = snapshot.machine
        
        self._set_oid(f"{MIBDefinitions.MACHINE_INDEX}.{idx}", idx)
        self._set_oid(f"{MIBDefinitions.MACHINE_IP}.{idx}", machine.ip)
        self._set_oid(f"{MIBDefinitions.MACHINE_HOSTNAME}.{idx}", machine.hostname)
        self._set_oid(f"{MIBDefinitions.MACHINE_OS_TYPE}.{idx}", machine.os_type)
        self._set_oid(f"{MIBDefinitions.MACHINE_UPTIME}.{idx}", machine.uptime_seconds * 100)
        
        # Status: 1=online, 2=offline, 3=unknown
        status = 1 if machine.is_online else 2
        self._set_oid(f"{MIBDefinitions.MACHINE_STATUS}.{idx}", status)
        
        self._set_oid(
            f"{MIBDefinitions.MACHINE_LAST_SEEN}.{idx}",
            machine.last_seen.isoformat()
        )
    
    def _build_cpu_entry(self, idx: int, snapshot: HardwareSnapshot):
        """Build CPU table entry."""
        cpu = snapshot.cpu
        
        self._set_oid(f"{MIBDefinitions.CPU_INDEX}.{idx}", idx)
        self._set_oid(f"{MIBDefinitions.CPU_USAGE_PERCENT}.{idx}", int(cpu.usage_percent))
        self._set_oid(f"{MIBDefinitions.CPU_CORE_COUNT}.{idx}", cpu.core_count)
        self._set_oid(f"{MIBDefinitions.CPU_THREAD_COUNT}.{idx}", cpu.thread_count)
        self._set_oid(f"{MIBDefinitions.CPU_FREQUENCY_MHZ}.{idx}", int(cpu.frequency_mhz))
        
        temp = int(cpu.temperature_celsius) if cpu.temperature_celsius else 0
        self._set_oid(f"{MIBDefinitions.CPU_TEMPERATURE}.{idx}", temp)
        
        self._set_oid(f"{MIBDefinitions.CPU_LOAD_1M}.{idx}", f"{cpu.load_1m:.2f}")
        self._set_oid(f"{MIBDefinitions.CPU_LOAD_5M}.{idx}", f"{cpu.load_5m:.2f}")
        self._set_oid(f"{MIBDefinitions.CPU_LOAD_15M}.{idx}", f"{cpu.load_15m:.2f}")
        self._set_oid(f"{MIBDefinitions.CPU_MODEL}.{idx}", cpu.model_name)
    
    def _build_memory_entry(self, idx: int, snapshot: HardwareSnapshot):
        """Build memory table entry."""
        mem = snapshot.memory
        
        self._set_oid(f"{MIBDefinitions.MEM_INDEX}.{idx}", idx)
        self._set_oid(f"{MIBDefinitions.MEM_TOTAL_BYTES}.{idx}", mem.total_bytes)
        self._set_oid(f"{MIBDefinitions.MEM_USED_BYTES}.{idx}", mem.used_bytes)
        self._set_oid(f"{MIBDefinitions.MEM_AVAILABLE_BYTES}.{idx}", mem.available_bytes)
        self._set_oid(f"{MIBDefinitions.MEM_USAGE_PERCENT}.{idx}", int(mem.usage_percent))
        self._set_oid(f"{MIBDefinitions.SWAP_TOTAL_BYTES}.{idx}", mem.swap_total_bytes)
        self._set_oid(f"{MIBDefinitions.SWAP_USED_BYTES}.{idx}", mem.swap_used_bytes)
    
    def _build_storage_entries(self, idx: int, snapshot: HardwareSnapshot):
        """Build storage table entries."""
        for dev_idx, device in enumerate(snapshot.storage.devices, start=1):
            storage_idx = f"{idx}.{dev_idx}"
            
            self._set_oid(f"{MIBDefinitions.STORAGE_INDEX}.{storage_idx}", f"{idx}.{dev_idx}")
            self._set_oid(f"{MIBDefinitions.STORAGE_MACHINE_INDEX}.{storage_idx}", idx)
            self._set_oid(f"{MIBDefinitions.STORAGE_DEVICE}.{storage_idx}", device.device)
            self._set_oid(f"{MIBDefinitions.STORAGE_MOUNT_POINT}.{storage_idx}", device.mount_point)
            self._set_oid(f"{MIBDefinitions.STORAGE_FS_TYPE}.{storage_idx}", device.fs_type)
            self._set_oid(f"{MIBDefinitions.STORAGE_TOTAL_BYTES}.{storage_idx}", device.total_bytes)
            self._set_oid(f"{MIBDefinitions.STORAGE_USED_BYTES}.{storage_idx}", device.used_bytes)
            self._set_oid(f"{MIBDefinitions.STORAGE_FREE_BYTES}.{storage_idx}", device.free_bytes)
            self._set_oid(f"{MIBDefinitions.STORAGE_USAGE_PERCENT}.{storage_idx}", int(device.usage_percent))
    
    def _build_power_entry(self, idx: int, snapshot: HardwareSnapshot):
        """Build power table entry."""
        power = snapshot.power
        
        self._set_oid(f"{MIBDefinitions.POWER_INDEX}.{idx}", idx)
        
        cpu_watts = int(power.cpu_power_watts * 100) if power.cpu_power_watts else 0
        self._set_oid(f"{MIBDefinitions.POWER_CPU_WATTS}.{idx}", cpu_watts)
        
        battery = int(power.battery_percent) if power.battery_percent else 0
        self._set_oid(f"{MIBDefinitions.POWER_BATTERY_PERCENT}.{idx}", battery)
        
        plugged = 1 if power.is_plugged_in else 0 if power.is_plugged_in is False else -1
        self._set_oid(f"{MIBDefinitions.POWER_PLUGGED_IN}.{idx}", plugged)
    
    def _build_network_entries(self, idx: int, snapshot: HardwareSnapshot):
        """Build network table entries."""
        for net_idx, iface in enumerate(snapshot.network.interfaces, start=1):
            net_key = f"{idx}.{net_idx}"
            
            self._set_oid(f"{MIBDefinitions.NET_INDEX}.{net_key}", f"{idx}.{net_idx}")
            self._set_oid(f"{MIBDefinitions.NET_MACHINE_INDEX}.{net_key}", idx)
            self._set_oid(f"{MIBDefinitions.NET_INTERFACE_NAME}.{net_key}", iface.name)
            self._set_oid(f"{MIBDefinitions.NET_IP_ADDRESS}.{net_key}", iface.ipv4_address)
            self._set_oid(f"{MIBDefinitions.NET_MAC_ADDRESS}.{net_key}", iface.mac_address)
            self._set_oid(f"{MIBDefinitions.NET_BYTES_SENT}.{net_key}", iface.bytes_sent)
            self._set_oid(f"{MIBDefinitions.NET_BYTES_RECV}.{net_key}", iface.bytes_recv)
    
    def get_oid_value(self, oid: str) -> Optional[Any]:
        """Get the value for an OID."""
        oid_tuple = oid_to_tuple(oid)
        return self._oid_cache.get(oid_tuple)
    
    def get_next_oid(self, oid: str) -> Optional[Tuple[str, Any]]:
        """Get the next OID in lexicographic order."""
        oid_tuple = oid_to_tuple(oid)
        
        # Find the next OID
        sorted_oids = sorted(self._oid_cache.keys())
        
        for candidate in sorted_oids:
            if candidate > oid_tuple:
                return (tuple_to_oid(candidate), self._oid_cache[candidate])
        
        return None
    
    def walk_subtree(self, base_oid: str) -> List[Tuple[str, Any]]:
        """Walk all OIDs under a base OID."""
        base_tuple = oid_to_tuple(base_oid)
        results = []
        
        for oid_tuple, value in sorted(self._oid_cache.items()):
            if oid_tuple[:len(base_tuple)] == base_tuple:
                results.append((tuple_to_oid(oid_tuple), value))
        
        return results
    
    @property
    def is_running(self) -> bool:
        """Check if the agent is running."""
        return self._running
    
    @property
    def uptime_seconds(self) -> float:
        """Get agent uptime in seconds."""
        return time.time() - self._start_time


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


class SimpleSNMPAgent:
    """
    SNMP agent that serves aggregated hardware metrics over UDP.

    Listens on a UDP port and responds to SNMPv2c GET, GETNEXT,
    and GETBULK requests using collected metrics data.
    """

    def __init__(self, data_manager: DataManager, port: int = 1161):
        self.data_manager = data_manager
        self.port = port
        self._udp_transport = None
        self._running = False
        self._start_time = time.time()
        self._mib = MIBDefinitions()
        self._oid_data: Dict[str, Any] = {}
        self._sorted_oids: List[str] = []
        self._ip_to_index: Dict[str, int] = {}

    async def start(self):
        """Start the SNMP agent with a real UDP server."""
        logger.info(f"Starting SNMP Agent on UDP port {self.port}")

        self._running = True
        asyncio.create_task(self._update_loop())

        # Wait for first data update so we have OIDs to serve
        self._update_data()

        # Bind UDP socket
        loop = asyncio.get_event_loop()
        self._udp_transport, _ = await loop.create_datagram_endpoint(
            lambda: _SNMPProtocol(self),
            local_addr=("0.0.0.0", self.port),
        )
        logger.info(f"SNMP Agent listening on UDP port {self.port}")

    async def stop(self):
        """Stop the agent."""
        self._running = False
        if self._udp_transport:
            self._udp_transport.close()
            self._udp_transport = None
        logger.info("SNMP Agent stopped")

    async def _update_loop(self):
        """Update data periodically."""
        while self._running:
            self._update_data()
            await asyncio.sleep(5)

    def _update_data(self):
        """Update OID data from snapshots."""
        self._oid_data.clear()
        self._ip_to_index.clear()

        snapshots = self.data_manager.snapshots

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

    # ── SNMP protocol handling ──────────────────────────────────

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
            if str(community) != "public":
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

            # ── GET ──
            if req_pdu.isSameTypeWith(pMod.GetRequestPDU()):
                for oid, _ in var_binds:
                    oid_str = ".".join(str(x) for x in oid)
                    value = self._oid_data.get(oid_str)
                    if value is not None:
                        rsp_var_binds.append((oid, self._to_snmp_value(value)))
                    else:
                        rsp_var_binds.append((oid, rfc1905.noSuchInstance))

            # ── GETNEXT ──
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

            # ── GETBULK ──
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

    # ── Public helpers (used by REST API) ───────────────────────

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
