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
from datetime import datetime
from typing import List, Dict, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import json

from ..core.models import HardwareSnapshot
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

# Global state (will be initialized in lifespan)
data_manager: Optional[DataManager] = None
scanner: Optional[NetworkScanner] = None
local_collector: Optional[LocalCollector] = None
snmp_collector: Optional[SNMPCollector] = None
ssh_collector: Optional[SSHCollector] = None
mqtt_service: Optional[MQTTBrokerService] = None
snmp_agent: Optional[SimpleSNMPAgent] = None
db: Optional[DatabaseManager] = None
config: Optional[Config] = None

# Background tasks
_discovery_task: Optional[asyncio.Task] = None
_collection_task: Optional[asyncio.Task] = None
_running = False

# Widget and MQTT device configuration storage
_widgets: Dict[str, Dict] = {}  # widget_id -> widget config
_mqtt_device_configs: Dict[str, Dict] = {}  # device_ip -> mqtt config


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
    # Extended name fields
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global data_manager, scanner, local_collector, snmp_collector, ssh_collector
    global mqtt_service, snmp_agent, db, config
    global _discovery_task, _collection_task, _running

    # Startup
    logger.info("Starting web server...")

    # Initialize with default config if not set
    if config is None:
        from ..core.config import get_default_config_path
        config_path = get_default_config_path()
        if config_path:
            logger.info(f"Loading configuration from {config_path}")
            config = Config.from_yaml(config_path)
        else:
            config = Config()

    data_manager = DataManager(config)
    scanner = NetworkScanner(config.discovery)
    local_collector = LocalCollector()
    snmp_collector = SNMPCollector(
        community=config.collection.snmp_community,
        timeout=config.collection.timeout_seconds,
    )
    if config.collection.ssh_username:
        ssh_collector = SSHCollector(
            username=config.collection.ssh_username,
            password=config.collection.ssh_password,
            key_path=config.collection.ssh_key_path,
        )

    # Initialize database for persistence
    db = DatabaseManager()
    _widgets.update(db.get_widget_configs())
    _mqtt_device_configs.update(db.get_mqtt_configs())
    logger.info(f"Loaded {len(_widgets)} widgets and {len(_mqtt_device_configs)} MQTT configs from database")

    # Initialize and start MQTT client
    mqtt_service = MQTTBrokerService(config)
    await mqtt_service.start()

    # Start SNMP Agent to serve aggregated metrics
    snmp_agent = SimpleSNMPAgent(data_manager, config.snmp.port)
    await snmp_agent.start()
    logger.info(f"SNMP Agent started on port {config.snmp.port}")

    # Collect local metrics immediately (run in executor to avoid blocking)
    loop = asyncio.get_event_loop()
    local_snapshot = await loop.run_in_executor(None, local_collector.collect_all)
    await data_manager.update_snapshot(local_snapshot)
    logger.info(f"Local machine: {local_snapshot.machine.hostname}")

    # Collect from configured static hosts in background
    static_hosts = config.discovery.static_hosts
    if static_hosts:
        logger.info(f"Collecting from static hosts (background): {static_hosts}")

        async def collect_priority():
            for ip in static_hosts:
                try:
                    logger.debug(f"Trying SNMP on {ip}")
                    snapshot = await snmp_collector.collect_all(ip)
                    if snapshot:
                        await data_manager.update_snapshot(snapshot)
                        logger.info(f"SNMP success: {ip} -> {snapshot.machine.hostname}")
                    else:
                        logger.warning(f"SNMP failed for {ip}: no snapshot returned")
                except Exception as e:
                    logger.error(f"SNMP error for {ip}: {e}")

        asyncio.create_task(collect_priority())

    # Start background tasks
    _running = True
    _discovery_task = asyncio.create_task(_discovery_loop())
    _collection_task = asyncio.create_task(_collection_loop())

    logger.info("Web server started")

    yield

    # Shutdown
    logger.info("Shutting down web server...")
    _running = False

    if _discovery_task:
        _discovery_task.cancel()
    if _collection_task:
        _collection_task.cancel()

    # Stop SNMP Agent
    if snmp_agent:
        await snmp_agent.stop()

    # Stop MQTT client
    if mqtt_service:
        await mqtt_service.stop()

    logger.info("Web server shut down")


