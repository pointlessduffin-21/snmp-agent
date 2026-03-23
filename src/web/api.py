"""
FastAPI Web Server for SNMP Agent Monitoring.

Provides REST API and web UI for:
- Device discovery and management
- Real-time metrics visualization
- Configuration control
- Selective metric reporting
"""

import asyncio
import logging
import json
from datetime import datetime
from typing import List, Dict, Optional, Any
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from ..core.models import MachineInfo, HardwareSnapshot
from ..core.config import Config
from ..core.data_manager import DataManager
from ..core.database import DatabaseManager
from ..core.hostname_resolver import get_vendor_from_mac
from ..discovery.network_scanner import NetworkScanner
from ..collectors.local_collector import LocalCollector
from ..collectors.snmp_collector import SNMPCollector
from ..collectors.ssh_collector import SSHCollector
from ..services.mqtt_broker import MQTTBrokerService
from ..agent.snmp_agent import SimpleSNMPAgent


logger = logging.getLogger(__name__)


# Pydantic models for API
class DeviceInfo(BaseModel):
    ip: str
    hostname: str
    os_type: str
    uptime_seconds: int
    is_online: bool
    last_seen: str
    collection_method: str
    mac_address: str = ""
    vendor: str = ""
    snmp_active: bool = False
    dns_name: str = ""
    mdns_name: str = ""
    netbios_name: str = ""
    snmp_sysname: str = ""
    display_name: str = ""


class CPUInfo(BaseModel):
    usage_percent: float
    core_count: int
    thread_count: int
    frequency_mhz: float
    temperature_celsius: Optional[float]
    load_1m: float
    load_5m: float
    load_15m: float
    model_name: str


class MemoryInfo(BaseModel):
    total_gb: float
    used_gb: float
    available_gb: float
    usage_percent: float
    swap_total_gb: float
    swap_used_gb: float


class StorageDeviceInfo(BaseModel):
    device: str
    mount_point: str
    fs_type: str
    total_gb: float
    used_gb: float
    free_gb: float
    usage_percent: float
    is_ssd: bool


class DeviceMetrics(BaseModel):
    device: DeviceInfo
    cpu: CPUInfo
    memory: MemoryInfo
    storage: List[StorageDeviceInfo]
    timestamp: str


class ScanRequest(BaseModel):
    subnets: List[str]
    timeout_ms: int = 1000


class ConfigUpdate(BaseModel):
    collection_interval: Optional[int] = None
    discovery_enabled: Optional[bool] = None
    collect_remote_snmp: Optional[bool] = None
    snmp_community: Optional[str] = None


class WidgetCreate(BaseModel):
    device_ip: str
    oid: str
    name: str
    display_type: str = "text"


class MQTTDeviceConfig(BaseModel):
    device_ip: str
    enabled: bool = False
    topic: Optional[str] = None
    publish_cpu: bool = True
    publish_memory: bool = True
    publish_storage: bool = True
    publish_widgets: bool = True


class OIDScanRequest(BaseModel):
    base_oids: Optional[List[str]] = None
    max_results: int = 500
    timeout: float = 10.0


class OIDValue(BaseModel):
    oid: str
    name: str
    value: str
    value_type: str


class OIDScanResponse(BaseModel):
    ip: str
    scan_time: str
    total_oids: int
    categories: Dict[str, List[OIDValue]]


class OIDGetRequest(BaseModel):
    oids: List[str]


class OIDWalkRequest(BaseModel):
    base_oid: str
    max_results: int = 100


