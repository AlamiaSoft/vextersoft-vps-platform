#!/usr/bin/env python3
"""
VexterSoft VPS Platform — Live System & Security Diagnostic Audit Tool

Purpose:
    Executes non-destructive, read-only diagnostic audits against the live
    VexterSoft VPS via SSH/WSL and external network socket checks.

Usage:
    python scripts/diagnostics/audit_vps_live.py [--target-ip <IP>] [--user <USER>]
"""

import argparse
import base64
import json
import socket
import subprocess
import sys
from pathlib import Path


DEFAULT_TARGET_IP = "5.189.128.157"
DEFAULT_TARGET_USER = "vexteradmin"

REMOTE_AUDIT_SCRIPT = """#!/bin/bash
set -euo pipefail

echo "=== SECTION: HOST IDENTITY & VIRTUALIZATION ==="
hostname
hostnamectl
systemd-detect-virt || true
echo "CPU Cores: $(nproc)"

echo "=== SECTION: MEMORY RAW & HUMAN ==="
free -b
grep -E 'MemTotal|MemAvailable' /proc/meminfo
free -h

echo "=== SECTION: STORAGE & SWAP ==="
df -h /
swapon --show || true

echo "=== SECTION: FIREWALL & LISTENING PORTS ==="
sudo ufw status verbose || true
sudo ss -tulpn || true

echo "=== SECTION: FAIL2BAN STATUS ==="
sudo fail2ban-client status sshd || true

echo "=== SECTION: DOCKER DAEMON & CONTAINERS ==="
sudo docker version --format 'Engine: {{.Server.Version}} (API: {{.Server.APIVersion}})' || true
sudo docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' || true
sudo docker network ls || true
sudo docker volume ls || true

echo "=== SECTION: CLOUDFLARE TUNNEL & PORTAINER LOGS (TAIL) ==="
echo "--- cloudflared ---"
sudo docker logs --tail 10 vextersoft-management-cloudflared-1 2>&1 || true
echo "--- portainer ---"
sudo docker logs --tail 10 vextersoft-management-portainer-1 2>&1 || true
"""


def run_remote_diagnostics(target_ip: str, user: str) -> str:
    """Executes the diagnostic script over SSH via the WSL environment with active SSH agent."""
    encoded_script = base64.b64encode(REMOTE_AUDIT_SCRIPT.encode("utf-8")).decode("ascii")

    wsl_command = (
        f'echo "{encoded_script}" | base64 -d | '
        f'SSH_AUTH_SOCK=$(ls /tmp/ssh-*/agent.* 2>/dev/null | head -n 1) '
        f'ssh -o StrictHostKeyChecking=yes -o ConnectTimeout=10 {user}@{target_ip} bash'
    )

    cmd = ["wsl", "bash", "-c", wsl_command]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 and not res.stdout:
        print(f"Error connecting to VPS: {res.stderr}", file=sys.stderr)
        sys.exit(res.returncode)
    return res.stdout


def probe_external_port(host: str, port: int, timeout: float = 3.0) -> bool:
    """Checks if a TCP port is reachable from this external vantage point."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.shutdown(socket.SHUT_RDWR)
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False
    finally:
        sock.close()


def audit_external_network(target_ip: str) -> dict:
    """Performs external TCP probing on standard management and daemon ports."""
    ports_to_check = {
        22: "SSH Administrative Port",
        9000: "Portainer Internal HTTP",
        9443: "Portainer Internal HTTPS",
        8000: "Portainer Edge Tunnel",
        2375: "Docker Daemon Insecure API",
        2376: "Docker Daemon TLS API",
    }
    results = {}
    for port, label in ports_to_check.items():
        is_open = probe_external_port(target_ip, port)
        results[port] = {
            "label": label,
            "open": is_open,
            "status": "PASS" if (port == 22 and is_open) or (port != 22 and not is_open) else "FAIL",
        }
    return results


def main():
    parser = argparse.ArgumentParser(description="Live VPS Diagnostic Audit Tool")
    parser.add_argument("--target-ip", default=DEFAULT_TARGET_IP, help="Target VPS IP address")
    parser.add_argument("--user", default=DEFAULT_TARGET_USER, help="SSH user (default: vexteradmin)")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    args = parser.parse_args()

    print(f"[*] Starting non-destructive live audit against {args.target_ip} ({args.user})...\n")

    # 1. External Network Probe
    print("--- 1. External Network Exposure Audit ---")
    external_results = audit_external_network(args.target_ip)
    for port, info in external_results.items():
        state = "OPEN" if info["open"] else "CLOSED / UNREACHABLE"
        print(f"  [Port {port:4d}] {info['label']:30s} -> {state:20s} [{info['status']}]")
    print()

    # 2. Remote Host Diagnostics
    print("--- 2. Live VPS Diagnostics via Strict SSH ---")
    remote_output = run_remote_diagnostics(args.target_ip, args.user)
    print(remote_output)

    print("[*] Audit complete. Zero host mutations performed.")


if __name__ == "__main__":
    main()
