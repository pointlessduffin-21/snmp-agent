"""
Configuration management for SNMP Agent Server.

Loads configuration from YAML files and environment variables.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional
import yaml


@dataclass
class SNMPConfig:
    """SNMP agent configuration."""
    
    port: int = 1161  # Non-privileged port by default
    community_read: str = "public"
    community_write: str = "private"
    enable_v3: bool = False
    v3_username: str = ""
    v3_auth_key: str = ""
    v3_priv_key: str = ""
    v3_auth_protocol: str = "SHA"  # MD5 or SHA
    v3_priv_protocol: str = "AES"  # DES or AES
    enterprise_oid: str = "1.3.6.1.4.1.99999"  # Custom enterprise OID


@dataclass
class DiscoveryConfig:
    """Network discovery configuration."""
    
    enabled: bool = True
    scan_interval_seconds: int = 300  # 5 minutes
    subnets: List[str] = field(default_factory=lambda: ["192.168.1.0/24"])
    static_hosts: List[str] = field(default_factory=list)
    ping_timeout_ms: int = 1000
    ping_count: int = 1
    use_arp_scan: bool = True
    exclude_ips: List[str] = field(default_factory=list)


@dataclass
class CollectionConfig:
    """Metrics collection configuration."""
    
    interval_seconds: int = 60
    timeout_seconds: int = 30
    collect_local: bool = True
    collect_remote_snmp: bool = True
    collect_remote_ssh: bool = False
    snmp_community: str = "public"
    snmp_port: int = 161
    ssh_username: str = ""
    ssh_key_path: str = ""
    ssh_password: str = ""  # Note: Use key-based auth in production


@dataclass
class LoggingConfig:
    """Logging configuration."""
    
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_path: Optional[str] = None
    max_file_size_mb: int = 10
    backup_count: int = 5


@dataclass
class MQTTConfig:
    """MQTT Broker configuration."""
    
    enabled: bool = False
    port: int = 1883
    host: str = "0.0.0.0"
    websocket_port: int = 9001
    publish_metrics: bool = True
    topic_prefix: str = "snmp-agent/metrics"


@dataclass
class Config:
    """Main configuration container."""
    
    snmp: SNMPConfig = field(default_factory=SNMPConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    collection: CollectionConfig = field(default_factory=CollectionConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    mqtt: MQTTConfig = field(default_factory=MQTTConfig)
    
    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        """Load configuration from YAML file."""
        config_path = Path(path)
        if not config_path.exists():
            return cls()
        
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}
        
        return cls._from_dict(data)
    
    @classmethod
    def _from_dict(cls, data: dict) -> "Config":
        """Create config from dictionary."""
        config = cls()
        
        if "snmp" in data:
            config.snmp = SNMPConfig(**data["snmp"])
        
        if "discovery" in data:
            config.discovery = DiscoveryConfig(**data["discovery"])
        
        if "collection" in data:
            config.collection = CollectionConfig(**data["collection"])
        
        if "logging" in data:
            config.logging = LoggingConfig(**data["logging"])

        if "mqtt" in data:
            config.mqtt = MQTTConfig(**data["mqtt"])
        
        # Override with environment variables
        config._apply_env_overrides()
        
        return config
    
    def _apply_env_overrides(self):
        """Apply environment variable overrides."""
        # SNMP settings
        if os.getenv("SNMP_PORT"):
            self.snmp.port = int(os.getenv("SNMP_PORT"))
        if os.getenv("SNMP_COMMUNITY_READ"):
            self.snmp.community_read = os.getenv("SNMP_COMMUNITY_READ")
        if os.getenv("SNMP_COMMUNITY_WRITE"):
            self.snmp.community_write = os.getenv("SNMP_COMMUNITY_WRITE")
        
        # V3 settings
        if os.getenv("SNMP_V3_USER"):
            self.snmp.enable_v3 = True
            self.snmp.v3_username = os.getenv("SNMP_V3_USER")
        if os.getenv("SNMP_V3_AUTH_KEY"):
            self.snmp.v3_auth_key = os.getenv("SNMP_V3_AUTH_KEY")
        if os.getenv("SNMP_V3_PRIV_KEY"):
            self.snmp.v3_priv_key = os.getenv("SNMP_V3_PRIV_KEY")
        
        # Discovery settings
        if os.getenv("DISCOVERY_SUBNETS"):
            self.discovery.subnets = os.getenv("DISCOVERY_SUBNETS").split(",")
        if os.getenv("DISCOVERY_STATIC_HOSTS"):
            self.discovery.static_hosts = os.getenv("DISCOVERY_STATIC_HOSTS").split(",")
        
        # Collection settings
        if os.getenv("REMOTE_SNMP_COMMUNITY"):
            self.collection.snmp_community = os.getenv("REMOTE_SNMP_COMMUNITY")
        if os.getenv("SSH_USERNAME"):
            self.collection.ssh_username = os.getenv("SSH_USERNAME")
        if os.getenv("SSH_KEY_PATH"):
            self.collection.ssh_key_path = os.getenv("SSH_KEY_PATH")
        
        # MQTT settings
        if os.getenv("MQTT_ENABLED"):
            self.mqtt.enabled = os.getenv("MQTT_ENABLED").lower() == "true"
        if os.getenv("MQTT_PORT"):
            self.mqtt.port = int(os.getenv("MQTT_PORT"))

        # Logging
        if os.getenv("LOG_LEVEL"):
            self.logging.level = os.getenv("LOG_LEVEL")
    
    def to_yaml(self, path: str):
        """Save configuration to YAML file."""
        data = {
            "snmp": {
                "port": self.snmp.port,
                "community_read": self.snmp.community_read,
                "community_write": self.snmp.community_write,
                "enable_v3": self.snmp.enable_v3,
                "enterprise_oid": self.snmp.enterprise_oid,
            },
            "discovery": {
                "enabled": self.discovery.enabled,
                "scan_interval_seconds": self.discovery.scan_interval_seconds,
                "subnets": self.discovery.subnets,
                "static_hosts": self.discovery.static_hosts,
                "use_arp_scan": self.discovery.use_arp_scan,
            },
            "collection": {
                "interval_seconds": self.collection.interval_seconds,
                "timeout_seconds": self.collection.timeout_seconds,
                "collect_local": self.collection.collect_local,
                "collect_remote_snmp": self.collection.collect_remote_snmp,
                "collect_remote_ssh": self.collection.collect_remote_ssh,
                "snmp_community": self.collection.snmp_community,
            },
            "mqtt": {
                "enabled": self.mqtt.enabled,
                "port": self.mqtt.port,
                "host": self.mqtt.host,
                "publish_metrics": self.mqtt.publish_metrics,
                "topic_prefix": self.mqtt.topic_prefix,
            },
            "logging": {
                "level": self.logging.level,
                "file_path": self.logging.file_path,
            },
        }
        
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)


def get_default_config_path() -> str:
    """Get the default configuration file path."""
    # Check common locations
    candidates = [
        Path("config/config.yaml"),
        Path("config.yaml"),
        Path.home() / ".snmp-agent" / "config.yaml",
        Path("/etc/snmp-agent/config.yaml"),
    ]
    
    for path in candidates:
        if path.exists():
            return str(path)
    
    # Return the first candidate as default
    return str(candidates[0])
