# SNMP Agent Server - Environment Variables

# Export these variables before running the server

# SNMP Configuration

export SNMP_PORT=1161
export SNMP_COMMUNITY_READ=public
export SNMP_COMMUNITY_WRITE=private

# SNMPv3 (optional)

# export SNMP_V3_USER=snmpuser

# export SNMP_V3_AUTH_KEY=authpassword

# export SNMP_V3_PRIV_KEY=privpassword

# Discovery

export DISCOVERY_SUBNETS=192.168.1.0/24

# export DISCOVERY_STATIC_HOSTS=192.168.1.100,192.168.1.101

# Remote Collection

export REMOTE_SNMP_COMMUNITY=public

# export SSH_USERNAME=admin

# export SSH_KEY_PATH=/path/to/key

# Logging

export LOG_LEVEL=INFO