# Common MIB OID prefixes for scanning
COMMON_MIB_OIDS = {
    "system": ("1.3.6.1.2.1.1", "System MIB - hostname, description, uptime, contact"),
    "interfaces": ("1.3.6.1.2.1.2", "Interface MIB - network interfaces"),
    "ip": ("1.3.6.1.2.1.4", "IP MIB - IP statistics"),
    "tcp": ("1.3.6.1.2.1.6", "TCP MIB - TCP statistics"),
    "udp": ("1.3.6.1.2.1.7", "UDP MIB - UDP statistics"),
    "host_resources": ("1.3.6.1.2.1.25", "Host Resources MIB - CPU, memory, storage, processes"),
    "ucd_snmp": ("1.3.6.1.4.1.2021", "UCD-SNMP MIB - Linux load, memory, disk, extend"),
    "net_snmp_extend": ("1.3.6.1.4.1.8072.1.3.2", "NET-SNMP Extend - custom scripts"),
    "lm_sensors": ("1.3.6.1.4.1.2021.13.16", "LM-SENSORS - temperature, voltage, fan"),
}

OID_NAMES = {
    "1.3.6.1.2.1.1.1.0": "sysDescr",
    "1.3.6.1.2.1.1.3.0": "sysUpTime",
    "1.3.6.1.2.1.1.5.0": "sysName",
    "1.3.6.1.2.1.1.6.0": "sysLocation",
    "1.3.6.1.2.1.25.3.3.1.2": "hrProcessorLoad",
    "1.3.6.1.2.1.25.2.3.1.3": "hrStorageDescr",
    "1.3.6.1.2.1.25.2.3.1.5": "hrStorageSize",
    "1.3.6.1.2.1.25.2.3.1.6": "hrStorageUsed",
    "1.3.6.1.4.1.2021.10.1.3.1": "laLoad.1min",
    "1.3.6.1.4.1.2021.10.1.3.2": "laLoad.5min",
    "1.3.6.1.4.1.2021.10.1.3.3": "laLoad.15min",
    "1.3.6.1.4.1.2021.4.5.0": "memTotalReal",
    "1.3.6.1.4.1.2021.4.6.0": "memAvailReal",
    "1.3.6.1.4.1.2021.4.11.0": "memTotalFree",
    "1.3.6.1.4.1.2021.4.14.0": "memBuffers",
    "1.3.6.1.4.1.2021.4.15.0": "memCached",
    "1.3.6.1.4.1.2021.4.3.0": "memSwapTotal",
    "1.3.6.1.4.1.2021.4.4.0": "memSwapAvail",
    "1.3.6.1.4.1.2021.11.9.0": "ssCpuUser",
    "1.3.6.1.4.1.2021.11.10.0": "ssCpuSystem",
    "1.3.6.1.4.1.2021.11.11.0": "ssCpuIdle",
}


def get_oid_name(oid: str) -> str:
    """Get human-readable name for an OID."""
    if oid in OID_NAMES:
        return OID_NAMES[oid]
    parts = oid.rsplit('.', 1)
    if len(parts) == 2 and parts[0] in OID_NAMES:
        return f"{OID_NAMES[parts[0]]}.{parts[1]}"
    for known_oid, name in OID_NAMES.items():
        if oid.startswith(known_oid):
            suffix = oid[len(known_oid):]
            return f"{name}{suffix}"
    return oid


def categorize_oid(oid: str) -> str:
    """Categorize an OID based on its prefix."""
    for category, (prefix, _) in COMMON_MIB_OIDS.items():
        if oid.startswith(prefix):
            return category
    return "other"


def _build_device_info(m: MachineInfo) -> DeviceInfo:
    """Build DeviceInfo from MachineInfo, enriching vendor if needed."""
    mac = m.mac_address
    vendor = m.vendor
    if mac and (not vendor or vendor == "Unknown"):
        looked_up = get_vendor_from_mac(mac)
        if looked_up and looked_up != "Unknown":
            vendor = looked_up
    if not vendor:
        vendor = "Unknown"

    return DeviceInfo(
        ip=m.ip,
        hostname=m.hostname,
        os_type=m.os_type,
        uptime_seconds=m.uptime_seconds,
        is_online=m.is_online,
        last_seen=m.last_seen.isoformat(),
        collection_method=m.collection_method,
        mac_address=mac,
        vendor=vendor,
        snmp_active=m.snmp_active,
        dns_name=m.dns_name,
        mdns_name=m.mdns_name,
        netbios_name=m.netbios_name,
        snmp_sysname=m.snmp_sysname,
        display_name=m.display_name,
    )


async def _publish_snapshot_mqtt(state, machine_ip: str, snapshot: HardwareSnapshot):
    """Publish a snapshot to MQTT if the device is configured for it."""
    mqtt_service = state.mqtt_service
    mqtt_device_configs = state.mqtt_device_configs
    config = state.config

    if not mqtt_service or not mqtt_service._client_connected:
        return

    mqtt_cfg = mqtt_device_configs.get(machine_ip)
    if not mqtt_cfg or not mqtt_cfg.get("enabled"):
        return

    topic = mqtt_cfg.get("topic", f"{config.mqtt.topic_prefix}/{machine_ip}")
    payload = {}

    if mqtt_cfg.get("publish_cpu", True):
        payload["cpu"] = {
            "usage_percent": snapshot.cpu.usage_percent,
            "core_count": snapshot.cpu.core_count,
            "load_1m": snapshot.cpu.load_1m,
            "load_5m": snapshot.cpu.load_5m,
            "load_15m": snapshot.cpu.load_15m,
            "model": snapshot.cpu.model_name,
        }
    if mqtt_cfg.get("publish_memory", True):
        payload["memory"] = {
            "total_bytes": snapshot.memory.total_bytes,
            "used_bytes": snapshot.memory.used_bytes,
            "usage_percent": snapshot.memory.usage_percent,
        }
    if mqtt_cfg.get("publish_storage", True):
        payload["storage"] = {
            "total_bytes": snapshot.storage.total_bytes,
            "used_bytes": snapshot.storage.used_bytes,
            "usage_percent": snapshot.storage.usage_percent,
            "device_count": len(snapshot.storage.devices),
        }

    payload["timestamp"] = snapshot.timestamp.isoformat()
    payload["hostname"] = snapshot.machine.hostname

    await mqtt_service.publish(topic, payload)


# -- Background loops --

async def _discovery_loop(app: FastAPI):
    """Background task for network discovery."""
    state = app.state

    logger.info("Starting discovery loop")
    while state.running and state.config.discovery.enabled:
        try:
            logger.debug("Running network discovery...")
            machines = await state.scanner.discover_all()
            logger.info(f"Discovery found {len(machines)} machines")

            for machine in machines:
                await state.data_manager.add_machine(machine)
        except Exception as e:
            logger.error(f"Discovery error: {e}")

        await asyncio.sleep(state.config.discovery.scan_interval_seconds)