# Create FastAPI app
app = FastAPI(
    title="SNMP Agent Monitor",
    description="Hardware metrics aggregation and monitoring",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
from pathlib import Path
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# Background loops
async def _discovery_loop():
    """Background task for network discovery."""
    global data_manager, scanner, config
    
    logger.info("Starting discovery loop")
    while _running and config.discovery.enabled:
        try:
            logger.debug("Running network discovery...")
            machines = await scanner.discover_all()
            logger.info(f"Discovery found {len(machines)} machines")

            for machine in machines:
                await data_manager.add_machine(machine)

            logger.debug("Finished adding machines")
        except Exception as e:
            logger.error(f"Discovery error: {e}")
        
        await asyncio.sleep(config.discovery.scan_interval_seconds)


async def _collection_loop():
    """Background task for metrics collection."""
    global data_manager, local_collector, snmp_collector, ssh_collector, config
    
    loop = asyncio.get_event_loop()
    
    while _running:
        try:
            machines = data_manager.machines
            logger.debug(f"Collection loop: processing {len(machines)} machines")
            
            for machine in machines:
                try:
                    snapshot = None
                    
                    if machine.ip == local_collector._local_ip:
                        # Run blocking psutil calls in executor
                        snapshot = await loop.run_in_executor(None, local_collector.collect_all)
                    elif config.collection.collect_remote_snmp:
                        snapshot = await snmp_collector.collect_all(machine.ip)
                    
                    if not snapshot and ssh_collector and config.collection.collect_remote_ssh:
                        # SSH is blocking, run in executor
                        snapshot = await loop.run_in_executor(None, ssh_collector.collect_all, machine.ip)
                    
                    if snapshot:
                        await data_manager.update_snapshot(snapshot)
                        if snapshot.machine.snmp_active:
                            logger.info(f"SNMP collected from {machine.ip}: {snapshot.machine.hostname}")
                        
                except Exception as e:
                    logger.error(f"Error collecting from {machine.ip}: {e}")
            
        except Exception as e:
            logger.error(f"Collection error: {e}")
        
        await asyncio.sleep(config.collection.interval_seconds)


# API Endpoints

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main dashboard page."""
    from pathlib import Path
    html_path = Path(__file__).parent / "static" / "index.html"
    
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    else:
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
    from pathlib import Path
    html_path = Path(__file__).parent / "static" / "device.html"
    
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    else:
        raise HTTPException(status_code=404, detail="Device page not found")


@app.get("/api/test-vendor")
async def test_vendor():
    """Test vendor lookup directly."""
    from ..core.hostname_resolver import OUI_VENDORS, get_vendor_from_mac
    test_macs = ['BC:24:11:B9:AC:38', '84:2F:57:24:50:B6', '98:E7:43:20:F0:44']
    results = {}
    for mac in test_macs:
        vendor = get_vendor_from_mac(mac)
        oui = ":".join(mac.split(":")[:3])
        results[mac] = {
            "vendor": vendor,
            "oui": oui,
            "in_dict": oui in OUI_VENDORS,
        }
    return {
        "oui_count": len(OUI_VENDORS),
        "results": results,
    }


@app.get("/api/devices")
async def get_devices() -> List[DeviceInfo]:
    """Get list of all discovered devices."""
    machines = data_manager.machines
    
    devices = []
    for m in machines:
        # Get MAC and lookup vendor if needed
        mac = m.mac_address if hasattr(m, 'mac_address') else ""
        vendor = m.vendor if hasattr(m, 'vendor') else ""
        
        # Lookup vendor from MAC if not already known
        if mac and (not vendor or vendor == "Unknown"):
            looked_up_vendor = get_vendor_from_mac(mac)
            if looked_up_vendor and looked_up_vendor != "Unknown":
                vendor = looked_up_vendor
        
        # Ensure vendor is never empty
        if not vendor:
            vendor = "Unknown"
        
        devices.append(DeviceInfo(
            ip=m.ip,
            hostname=m.hostname,
            os_type=m.os_type,
            uptime_seconds=m.uptime_seconds,
            is_online=m.is_online,
            last_seen=m.last_seen.isoformat(),
            collection_method=m.collection_method,
            mac_address=mac,
            vendor=vendor,
            snmp_active=m.snmp_active if hasattr(m, 'snmp_active') else False,
            dns_name=m.dns_name if hasattr(m, 'dns_name') else "",
            mdns_name=m.mdns_name if hasattr(m, 'mdns_name') else "",
            netbios_name=m.netbios_name if hasattr(m, 'netbios_name') else "",
            snmp_sysname=m.snmp_sysname if hasattr(m, 'snmp_sysname') else "",
            display_name=m.display_name if hasattr(m, 'display_name') else m.hostname,
        ))
    
    return devices


@app.get("/api/debug/vendor/{mac}")
async def debug_vendor_lookup(mac: str):
    """Debug endpoint to test vendor lookup."""
    from ..core.hostname_resolver import OUI_VENDORS
    result = get_vendor_from_mac(mac)
    normalized_mac = mac.upper().replace("-", ":")
    oui = ":".join(normalized_mac.split(":")[:3])
    return {
        "input_mac": mac,
        "normalized": normalized_mac,
        "oui": oui,
        "lookup_result": result,
        "oui_in_dict": oui in OUI_VENDORS,
        "dict_size": len(OUI_VENDORS),
    }


@app.get("/api/devices/{ip}/metrics")
async def get_device_metrics(ip: str) -> DeviceMetrics:
    """Get current metrics for a specific device."""
    snapshot = data_manager.get_snapshot(ip)
    
    if not snapshot:
        raise HTTPException(status_code=404, detail="Device not found")
    
    return DeviceMetrics(
        device=DeviceInfo(
            ip=snapshot.machine.ip,
            hostname=snapshot.machine.hostname,
            os_type=snapshot.machine.os_type,
            uptime_seconds=snapshot.machine.uptime_seconds,
            is_online=snapshot.machine.is_online,
            last_seen=snapshot.machine.last_seen.isoformat(),
            collection_method=snapshot.machine.collection_method,
        ),
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
async def get_aggregated_stats() -> Dict[str, Any]:
    """Get aggregated statistics across all devices."""
    return data_manager.get_aggregated_stats()


@app.get("/api/snmp/oids")
async def get_snmp_oids(base: Optional[str] = None):
    """Get all OIDs served by the local SNMP agent (mirrored metrics)."""
    if snmp_agent is None:
        raise HTTPException(status_code=503, detail="SNMP agent not running")

    if base:
        data = snmp_agent.walk(base)
    else:
        data = snmp_agent.get_all_data()

    # Sort by OID for readable output
    sorted_oids = sorted(data.items(), key=lambda x: tuple(int(p) for p in x[0].split(".") if p))
    return {"total": len(sorted_oids), "oids": {k: v for k, v in sorted_oids}}


@app.post("/api/scan")
async def trigger_scan(request: ScanRequest, background_tasks: BackgroundTasks):
    """Trigger a manual network scan."""
    
    async def do_scan():
        temp_scanner = NetworkScanner(config.discovery)
        temp_scanner.config.subnets = request.subnets
        temp_scanner.config.ping_timeout_ms = request.timeout_ms
        
        machines = await temp_scanner.discover_all()
        
        for machine in machines:
            await data_manager.add_machine(machine)
    
    background_tasks.add_task(do_scan)
    
    return {"message": "Scan started", "subnets": request.subnets}


@app.post("/api/config")
async def update_config(update: ConfigUpdate):
    """Update collection configuration."""
    if update.collection_interval:
        config.collection.interval_seconds = update.collection_interval
    if update.discovery_enabled is not None:
        config.discovery.enabled = update.discovery_enabled
    if update.collect_remote_snmp is not None:
        config.collection.collect_remote_snmp = update.collect_remote_snmp
    if update.snmp_community:
        config.collection.snmp_community = update.snmp_community
        # Update collector
        global snmp_collector
        snmp_collector = SNMPCollector(
            community=config.collection.snmp_community,
            timeout=config.collection.timeout_seconds,
        )
    
    return {"message": "Configuration updated", "config": update.dict(exclude_none=True)}


@app.get("/api/config")
async def get_config():
    """Get current configuration."""
    return {
        "collection_interval": config.collection.interval_seconds,
        "discovery_enabled": config.discovery.enabled,
        "collect_remote_snmp": config.collection.collect_remote_snmp,
        "snmp_community": config.collection.snmp_community,
        "subnets": config.discovery.subnets,
    }


@app.get("/api/mqtt/status")
async def get_mqtt_status():
    """Get MQTT broker status."""
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


# Widget Models
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


# Widget CRUD endpoints
@app.get("/api/widgets")
async def list_widgets(device_ip: Optional[str] = None):
    """List all widgets, optionally filtered by device IP."""
    if device_ip:
        return [w for w in _widgets.values() if w.get("device_ip") == device_ip or w.get("device_ip") == "*"]
    return list(_widgets.values())


@app.post("/api/widgets")
async def create_widget(widget: WidgetCreate):
    """Create a new custom widget."""
    import uuid
    widget_id = str(uuid.uuid4())[:8]
    widget_data = {
        "id": widget_id,
        "device_ip": widget.device_ip,
        "oid": widget.oid,
        "name": widget.name,
        "display_type": widget.display_type,
        "created_at": datetime.now().isoformat()
    }
    _widgets[widget_id] = widget_data
    if db:
        db.save_widget_config(widget_id, widget_data)
    return widget_data


@app.delete("/api/widgets/{widget_id}")
async def delete_widget(widget_id: str):
    """Delete a widget."""
    if widget_id not in _widgets:
        raise HTTPException(status_code=404, detail="Widget not found")
    del _widgets[widget_id]
    if db:
        db.delete_widget_config(widget_id)
    return {"status": "deleted"}


# MQTT Device Configuration endpoints
@app.get("/api/mqtt/devices")
async def list_mqtt_device_configs():
    """List all MQTT device configurations."""
    return list(_mqtt_device_configs.values())


@app.get("/api/mqtt/devices/{device_ip}")
async def get_mqtt_device_config(device_ip: str):
    """Get MQTT configuration for a specific device."""
    if device_ip not in _mqtt_device_configs:
        # Return default config
        return {
            "device_ip": device_ip,
            "enabled": False,
            "topic": f"snmp-agent/devices/{device_ip}",
            "publish_cpu": True,
            "publish_memory": True,
            "publish_storage": True,
            "publish_widgets": True
        }
    return _mqtt_device_configs[device_ip]


@app.post("/api/mqtt/devices")
async def save_mqtt_device_config(config_data: MQTTDeviceConfig):
    """Save MQTT configuration for a device."""
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
    _mqtt_device_configs[device_ip] = mqtt_config
    if db:
        db.save_mqtt_config(device_ip, mqtt_config)
    return mqtt_config


@app.get("/api/stream")
async def stream_updates():
    """Server-sent events stream for real-time updates."""
    
    async def event_generator():
        while True:
            # Send current stats every 5 seconds
            stats = data_manager.get_aggregated_stats()
            yield f"data: {json.dumps(stats)}\n\n"
            await asyncio.sleep(5)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# OID request/response models
class OIDScanRequest(BaseModel):
    base_oids: Optional[List[str]] = None  # If None, scan common MIBs
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

# OID name mappings for common metrics
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
    # Exact match
    if oid in OID_NAMES:
        return OID_NAMES[oid]
    
    # Check for table entries (strip last index)
    parts = oid.rsplit('.', 1)
    if len(parts) == 2:
        base_oid = parts[0]
        if base_oid in OID_NAMES:
            return f"{OID_NAMES[base_oid]}.{parts[1]}"
    
    # Check for prefix match
    for known_oid, name in OID_NAMES.items():
        if oid.startswith(known_oid):
            suffix = oid[len(known_oid):]
            return f"{name}{suffix}"
    
    return oid  # Return OID if no name found

def categorize_oid(oid: str) -> str:
    """Categorize an OID based on its prefix."""
    for category, (prefix, _) in COMMON_MIB_OIDS.items():
        if oid.startswith(prefix):
            return category
    return "other"


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
async def scan_device_oids(ip: str, request: OIDScanRequest):
    """Scan a device for available SNMP OIDs."""
    if snmp_collector is None:
        raise HTTPException(status_code=503, detail="SNMP collector not initialized")
    
    # Choose which OID prefixes to scan
    if request.base_oids:
        base_oids = request.base_oids
    else:
        # Default to common MIBs
        base_oids = [prefix for prefix, _ in COMMON_MIB_OIDS.values()]
    
    all_results = {}
    categories = {}
    
    for base_oid in base_oids:
        try:
            results = await snmp_collector._walk_oid(ip, base_oid)
            
            for oid, value in results.items():
                if len(all_results) >= request.max_results:
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
                    value=value_str[:200],  # Truncate long values
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
async def get_oid_values(ip: str, request: OIDGetRequest):
    """Get specific OID values from a device."""
    if snmp_collector is None:
        raise HTTPException(status_code=503, detail="SNMP collector not initialized")
    
    results = []
    for oid in request.oids:
        try:
            value = await snmp_collector._get_oid(ip, oid)
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
async def walk_oid_subtree(ip: str, request: OIDWalkRequest):
    """Walk an OID subtree to discover child OIDs."""
    if snmp_collector is None:
        raise HTTPException(status_code=503, detail="SNMP collector not initialized")
    
    try:
        results = await snmp_collector._walk_oid(ip, request.base_oid)
        
        oid_values = []
        for oid, value in list(results.items())[:request.max_results]:
            oid_values.append(OIDValue(
                oid=oid,
                name=get_oid_name(oid),
                value=str(value)[:200],
                value_type="string",
            ))
        
        return {
            "ip": ip,
            "base_oid": request.base_oid,
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
    global config
    
    if app_config:
        config = app_config
    
    logger.info(f"Starting web server on http://{host}:{port}")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )
