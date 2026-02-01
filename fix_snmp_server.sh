#!/bin/bash
# Run this on your Linux server (192.168.0.100) to configure SNMP properly

echo "=== Fixing SNMP Configuration ==="

# Backup current config
sudo cp /etc/snmp/snmpd.conf /etc/snmp/snmpd.conf.backup

# Create new config
sudo tee /etc/snmp/snmpd.conf > /dev/null << 'EOF'
# System information
syslocation Server Room
syscontact Admin <admin@example.com>

# Listen on all interfaces
agentAddress udp:161,udp6:[::1]:161

# Full access view (includes all OIDs)
view all included .1

# Community string with full access
rocommunity public default -V all

# Alternative: access from specific subnet
# rocommunity public 192.168.0.0/24 -V all

# Enable disk monitoring
includeAllDisks 10%

# Enable load average monitoring
load 12 10 5

# Enable memory monitoring (automatically enabled)
EOF

echo "Configuration written. Restarting snmpd..."
sudo systemctl restart snmpd

# Wait and test
sleep 2
echo ""
echo "=== Testing SNMP ==="
echo "Load averages:"
snmpwalk -v2c -c public localhost 1.3.6.1.4.1.2021.10.1.3 2>&1 | head -3

echo ""
echo "Memory:"
snmpwalk -v2c -c public localhost 1.3.6.1.4.1.2021.4 2>&1 | head -5

echo ""
echo "CPU/Processor load:"
snmpwalk -v2c -c public localhost hrProcessorLoad 2>&1 | head -5

echo ""
echo "Storage:"
snmpwalk -v2c -c public localhost hrStorageDescr 2>&1 | head -5

echo ""
echo "=== Done! Refresh the web UI to see updated metrics ==="
