# SNMP Agent Server for Hardware Metrics Aggregation

A Python-based SNMP server that aggregates hardware metrics from all machines in a network and exposes them via the SNMP protocol. Query a single endpoint to get comprehensive hardware information from your entire infrastructure.

## Features

- **Hardware Metrics Collection**
  - CPU: Usage, cores, frequency, temperature, load averages, model
  - Memory: Total, used, available, swap usage
  - Storage: Per-device space, filesystem type, SSD detection
  - Power: CPU power consumption (RAPL), battery status
  - Network: Interface stats, traffic counters

- **Network Discovery**
  - Ping sweep for IP ranges
  - ARP table scanning
  - Static host configuration

- **Multiple Collection Methods**
  - Local collection via `psutil`
  - Remote SNMP (queries existing SNMP agents)
  - SSH-based collection for Linux machines

- **SNMP Protocol Support**
  - SNMPv2c and SNMPv3
  - Custom MIB with hardware-specific OIDs
  - Standard GET, GETNEXT, BULK operations

## Quick Start

### Installation

```bash
# Clone the repository
cd snmp-agent

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Run Local Test

```bash
# Test local hardware collection
python tests/test_local_collector.py
```

### Start the SNMP Agent

```bash
# Start with default settings (local machine only)
python -m src.main --local-only

# Start with network discovery
python -m src.main --subnet 192.168.1.0/24

# Start on custom port with verbose logging
python -m src.main -p 1161 --community mycommunity -v
```

### Query the Agent

```bash
# Get all machines
snmpwalk -v2c -c public localhost:1161 .1.3.6.1.4.1.99999.1.2

# Get CPU metrics
snmpwalk -v2c -c public localhost:1161 .1.3.6.1.4.1.99999.1.3

# Get memory metrics
snmpwalk -v2c -c public localhost:1161 .1.3.6.1.4.1.99999.1.4

# Get storage metrics
snmpwalk -v2c -c public localhost:1161 .1.3.6.1.4.1.99999.1.5
```

## Configuration

### Configuration File

Copy and customize `config/config.yaml`:

```yaml
snmp:
  port: 1161
  community_read: "public"
  enterprise_oid: "1.3.6.1.4.1.99999"

discovery:
  enabled: true
  subnets:
    - "192.168.1.0/24"
  scan_interval_seconds: 300

collection:
  interval_seconds: 60
  collect_local: true
  collect_remote_snmp: true
```

### Environment Variables

```bash
export SNMP_PORT=1161
export SNMP_COMMUNITY_READ=public
export DISCOVERY_SUBNETS=192.168.1.0/24
```

See `env.md` for all available environment variables.

## MIB Structure

The agent exposes hardware metrics under a custom enterprise OID:

```
.1.3.6.1.4.1.99999.1 (hwAggregator)
├── .1 (agentInfo)
│   ├── .1.0 (agentVersion)
│   ├── .2.0 (agentUptime)
│   └── .3.0 (machineCount)
├── .2 (machineTable)
│   └── .1.{index} (machineEntry)
│       ├── .1 (machineIndex)
│       ├── .2 (machineIP)
│       ├── .3 (machineHostname)
│       ├── .4 (machineOSType)
│       ├── .5 (machineUptime)
│       └── .6 (machineStatus)
├── .3 (cpuTable)
│   └── .1.{index}
│       ├── .2 (cpuUsagePercent)
│       ├── .3 (cpuCoreCount)
│       ├── .4 (cpuThreadCount)
│       ├── .5 (cpuFrequencyMHz)
│       ├── .6 (cpuTemperature)
│       └── .7-.9 (loadAverages)
├── .4 (memoryTable)
│   └── .1.{index}
│       ├── .2 (memTotalBytes)
│       ├── .3 (memUsedBytes)
│       ├── .4 (memAvailableBytes)
│       └── .5 (memUsagePercent)
├── .5 (storageTable)
│   └── .1.{machine}.{device}
│       ├── .3 (storageDevice)
│       ├── .6 (storageTotalBytes)
│       ├── .7 (storageUsedBytes)
│       └── .9 (storageUsagePercent)
└── .6 (powerTable)
    └── .1.{index}
        ├── .2 (powerCPUWatts)
        ├── .3 (powerBatteryPercent)
        └── .4 (powerPluggedIn)
```

## Command Line Options

```
usage: python -m src.main [-h] [-c CONFIG] [-p PORT] [--community COMMUNITY]
                          [--subnet SUBNET] [--host HOST] [--local-only] [-v]
                          [--generate-config]

Options:
  -c, --config       Path to configuration file
  -p, --port         SNMP port (default: 1161)
  --community        SNMP community string (default: public)
  --subnet           Subnet to scan (can be repeated)
  --host             Static host to monitor (can be repeated)
  --local-only       Only monitor local machine
  -v, --verbose      Enable debug logging
  --generate-config  Generate sample config file
```

## Requirements

- Python 3.9+
- psutil (hardware metrics)
- pysnmp-lextudio (SNMP protocol)
- paramiko (SSH collection)
- pyyaml (configuration)

## Security Considerations

- Use SNMPv3 for encrypted communication in production
- Run on non-privileged ports (>1024) unless root access is available
- Restrict network access to the SNMP port
- Use strong community strings (not "public")
- For SSH collection, use key-based authentication

## Troubleshooting

### Port 161 Permission Denied

Standard SNMP port (161) requires root privileges. Either:

- Run as root: `sudo python -m src.main -p 161`
- Use a high port: `python -m src.main -p 1161`

### No Machines Discovered

- Check firewall allows ICMP (ping)
- Verify subnet configuration is correct
- Try adding hosts manually with `--host`

### Temperature Not Available

CPU temperature requires:

- Linux: `lm-sensors` package installed
- macOS: Limited support
- Windows: Not available via psutil

### Power Reading Not Available

CPU power (RAPL) requires:

- Linux kernel 3.13+
- Intel CPU with RAPL support
- Root/admin privileges to read `/sys/class/powercap/`

## License

MIT License
