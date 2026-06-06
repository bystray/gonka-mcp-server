#!/bin/bash

#############################################################################
# Gonka MCP Security Monitor
#
# Checks for security issues:
# 1. API keys sent in URL query parameters (via middleware warning logs)
# 2. Service health status
# 3. Recent tool usage patterns
#
# Run: ./monitor_mcp_security.sh [OPTIONS]
#      monitor_mcp_security.sh --continuous    (watch every 5 minutes)
#      monitor_mcp_security.sh --alert-email   (email on issues)
#############################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="gonka-mcp.service"
LOG_DAYS="${LOG_DAYS:-1}"

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

#############################################################################
# Functions
#############################################################################

print_header() {
    echo -e "${BLUE}===================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}===================================================${NC}"
}

print_ok() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

check_service_status() {
    print_header "Service Status"

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        print_ok "MCP service is running"

        # Get PID and uptime
        local pid=$(systemctl show -p MainPID --value "$SERVICE_NAME")
        local since=$(systemctl show -p ActiveEnterTimestamp --value "$SERVICE_NAME")
        echo "  PID: $pid"
        echo "  Since: $since"

        # Memory usage
        if [ -r "/proc/$pid/status" ]; then
            local mem_kb=$(awk '/^VmRSS:/ {print $2}' "/proc/$pid/status")
            local mem_mb=$((mem_kb / 1024))
            echo "  Memory: ${mem_mb}MB"
        fi

        return 0
    else
        print_error "MCP service is NOT running"
        systemctl status "$SERVICE_NAME" || true
        return 1
    fi
}

check_security_issues() {
    print_header "Security Issues"

    local issues=0

    # Check for API keys in query strings (security middleware warnings)
    local key_attempts=$(journalctl -u "$SERVICE_NAME" \
        --since "${LOG_DAYS} days ago" \
        --grep "SECURITY.*api_key" \
        --no-pager 2>/dev/null | wc -l)

    if [ "$key_attempts" -gt 0 ]; then
        print_error "Found $key_attempts attempts to send API key in URL query parameters!"
        print_warn "These indicate misconfigured clients or tests"
        echo "  Recent attempts:"
        journalctl -u "$SERVICE_NAME" \
            --since "${LOG_DAYS} days ago" \
            --grep "SECURITY.*api_key" \
            --no-pager \
            -n 5 2>/dev/null | tail -5 || true
        issues=$((issues + 1))
    else
        print_ok "No API keys detected in URL parameters"
    fi

    # Check for access log entries (should be minimal since we disabled them)
    local access_log_lines=$(journalctl -u "$SERVICE_NAME" \
        --since "${LOG_DAYS} days ago" \
        --grep "HTTP.*200\|HTTP.*404" \
        --no-pager 2>/dev/null | wc -l)

    if [ "$access_log_lines" -gt 0 ]; then
        print_warn "Found $access_log_lines HTTP access log entries (should be minimal)"
        issues=$((issues + 1))
    else
        print_ok "Uvicorn access logging properly disabled"
    fi

    # Check stderr for any auth-related errors
    local auth_errors=$(journalctl -u "$SERVICE_NAME" \
        --since "${LOG_DAYS} days ago" \
        --grep "auth|key|credential|token" \
        --case-sensitive=false \
        --no-pager 2>/dev/null | wc -l)

    if [ "$auth_errors" -gt 0 ]; then
        print_warn "Found $auth_errors log lines mentioning auth/keys (may be normal)"
    else
        print_ok "No authentication-related errors"
    fi

    return $issues
}

check_tool_usage() {
    print_header "Recent Tool Usage"

    # Parse mcp-stats.jsonl for tool calls
    local stats_file="/opt/agentgonka/mcp-stats.jsonl"

    if [ ! -f "$stats_file" ]; then
        print_warn "Stats file not found: $stats_file"
        return 0
    fi

    # Count tool calls in last 24 hours
    local cutoff=$(date -d "24 hours ago" +"%Y-%m-%dT%H:%M:%S")

    # Tools called
    echo "  Tools called (last 24h):"
    jq -r '.tool' "$stats_file" 2>/dev/null | sort | uniq -c | sort -rn | head -10 || true

    # Client IPs
    echo ""
    echo "  Client IPs (last 24h):"
    jq -r '.ip' "$stats_file" 2>/dev/null | sort | uniq -c | sort -rn | head -5 || true

    # Average response time
    echo ""
    echo "  Average response time:"
    local avg_ms=$(jq '.ms' "$stats_file" 2>/dev/null | awk '{sum+=$1; count++} END {if (count>0) print int(sum/count); else print "N/A"}')
    echo "    ${avg_ms}ms"
}

check_disk_space() {
    print_header "Disk Space"

    # Check journal size
    local journal_size=$(du -sh /var/log/journal 2>/dev/null | awk '{print $1}')
    echo "  Journal size: ${journal_size:-N/A}"

    # Check pricing.json
    if [ -f "/var/www/gogonka/pricing.json" ]; then
        local pricing_size=$(stat -f%z "/var/www/gogonka/pricing.json" 2>/dev/null || stat -c%s "/var/www/gogonka/pricing.json" 2>/dev/null || echo "N/A")
        local pricing_mtime=$(stat -f%Sm -t "%Y-%m-%d %H:%M:%S" "/var/www/gogonka/pricing.json" 2>/dev/null || stat -c%y "/var/www/gogonka/pricing.json" 2>/dev/null | cut -d' ' -f1-2 || echo "N/A")
        echo "  Pricing data: $pricing_size bytes (updated: $pricing_mtime)"
        print_ok "Pricing file exists and accessible"
    else
        print_error "Pricing file not found: /var/www/gogonka/pricing.json"
    fi
}

show_alerts() {
    print_header "⚠ Alerts & Recommendations"

    # Check if service has restarted recently
    local restart_count=$(journalctl -u "$SERVICE_NAME" \
        --since "24 hours ago" \
        --grep "Started\|Restarted" \
        --no-pager 2>/dev/null | wc -l)

    if [ "$restart_count" -gt 2 ]; then
        print_error "Service restarted $restart_count times in last 24h (might indicate instability)"
    elif [ "$restart_count" -gt 0 ]; then
        print_warn "Service restarted $restart_count time(s) in last 24h"
    else
        print_ok "Service stable (no recent restarts)"
    fi
}

#############################################################################
# Main
#############################################################################

main() {
    local exit_code=0

    case "${1:-}" in
        --continuous)
            # Run every 5 minutes
            while true; do
                clear
                check_service_status || exit_code=1
                check_security_issues || exit_code=1
                check_tool_usage
                check_disk_space
                show_alerts

                echo ""
                echo "Next check in 5 minutes ($(date '+%H:%M:%S'))..."
                sleep 300
            done
            ;;

        --alert-email)
            # TODO: Email alerts
            echo "Email alert feature not yet implemented"
            exit 1
            ;;

        *)
            # One-time check
            check_service_status || exit_code=1
            check_security_issues || exit_code=1
            check_tool_usage
            check_disk_space
            show_alerts

            echo ""
            if [ $exit_code -eq 0 ]; then
                print_ok "All checks passed"
            else
                print_error "Some issues detected (see above)"
            fi

            return $exit_code
            ;;
    esac
}

main "$@"
