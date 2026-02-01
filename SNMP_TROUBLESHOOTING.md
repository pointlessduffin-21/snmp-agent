# SNMP Server Configuration Fix Guide

If you're getting "Cannot connect to SNMP" errors, follow these steps:

## Problem: SNMP daemon running but not accepting connections

### Step 1: Check what snmpd is listening on

```bash
# On the Linux server (192.168.0.100)
sudo ss -tulnp | grep snmpd
```

**Expected output:**

```
udp   BIND   0.0.0.0:161    *:*     users:(("snmpd",pid=...))
```

**If you see:**

```
udp   BIND   127.0.0.1:161  *:*     users:(("snmpd",pid=...))
```

↑ This means it's only listening on localhost!

### Step 2: Fix the configuration

Edit `/etc/snmp/snmpd.conf`:

```bash
sudo nano /etc/snmp/snmpd.conf
```

**Find and comment out this line:**

```conf
# agentAddress  udp:127.0.0.1:161
```

**Add this line instead:**

```conf
agentAddress udp:161,udp6:[::1]:161
```

**Add community access (add these lines anywhere):**

```conf
# Community string for read-only access from your network
rocommunity public 192.168.0.0/24

# Or for specific IPs:
# rocommunity public 192.168.0.117

# System information
syslocation "Server Room"
syscontact Admin <admin@example.com>
```

### Step 3: Restart snmpd

```bash
sudo systemctl restart snmpd
sudo systemctl status snmpd
```

### Step 4: Verify it's listening on the network

```bash
sudo ss -tulnp | grep snmpd
# Should show 0.0.0.0:161 now

# Test locally
snmpwalk -v2c -c public localhost sysDescr
```

### Step 5: Check firewall

```bash
# Ubuntu/Debian
sudo ufw status
sudo ufw allow 161/udp

# Or with iptables
sudo iptables -I INPUT -p udp --dport 161 -j ACCEPT
```

### Step 6: Test from your SNMP agent server

From your Mac running the SNMP agent:

```bash
# Install net-snmp tools if needed
brew install net-snmp

# Test the connection
snmpwalk -v2c -c public 192.168.0.100 sysDescr
```

**Success looks like:**

```
SNMPv2-MIB::sysDescr.0 = STRING: Linux shiela 5.15.0-91-generic ...
```

## Common Issues

### Issue 1: "Timeout: No Response"

- Firewall is blocking port 161
- snmpd listening only on 127.0.0.1
- Wrong IP/subnet in rocommunity

### Issue 2: "No Such Name"

- Community string mismatch
- Check your rocommunity line

### Issue 3: "Authentication failure"

- Wrong community string
- Try: `rocommunity public default` for all IPs (less secure)

## Full Example snmpd.conf

```conf
# /etc/snmp/snmpd.conf

# Listen on all interfaces
agentAddress udp:161,udp6:[::1]:161

# Community string (read-only from your network)
rocommunity public 192.168.0.0/24

# System info
syslocation Server Room
syscontact Admin <admin@example.com>

# Process monitoring
proc  systemd
proc  sshd

# Disk monitoring (optional)
disk / 10000

# Load monitoring (optional)
load 12 10 5

# Default monitoring
includeAllDisks 10%
```

After editing:

```bash
sudo systemctl restart snmpd
```

## Quick Test Script

Save this as `test_snmp.sh` on your server:

```bash
#!/bin/bash
echo "=== SNMP Server Check ==="
echo ""
echo "1. Service status:"
systemctl status snmpd | grep Active

echo ""
echo "2. Listening ports:"
sudo ss -tulnp | grep snmpd

echo ""
echo "3. Local test:"
snmpwalk -v2c -c public localhost sysDescr.0 2>&1 | head -1

echo ""
echo "4. Configuration check:"
grep -E "^agentAddress|^rocommunity" /etc/snmp/snmpd.conf
```

Run with: `bash test_snmp.sh`
