import sqlite3
import json
import logging
import threading
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Manages SQLite database for persistence."""
    
    def __init__(self, db_path: str = "data/snmp_agent.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """Initialize database tables."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Key-Value store for widgets and miscellaneous configs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # MQTT Configuration store
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mqtt_configs (
                    device_ip TEXT PRIMARY KEY,
                    config_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")

    def save_mqtt_config(self, device_ip: str, config: Dict[str, Any]):
        """Save MQTT configuration for a device."""
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO mqtt_configs (device_ip, config_json)
                VALUES (?, ?)
            """, (device_ip, json.dumps(config)))
            conn.commit()

    def get_mqtt_configs(self) -> Dict[str, Dict]:
        """Load all MQTT configurations."""
        configs = {}
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT device_ip, config_json FROM mqtt_configs")
            rows = cursor.fetchall()
            
            for ip, config_json in rows:
                try:
                    configs[ip] = json.loads(config_json)
                except json.JSONDecodeError:
                    logger.error(f"Failed to decode MQTT config for {ip}")
        return configs

    def delete_mqtt_config(self, device_ip: str):
        """Delete MQTT configuration for a device."""
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM mqtt_configs WHERE device_ip = ?", (device_ip,))
            conn.commit()

    def save_widget_config(self, widget_id: str, config: Dict[str, Any]):
        """Save widget configuration."""
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO kv_store (key, value)
                VALUES (?, ?)
            """, (f"widget:{widget_id}", json.dumps(config)))
            conn.commit()

    def get_widget_configs(self) -> Dict[str, Dict]:
        """Load all widget configurations."""
        widgets = {}
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM kv_store WHERE key LIKE 'widget:%'")
            rows = cursor.fetchall()
            
            for key, value_json in rows:
                widget_id = key.split(":", 1)[1]
                try:
                    widgets[widget_id] = json.loads(value_json)
                except json.JSONDecodeError:
                    logger.error(f"Failed to decode widget config for {widget_id}")
        return widgets

    def delete_widget_config(self, widget_id: str):
        """Delete widget configuration."""
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM kv_store WHERE key = ?", (f"widget:{widget_id}",))
            conn.commit()