async def _collection_loop(app: FastAPI):
    """Background task for metrics collection (parallelized)."""
    state = app.state
    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(10)

    while state.running:
        try:
            machines = await state.data_manager.get_machines()
            logger.debug(f"Collection loop: processing {len(machines)} machines")

            async def collect_one(machine: MachineInfo):
                async with sem:
                    try:
                        snapshot = None

                        if machine.ip == state.local_collector._local_ip:
                            snapshot = await loop.run_in_executor(
                                None, state.local_collector.collect_all
                            )
                        elif state.config.collection.collect_remote_snmp:
                            snapshot = await state.snmp_collector.collect_all(machine.ip)

                        if not snapshot and state.ssh_collector and state.config.collection.collect_remote_ssh:
                            snapshot = await loop.run_in_executor(
                                None, state.ssh_collector.collect_all, machine.ip
                            )

                        if snapshot:
                            await state.data_manager.update_snapshot(snapshot)
                            await _publish_snapshot_mqtt(state, machine.ip, snapshot)
                    except Exception as e:
                        logger.error(f"Error collecting from {machine.ip}: {e}")

            tasks = [collect_one(m) for m in machines]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Mark stale machines as offline (3 missed collection cycles)
            stale_threshold = state.config.collection.interval_seconds * 3
            await state.data_manager.mark_stale_offline(max_age_seconds=stale_threshold)

        except Exception as e:
            logger.error(f"Collection error: {e}")

        await asyncio.sleep(state.config.collection.interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting web server...")

    config = getattr(app.state, 'config', None)
    if config is None:
        from ..core.config import get_default_config_path
        config_path = get_default_config_path()
        if config_path:
            logger.info(f"Loading configuration from {config_path}")
            config = Config.from_yaml(config_path)
        else:
            config = Config()
    app.state.config = config

    # Initialize database
    db = DatabaseManager()
    app.state.db = db

    # Initialize data manager with DB for persistence
    data_manager = DataManager(config, db=db)
    app.state.data_manager = data_manager

    # Load persisted devices (mark offline until re-confirmed)
    persisted = db.get_all_devices()
    for ip, dev_data in persisted.items():
        last_seen = dev_data.pop("last_seen", None)
        is_online = dev_data.pop("is_online", False)
        machine = MachineInfo(ip=ip, **dev_data)
        machine.is_online = False  # Will be re-confirmed by collection
        if last_seen:
            try:
                machine.last_seen = datetime.fromisoformat(last_seen)
            except (ValueError, TypeError):
                pass
        await data_manager.add_machine(machine)
    if persisted:
        logger.info(f"Loaded {len(persisted)} persisted devices from database")

    # Initialize components
    app.state.scanner = NetworkScanner(config.discovery)
    app.state.local_collector = LocalCollector()
    app.state.snmp_collector = SNMPCollector(
        community=config.collection.snmp_community,
        timeout=config.collection.timeout_seconds,
    )
    app.state.ssh_collector = None
    if config.collection.ssh_username:
        app.state.ssh_collector = SSHCollector(
            username=config.collection.ssh_username,
            password=config.collection.ssh_password,
            key_path=config.collection.ssh_key_path,
        )

    # Load widget and MQTT device configs
    app.state.widgets = db.get_widget_configs()
    app.state.mqtt_device_configs = db.get_mqtt_configs()
    logger.info(f"Loaded {len(app.state.widgets)} widgets and {len(app.state.mqtt_device_configs)} MQTT configs from database")

    # Start MQTT client
    mqtt_service = MQTTBrokerService(config)
    app.state.mqtt_service = mqtt_service
    await mqtt_service.start()

    # Start SNMP Agent
    snmp_agent = SimpleSNMPAgent(
        data_manager,
        config.snmp.port,
        community=config.snmp.community_read,
    )
    app.state.snmp_agent = snmp_agent
    await snmp_agent.start()
    logger.info(f"SNMP Agent started on port {config.snmp.port}")

    # Collect local metrics immediately
    loop = asyncio.get_event_loop()
    local_snapshot = await loop.run_in_executor(None, app.state.local_collector.collect_all)
    await data_manager.update_snapshot(local_snapshot)
    logger.info(f"Local machine: {local_snapshot.machine.hostname}")

    # Collect from static hosts in background
    static_hosts = config.discovery.static_hosts
    if static_hosts:
        logger.info(f"Collecting from static hosts (background): {static_hosts}")
        snmp_coll = app.state.snmp_collector

        async def collect_priority():
            for ip in static_hosts:
                try:
                    snapshot = await snmp_coll.collect_all(ip)
                    if snapshot:
                        await data_manager.update_snapshot(snapshot)
                        logger.info(f"SNMP success: {ip} -> {snapshot.machine.hostname}")
                    else:
                        logger.warning(f"SNMP failed for {ip}: no snapshot returned")
                except Exception as e:
                    logger.error(f"SNMP error for {ip}: {e}")

        asyncio.create_task(collect_priority())

    # Start background tasks
    app.state.running = True
    app.state.discovery_task = asyncio.create_task(_discovery_loop(app))
    app.state.collection_task = asyncio.create_task(_collection_loop(app))

    logger.info("Web server started")

    yield

    # Shutdown
    logger.info("Shutting down web server...")
    app.state.running = False

    if app.state.discovery_task:
        app.state.discovery_task.cancel()
    if app.state.collection_task:
        app.state.collection_task.cancel()

    if app.state.snmp_agent:
        await app.state.snmp_agent.stop()
    if app.state.mqtt_service:
        await app.state.mqtt_service.stop()

    logger.info("Web server shut down")


# Create FastAPI app
app = FastAPI(
    title="SNMP Agent Monitor",
    description="Hardware metrics aggregation and monitoring",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: don't combine allow_credentials with wildcard origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# -- Helper to get state from request --

def _state(request: Request):
    return request.app.state


# -- API Endpoints --

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main dashboard page."""
    html_path = Path(__file__).parent / "static" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(content="""
        <html>
            <head><title>SNMP Agent Monitor</title></head>
            <body>
                <h1>SNMP Agent Monitor</h1>
                <p>Dashboard is loading... If this persists, check static files.</p>
                <p>API Documentation: <a href="/docs">/docs</a></p>
            </body>
        </html>
    """)


@app.get("/device/{ip}", response_class=HTMLResponse)
async def device_page(ip: str):
    """Serve the device detail page."""
    html_path = Path(__file__).parent / "static" / "device.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    raise HTTPException(status_code=404, detail="Device page not found")


@app.get("/api/devices")
async def get_devices(request: Request) -> List[DeviceInfo]:
    """Get list of all discovered devices."""
    s = _state(request)
    machines = await s.data_manager.get_machines()
    return [_build_device_info(m) for m in machines]


@app.get("/api/devices/{ip}/metrics")
async def get_device_metrics(ip: str, request: Request) -> DeviceMetrics:
    """Get current metrics for a specific device."""
    s = _state(request)
    snapshot = await s.data_manager.get_snapshot(ip)

    if not snapshot:
        raise HTTPException(status_code=404, detail="Device not found")

    return DeviceMetrics(
        device=_build_device_info(snapshot.machine),
        cpu=CPUInfo(
            usage_percent=snapshot.cpu.usage_percent,
            core_count=snapshot.cpu.core_count,
            thread_count=snapshot.cpu.thread_count,
            frequency_mhz=snapshot.cpu.frequency_mhz,
            temperature_celsius=snapshot.cpu.temperature_celsius,
            load_1m=snapshot.cpu.load_1m,
            load_5m=snapshot.cpu.load_5m,
            load_15m=snapshot.cpu.load_15m,
            model_name=snapshot.cpu.model_name,
        ),
        memory=MemoryInfo(
            total_gb=snapshot.memory.total_gb,
            used_gb=snapshot.memory.used_gb,
            available_gb=snapshot.memory.available_gb,
            usage_percent=snapshot.memory.usage_percent,
            swap_total_gb=snapshot.memory.swap_total_bytes / (1024**3),
            swap_used_gb=snapshot.memory.swap_used_bytes / (1024**3),
        ),
        storage=[
            StorageDeviceInfo(
                device=d.device,
                mount_point=d.mount_point,
                fs_type=d.fs_type,
                total_gb=d.total_gb,
                used_gb=d.used_gb,
                free_gb=d.free_gb,
                usage_percent=d.usage_percent,
                is_ssd=d.is_ssd,
            )
            for d in snapshot.storage.devices
        ],
        timestamp=snapshot.timestamp.isoformat(),
    )


@app.get("/api/stats")
async def get_aggregated_stats(request: Request) -> Dict[str, Any]:
    """Get aggregated statistics across all devices."""
    s = _state(request)
    return await s.data_manager.get_aggregated_stats()


@app.get("/api/snmp/oids")
async def get_snmp_oids(request: Request, base: Optional[str] = None):
    """Get all OIDs served by the local SNMP agent (mirrored metrics)."""
    s = _state(request)
    if s.snmp_agent is None:
        raise HTTPException(status_code=503, detail="SNMP agent not running")

    if base:
        data = s.snmp_agent.walk(base)
    else:
        data = s.snmp_agent.get_all_data()

    sorted_oids = sorted(data.items(), key=lambda x: tuple(int(p) for p in x[0].split(".") if p))
    return {"total": len(sorted_oids), "oids": {k: v for k, v in sorted_oids}}


@app.get("/api/snmp/traps")
async def get_snmp_traps(request: Request, limit: int = 100, offset: int = 0):
    """Get received SNMP traps (newest first)."""
    s = _state(request)
    if s.snmp_agent is None:
        raise HTTPException(status_code=503, detail="SNMP agent not running")

    traps = s.snmp_agent.get_traps(limit=limit, offset=offset)
    return {
        "total": s.snmp_agent.get_trap_count(),
        "showing": len(traps),
        "offset": offset,
        "traps": traps,
    }


@app.post("/api/snmp/traps/simulate")
async def simulate_snmp_trap(request: Request, trap_type: str = "linkDown"):
    """Simulate an SNMP trap for testing purposes."""
    s = _state(request)
    if s.snmp_agent is None:
        raise HTTPException(status_code=503, detail="SNMP agent not running")

    valid_types = ["linkDown", "linkUp", "coldStart", "authFailure", "cpuHigh", "diskFull"]
    if trap_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid trap type. Valid types: {valid_types}",
        )

    trap = s.snmp_agent.simulate_trap(trap_type)
    return {"message": f"Simulated {trap_type} trap", "trap": trap}


@app.post("/api/snmp/traps/simulate-batch")
async def simulate_batch_traps(request: Request):
    """Simulate a burst of various trap types for demo purposes."""
    s = _state(request)
    if s.snmp_agent is None:
        raise HTTPException(status_code=503, detail="SNMP agent not running")

    trap_types = ["coldStart", "linkUp", "linkDown", "authFailure", "cpuHigh", "diskFull"]
    results = [s.snmp_agent.simulate_trap(tt) for tt in trap_types]
    return {"message": f"Simulated {len(results)} traps", "count": len(results)}


@app.delete("/api/snmp/traps")
async def clear_snmp_traps(request: Request):
    """Clear stored traps."""
    s = _state(request)
    if s.snmp_agent is None:
        raise HTTPException(status_code=503, detail="SNMP agent not running")

    s.snmp_agent.clear_traps()
    return {"message": "Traps cleared"}


@app.post("/api/scan")
async def trigger_scan(req: ScanRequest, request: Request, background_tasks: BackgroundTasks):
    """Trigger a manual network scan."""
    s = _state(request)

    async def do_scan():
        temp_scanner = NetworkScanner(s.config.discovery)
        temp_scanner.config.subnets = req.subnets
        temp_scanner.config.ping_timeout_ms = req.timeout_ms

        machines = await temp_scanner.discover_all()
        for machine in machines:
            await s.data_manager.add_machine(machine)

    background_tasks.add_task(do_scan)
    return {"message": "Scan started", "subnets": req.subnets}


@app.post("/api/config")
async def update_config(update: ConfigUpdate, request: Request):
    """Update collection configuration."""
    s = _state(request)
    if update.collection_interval:
        s.config.collection.interval_seconds = update.collection_interval
    if update.discovery_enabled is not None:
        s.config.discovery.enabled = update.discovery_enabled
    if update.collect_remote_snmp is not None:
        s.config.collection.collect_remote_snmp = update.collect_remote_snmp
    if update.snmp_community:
        s.config.collection.snmp_community = update.snmp_community
        s.snmp_collector = SNMPCollector(
            community=s.config.collection.snmp_community,
            timeout=s.config.collection.timeout_seconds,
        )

    return {"message": "Configuration updated", "config": update.dict(exclude_none=True)}


@app.get("/api/config")
async def get_config(request: Request):
    """Get current configuration."""
    s = _state(request)
    return {
        "collection_interval": s.config.collection.interval_seconds,
        "discovery_enabled": s.config.discovery.enabled,
        "collect_remote_snmp": s.config.collection.collect_remote_snmp,
        "snmp_community": s.config.collection.snmp_community,
        "subnets": s.config.discovery.subnets,
    }


@app.get("/api/mqtt/status")
async def get_mqtt_status(request: Request):
    """Get MQTT broker status."""
    s = _state(request)
    mqtt_service = getattr(s, 'mqtt_service', None)
    config = s.config

    if mqtt_service is None:
        return {
            "enabled": False,
            "status": "not_initialized",
            "port": None,
            "clients": 0,
        }

    return {
        "enabled": config.mqtt.enabled,
        "status": "connected" if mqtt_service._client_connected else ("stopped" if config.mqtt.enabled else "disabled"),
        "host": config.mqtt.host,
        "port": config.mqtt.port,
        "topic_prefix": config.mqtt.topic_prefix,
        "connected": mqtt_service._client_connected,
    }


# -- Widget CRUD --

@app.get("/api/widgets")
async def list_widgets(request: Request, device_ip: Optional[str] = None):
    """List all widgets, optionally filtered by device IP."""
    s = _state(request)
    if device_ip:
        return [w for w in s.widgets.values() if w.get("device_ip") == device_ip or w.get("device_ip") == "*"]
    return list(s.widgets.values())


@app.post("/api/widgets")
async def create_widget(widget: WidgetCreate, request: Request):
    """Create a new custom widget."""
    import uuid
    s = _state(request)
    widget_id = str(uuid.uuid4())[:8]
    widget_data = {
        "id": widget_id,
        "device_ip": widget.device_ip,
        "oid": widget.oid,
        "name": widget.name,
        "display_type": widget.display_type,
        "created_at": datetime.now().isoformat()
    }
    s.widgets[widget_id] = widget_data
    s.db.save_widget_config(widget_id, widget_data)
    return widget_data


@app.delete("/api/widgets/{widget_id}")
async def delete_widget(widget_id: str, request: Request):
    """Delete a widget."""
    s = _state(request)
    if widget_id not in s.widgets:
        raise HTTPException(status_code=404, detail="Widget not found")
    del s.widgets[widget_id]
    s.db.delete_widget_config(widget_id)
    return {"status": "deleted"}


# -- MQTT Device Configuration --

@app.get("/api/mqtt/devices")
async def list_mqtt_device_configs(request: Request):
    """List all MQTT device configurations."""
    s = _state(request)
    return list(s.mqtt_device_configs.values())


@app.get("/api/mqtt/devices/{device_ip}")
async def get_mqtt_device_config(device_ip: str, request: Request):
    """Get MQTT configuration for a specific device."""
    s = _state(request)
    if device_ip not in s.mqtt_device_configs:
        return {
            "device_ip": device_ip,
            "enabled": False,
            "topic": f"snmp-agent/devices/{device_ip}",
            "publish_cpu": True,
            "publish_memory": True,
            "publish_storage": True,
            "publish_widgets": True
        }
    return s.mqtt_device_configs[device_ip]


@app.post("/api/mqtt/devices")
async def save_mqtt_device_config(config_data: MQTTDeviceConfig, request: Request):
    """Save MQTT configuration for a device."""
    s = _state(request)
    device_ip = config_data.device_ip
    mqtt_config = {
        "device_ip": device_ip,
        "enabled": config_data.enabled,
        "topic": config_data.topic or f"snmp-agent/devices/{device_ip}",
        "publish_cpu": config_data.publish_cpu,
        "publish_memory": config_data.publish_memory,
        "publish_storage": config_data.publish_storage,
        "publish_widgets": config_data.publish_widgets
    }
    s.mqtt_device_configs[device_ip] = mqtt_config
    s.db.save_mqtt_config(device_ip, mqtt_config)
    return mqtt_config


@app.get("/api/stream")
async def stream_updates(request: Request):
    """Server-sent events stream for real-time updates."""
    s = _state(request)

    async def event_generator():
        try:
            while True:
                stats = await s.data_manager.get_aggregated_stats()
                yield f"data: {json.dumps(stats)}\n\n"
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.debug("SSE client disconnected")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# -- OID scanning endpoints --

@app.get("/api/devices/{ip}/oids/categories")
async def get_oid_categories(ip: str):
    """Get available OID categories to scan."""
    return {
        "categories": [
            {"id": cat, "oid_prefix": prefix, "description": desc}
            for cat, (prefix, desc) in COMMON_MIB_OIDS.items()
        ]
    }


@app.post("/api/devices/{ip}/oids/scan")
async def scan_device_oids(ip: str, req: OIDScanRequest, request: Request):
    """Scan a device for available SNMP OIDs."""
    s = _state(request)
    if s.snmp_collector is None:
        raise HTTPException(status_code=503, detail="SNMP collector not initialized")

    base_oids = req.base_oids or [prefix for prefix, _ in COMMON_MIB_OIDS.values()]

    all_results = {}
    categories = {}

    for base_oid in base_oids:
        try:
            results = await s.snmp_collector._walk_oid(ip, base_oid)

            for oid, value in results.items():
                if len(all_results) >= req.max_results:
                    break

                oid_name = get_oid_name(oid)
                category = categorize_oid(oid)

                value_str = str(value)
                value_type = "string"
                try:
                    int(value_str)
                    value_type = "integer"
                except ValueError:
                    try:
                        float(value_str)
                        value_type = "float"
                    except ValueError:
                        pass

                oid_entry = OIDValue(
                    oid=oid,
                    name=oid_name,
                    value=value_str[:200],
                    value_type=value_type,
                )

                if category not in categories:
                    categories[category] = []
                categories[category].append(oid_entry)
                all_results[oid] = oid_entry

        except Exception as e:
            logger.debug(f"Error scanning {base_oid} on {ip}: {e}")

    return OIDScanResponse(
        ip=ip,
        scan_time=datetime.now().isoformat(),
        total_oids=len(all_results),
        categories=categories,
    )


@app.post("/api/devices/{ip}/oids/get")
async def get_oid_values(ip: str, req: OIDGetRequest, request: Request):
    """Get specific OID values from a device."""
    s = _state(request)
    if s.snmp_collector is None:
        raise HTTPException(status_code=503, detail="SNMP collector not initialized")

    results = []
    for oid in req.oids:
        try:
            value = await s.snmp_collector._get_oid(ip, oid)
            if value is not None:
                results.append(OIDValue(
                    oid=oid,
                    name=get_oid_name(oid),
                    value=str(value),
                    value_type="string",
                ))
        except Exception as e:
            logger.debug(f"Error getting OID {oid} from {ip}: {e}")

    return {"ip": ip, "oids": results}


@app.post("/api/devices/{ip}/oids/walk")
async def walk_oid_subtree(ip: str, req: OIDWalkRequest, request: Request):
    """Walk an OID subtree to discover child OIDs."""
    s = _state(request)
    if s.snmp_collector is None:
        raise HTTPException(status_code=503, detail="SNMP collector not initialized")

    try:
        results = await s.snmp_collector._walk_oid(ip, req.base_oid)

        oid_values = []
        for oid, value in list(results.items())[:req.max_results]:
            oid_values.append(OIDValue(
                oid=oid,
                name=get_oid_name(oid),
                value=str(value)[:200],
                value_type="string",
            ))

        return {
            "ip": ip,
            "base_oid": req.base_oid,
            "count": len(oid_values),
            "oids": oid_values,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def start_web_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    app_config: Optional[Config] = None,
):
    """Start the web server."""
    if app_config:
        app.state.config = app_config

    logger.info(f"Starting web server on http://{host}:{port}")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )
