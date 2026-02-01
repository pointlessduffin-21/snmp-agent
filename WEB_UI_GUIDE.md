# SNMP Agent Server - Web UI Quick Start Guide

## Starting the Web Server

```bash
cd /Users/yeems214/cubeworks/snmp-agent
source venv/bin/activate
python start_web.py
```

The web interface will be available at: **http://localhost:8000**

## What You See

### Dashboard (17 devices discovered)

- Device grid showing all machines found on your network
- Real-time stats: Device count, online status, average CPU
- Dark theme interface with sidebar controls

### Features Available Now

| Feature          | Status     | How to Use                                      |
| ---------------- | ---------- | ----------------------------------------------- |
| **View Devices** | ✅ Working | Grid shows all 17 discovered devices            |
| **Network Scan** | ✅ Working | Click "Scan Network" or enter subnet in sidebar |
| **Refresh Data** | ✅ Working | Manual refresh or auto-updates via SSE          |
| **Filters**      | ✅ Working | Toggle online/offline devices                   |

### To Get Full Hardware Metrics

**Currently:** Devices are discovered via ping (shows IP, status, discovery method)

**For CPU/RAM/Storage data:** Configure SNMP on each remote machine:

#### Linux Devices

```bash
sudo apt install snmpd
sudo nano /etc/snmp/snmpd.conf
# Add: rocommunity public 192.168.0.0/24
sudo systemctl restart snmpd
```

#### Windows Devices

1. Settings → Apps → Optional Features → SNMP Service
2. Configure community string to "public"
3. Allow your server IP

#### Then in Web UI:

1. Click **⚙️ Configuration**
2. Set SNMP Community to "public" (or your custom string)
3. Enable "Collect via SNMP"
4. Save

Devices will now report CPU, memory, storage, power metrics!

## Next Steps

1. **Configure SNMP on your other machines** to unlock full metrics
2. **Click any device card** to see detailed metrics (once SNMP is configured)
3. **Use Quick Scan** to discover more subnets
4. **Adjust collection interval** in Configuration modal

## API Documentation

FastAPI auto-generated docs: **http://localhost:8000/docs**

Available endpoints:

- `GET /api/devices` - List all devices
- `GET /api/devices/{ip}/metrics` - Get device details
- `GET /api/stats` - Aggregated statistics
- `POST /api/scan` - Trigger network scan
- `GET /api/stream` - SSE real-time updates
