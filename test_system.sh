#!/bin/bash
# System Test Script for SNMP Agent
# Tests standalone mode and Docker configurations

# Don't exit on error - we'll handle them explicitly
set +e

echo "======================================"
echo "SNMP Agent System Test"
echo "======================================"
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counter
TESTS_PASSED=0
TESTS_FAILED=0

# Process IDs
SNMP_PID=""
WEB_PID=""

# Function to print test result
print_result() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✓ PASSED${NC}: $2"
        ((TESTS_PASSED++))
    else
        echo -e "${RED}✗ FAILED${NC}: $2"
        ((TESTS_FAILED++))
    fi
}

# Function to cleanup background processes
cleanup() {
    echo ""
    echo "Cleaning up..."
    # Kill specific PIDs if they exist
    [ ! -z "$SNMP_PID" ] && kill $SNMP_PID 2>/dev/null || true
    [ ! -z "$WEB_PID" ] && kill $WEB_PID 2>/dev/null || true
    docker compose down >/dev/null 2>&1 || true
    docker stop snmp-agent-test >/dev/null 2>&1 || true
    docker rm snmp-agent-test >/dev/null 2>&1 || true
}

trap cleanup EXIT

echo "Test 1: Dependencies installed"
echo "------------------------------"
python3 -c "import psutil, pysnmp, paramiko, fastapi, uvicorn" 2>/dev/null
print_result $? "All Python dependencies are installed"
echo ""

echo "Test 2: Local collector test"
echo "-----------------------------"
timeout 15 python3 tests/test_local_collector.py >/dev/null 2>&1
print_result $? "Local collector test runs successfully"
echo ""

echo "Test 3: Standalone SNMP Agent mode"
echo "-----------------------------------"
timeout 10 python3 -m src.main --local-only >/dev/null 2>&1 &
SNMP_PID=$!
sleep 5

# Check if process is still running
if ps -p $SNMP_PID > /dev/null 2>&1; then
    kill $SNMP_PID 2>/dev/null || true
    wait $SNMP_PID 2>/dev/null || true
    print_result 0 "Standalone SNMP agent starts successfully"
else
    print_result 1 "Standalone SNMP agent failed to start"
fi
echo ""

echo "Test 4: Web UI mode"
echo "-------------------"
timeout 10 python3 start_web.py --port 8002 >/dev/null 2>&1 &
WEB_PID=$!
sleep 7

# Check if web server is responding
curl -s http://localhost:8002/api/stats >/dev/null 2>&1
WEB_RESULT=$?

kill $WEB_PID 2>/dev/null || true
wait $WEB_PID 2>/dev/null || true

print_result $WEB_RESULT "Web UI starts and responds to API requests"
echo ""

echo "Test 5: Docker build"
echo "--------------------"
docker build -t snmp-agent:test . >/dev/null 2>&1
print_result $? "Docker image builds successfully"
echo ""

echo "Test 6: Docker container"
echo "------------------------"
docker run -d --name snmp-agent-test -p 8003:8000 -e MQTT_ENABLED=false snmp-agent:test >/dev/null 2>&1
sleep 8

# Check if container is running
docker ps | grep snmp-agent-test >/dev/null 2>&1
CONTAINER_RUNNING=$?

# Check if web server is responding inside container
curl -s http://localhost:8003/api/stats >/dev/null 2>&1
CONTAINER_API=$?

docker stop snmp-agent-test >/dev/null 2>&1
docker rm snmp-agent-test >/dev/null 2>&1

if [ $CONTAINER_RUNNING -eq 0 ] && [ $CONTAINER_API -eq 0 ]; then
    print_result 0 "Docker container runs and serves API"
else
    print_result 1 "Docker container failed to run or serve API"
fi
echo ""

echo "Test 7: Docker Compose"
echo "----------------------"
docker compose up -d >/dev/null 2>&1
sleep 12

# Check if services are running
docker compose ps | grep "snmp-agent-monitor" | grep -E "(running|Up)" >/dev/null 2>&1
COMPOSE_RUNNING=$?

# Check API
curl -s http://localhost:8000/api/stats >/dev/null 2>&1
COMPOSE_API=$?

docker compose down >/dev/null 2>&1

if [ $COMPOSE_RUNNING -eq 0 ] && [ $COMPOSE_API -eq 0 ]; then
    print_result 0 "Docker Compose deployment works"
else
    print_result 1 "Docker Compose deployment failed"
fi
echo ""

echo "======================================"
echo "Test Summary"
echo "======================================"
echo -e "Tests Passed: ${GREEN}${TESTS_PASSED}${NC}"
echo -e "Tests Failed: ${RED}${TESTS_FAILED}${NC}"
echo "======================================"

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}All systems pass!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi
