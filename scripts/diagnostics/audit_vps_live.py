#!/usr/bin/env python3
"""
VexterSoft VPS Platform — Live System & Security Diagnostic Audit Tool

Purpose:
    Executes non-destructive, read-only diagnostic audits against the live
    VexterSoft VPS via SSH/WSL and external network socket checks.

Target Resolution:
    Resolves the target host deterministically from `ansible/inventory/hosts.yml`
    (via `scripts/resolve_ansible_target.py` rules) or explicit validated CLI
    arguments (`--target-ip`). Fails closed on missing, placeholder (`<...>`),
    documentation-range (`192.0.2.1`, `2001:db8::/32`), or ambiguous targets.

Usage:
    python scripts/diagnostics/audit_vps_live.py [--inventory ansible/inventory/hosts.yml] [--alias vextersoft_vps]
    python scripts/diagnostics/audit_vps_live.py --target-ip <VALID_PUBLIC_IP> [--user vexteradmin]
"""
from __future__ import annotations

import argparse
import base64
import errno
import ipaddress
import json
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.resolve_ansible_target import (  # noqa: E402
    HOST_RE,
    USER_RE,
    TargetError,
    resolve_target,
)

DEFAULT_TARGET_USER = "vexteradmin"
DEFAULT_TARGET_ALIAS = "vextersoft_vps"
DEFAULT_INVENTORY_PATH = REPO_ROOT / "ansible" / "inventory" / "hosts.yml"

PLACEHOLDER_RE = re.compile(r"<[^>]*>|TODO|CHANGEME|EXAMPLE", re.IGNORECASE)
DOCUMENTATION_NETWORKS = (
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("2001:db8::/32"),
)

# Errno / WinError codes indicating local client lacks IPv6 routing (not a remote port closure)
LOCAL_UNROUTABLE_ERRNOS = frozenset({
    errno.ENETUNREACH,
    errno.EHOSTUNREACH,
    errno.EADDRNOTAVAIL,
    10049,  # WSAEADDRNOTAVAIL
    10051,  # WSAENETUNREACH
    10065,  # WSAEHOSTUNREACH
})


class AuditTargetError(ValueError):
    """Raised when the audit target is missing, placeholder, test-range, or ambiguous."""


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

echo "=== SECTION: NETWORK & IPV6 ==="
ip -br addr || true

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


def validate_live_target_host(host: str) -> str:
    """
    Validate a target IP or hostname for live auditing, failing closed on empty,
    placeholder, documentation/test-net (`192.0.2.1`, `2001:db8::`), loopback,
    or malformed values.
    """
    if not isinstance(host, str) or not host.strip():
        raise AuditTargetError("Target host/IP is missing or empty.")
    cleaned = host.strip()
    if PLACEHOLDER_RE.search(cleaned):
        raise AuditTargetError(f"Target host contains an unresolved placeholder or example token: {cleaned!r}")
    if not HOST_RE.fullmatch(cleaned):
        raise AuditTargetError(f"Target host contains invalid characters: {cleaned!r}")

    lower = cleaned.lower()
    if lower in {"localhost", "example.com", "example.org", "example.net"} or lower.endswith(".example"):
        raise AuditTargetError(f"Target host uses a reserved/documentation hostname: {cleaned!r}")

    try:
        addr = ipaddress.ip_address(cleaned)
    except ValueError:
        # Hostname format rather than IP literal: require at least one dot and valid labels
        if ":" in cleaned or "." not in cleaned:
            raise AuditTargetError(f"Target host is neither a valid IP literal nor a qualified hostname: {cleaned!r}")
        return cleaned

    for net in DOCUMENTATION_NETWORKS:
        if addr in net:
            raise AuditTargetError(
                f"Target IP {cleaned!r} is in RFC documentation/test range ({net}); "
                "configure the real VPS address in ansible/inventory/hosts.yml."
            )
    if (
        addr.is_loopback
        or addr.is_unspecified
        or addr.is_multicast
        or addr.is_link_local
        or addr.is_private
        or addr.is_reserved
    ):
        raise AuditTargetError(
            f"Target IP {cleaned!r} is non-routable/private/reserved and cannot be used as a live VPS target."
        )
    return cleaned


def _yaml_inventory_to_ansible_json(raw_inventory: dict[str, Any]) -> dict[str, Any]:
    """
    Convert a standard YAML Ansible inventory tree (`all.hosts`, `all.children`)
    into the JSON structure expected by `scripts/resolve_ansible_target.py`.
    """
    if not isinstance(raw_inventory, dict):
        raise AuditTargetError("Inventory YAML root must be a mapping.")
    if "_meta" in raw_inventory and "vps_servers" in raw_inventory:
        return raw_inventory

    all_block = raw_inventory.get("all")
    if not isinstance(all_block, dict):
        raise AuditTargetError("Inventory YAML is missing top-level 'all' mapping.")

    hostvars: dict[str, dict[str, Any]] = {}
    top_hosts = all_block.get("hosts") or {}
    if not isinstance(top_hosts, dict):
        raise AuditTargetError("Inventory 'all.hosts' must be a mapping.")
    for alias, vars_map in top_hosts.items():
        if isinstance(vars_map, dict):
            hostvars[alias] = dict(vars_map)
        elif vars_map is None:
            hostvars[alias] = {}
        else:
            raise AuditTargetError(f"Host variables for {alias!r} must be a mapping.")

    out: dict[str, Any] = {"_meta": {"hostvars": hostvars}}
    children = all_block.get("children") or {}
    if not isinstance(children, dict):
        raise AuditTargetError("Inventory 'all.children' must be a mapping.")

    for group_name, group_data in children.items():
        if not isinstance(group_data, dict):
            raise AuditTargetError(f"Group {group_name!r} definition must be a mapping.")
        g_hosts_raw = group_data.get("hosts") or {}
        if isinstance(g_hosts_raw, dict):
            g_hosts = list(g_hosts_raw.keys())
            for alias, vars_map in g_hosts_raw.items():
                merged = dict(hostvars.get(alias, {}))
                if isinstance(vars_map, dict):
                    merged.update(vars_map)
                hostvars[alias] = merged
        elif isinstance(g_hosts_raw, list):
            g_hosts = list(g_hosts_raw)
        else:
            raise AuditTargetError(f"Group {group_name!r} hosts must be a mapping or list.")

        g_children_raw = group_data.get("children") or {}
        if isinstance(g_children_raw, dict):
            g_children = list(g_children_raw.keys())
        elif isinstance(g_children_raw, list):
            g_children = list(g_children_raw)
        else:
            raise AuditTargetError(f"Group {group_name!r} children must be a mapping or list.")

        out[group_name] = {"hosts": g_hosts, "children": g_children}

    return out


def resolve_audit_target(
    *,
    target_ip: str | None = None,
    user: str | None = None,
    port: int = 22,
    inventory_path: Path | None = None,
    alias: str = DEFAULT_TARGET_ALIAS,
) -> dict[str, Any]:
    """
    Resolve and validate the VPS target for live diagnostics.
    Uses explicit CLI `--target-ip` when provided, or resolves `alias` from
    `ansible/inventory/hosts.yml` via `scripts/resolve_ansible_target.py`.
    Fails closed on any missing, placeholder, test-range, or ambiguous target.
    """
    if target_ip is not None and target_ip.strip():
        validated_host = validate_live_target_host(target_ip)
        effective_user = (user or DEFAULT_TARGET_USER).strip()
        if PLACEHOLDER_RE.search(effective_user) or not USER_RE.fullmatch(effective_user):
            raise AuditTargetError(f"SSH user is invalid or contains a placeholder: {effective_user!r}")
        if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
            raise AuditTargetError(f"SSH port is invalid: {port!r}")
        return {
            "alias": alias,
            "host": validated_host,
            "user": effective_user,
            "port": port,
            "source": "cli",
        }

    inv_file = inventory_path if inventory_path is not None else DEFAULT_INVENTORY_PATH
    if not inv_file.is_file():
        raise AuditTargetError(
            f"Canonical inventory file not found at {inv_file}. "
            "Create ansible/inventory/hosts.yml or pass an explicit validated --target-ip."
        )
    if yaml is None:
        raise AuditTargetError("PyYAML is required to parse Ansible inventory files.")

    try:
        raw_data = yaml.safe_load(inv_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AuditTargetError(f"Failed to parse inventory YAML {inv_file}: {exc}") from exc

    if not isinstance(raw_data, dict):
        raise AuditTargetError(f"Inventory file {inv_file} does not contain a valid YAML mapping.")

    try:
        normalized_inv = _yaml_inventory_to_ansible_json(raw_data)
        resolved = resolve_target(normalized_inv, alias)
    except TargetError as exc:
        raise AuditTargetError(f"Inventory target validation failed: {exc}") from exc

    validated_host = validate_live_target_host(resolved["host"])
    effective_user = user.strip() if (user and user.strip()) else resolved["user"]
    if PLACEHOLDER_RE.search(effective_user) or not USER_RE.fullmatch(effective_user):
        raise AuditTargetError(f"SSH user is invalid or contains a placeholder: {effective_user!r}")

    return {
        "alias": resolved["alias"],
        "host": validated_host,
        "user": effective_user,
        "port": int(resolved["port"]),
        "source": str(inv_file),
    }


def run_remote_diagnostics(target_ip: str, user: str, port: int = 22) -> str:
    """Executes the diagnostic script over SSH via the WSL environment with active SSH agent."""
    encoded_script = base64.b64encode(REMOTE_AUDIT_SCRIPT.encode("utf-8")).decode("ascii")

    wsl_command = (
        f'echo "{encoded_script}" | base64 -d | '
        f'SSH_AUTH_SOCK=$(ls /tmp/vextersoft-ssh/agent.sock /tmp/ssh-*/agent.* 2>/dev/null | head -n 1) '
        f'ssh -p {int(port)} -o StrictHostKeyChecking=yes -o ConnectTimeout=10 {user}@{target_ip} bash'
    )

    cmd = ["wsl", "bash", "-c", wsl_command]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 and not res.stdout:
        print(f"Error connecting to VPS: {res.stderr}", file=sys.stderr)
        sys.exit(res.returncode)
    return res.stdout


def probe_external_port(host: str, port: int, is_ipv6: bool = False, timeout: float = 2.5) -> str:
    """
    Check if a TCP port is reachable from this external vantage point.

    Returns:
      - `"OPEN"`: TCP handshake succeeded.
      - `"CLOSED"`: Connection refused or timed out over a routable path.
      - `"INCONCLUSIVE"`: Local client lacks routing for the address family (e.g. IPv6 unavailable).
    """
    family = socket.AF_INET6 if is_ipv6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.shutdown(socket.SHUT_RDWR)
        return "OPEN"
    except (socket.timeout, ConnectionRefusedError):
        return "CLOSED"
    except OSError as exc:
        err_code = getattr(exc, "errno", None) or getattr(exc, "winerror", None)
        if is_ipv6 and err_code in LOCAL_UNROUTABLE_ERRNOS:
            return "INCONCLUSIVE"
        return "CLOSED"
    finally:
        sock.close()


def audit_external_network(target_ip: str) -> dict[int, dict[str, Any]]:
    """Performs external TCP probing on standard management and daemon ports."""
    ports_to_check = {
        22: "SSH Administrative Port",
        80: "HTTP Web Standard",
        443: "HTTPS Web Standard",
        9000: "Portainer Internal HTTP",
        9443: "Portainer Internal HTTPS",
        8000: "Portainer Edge Tunnel",
        2375: "Docker Daemon Insecure API",
        2376: "Docker Daemon TLS API",
    }
    results: dict[int, dict[str, Any]] = {}
    is_ipv6 = ":" in target_ip
    for port, label in ports_to_check.items():
        probe_state = probe_external_port(target_ip, port, is_ipv6=is_ipv6)
        if probe_state == "INCONCLUSIVE":
            status = "INCONCLUSIVE"
        elif (port == 22 and probe_state == "OPEN") or (port != 22 and probe_state == "CLOSED"):
            status = "PASS"
        else:
            status = "FAIL"
        results[port] = {
            "label": label,
            "open": probe_state == "OPEN",
            "probe_state": probe_state,
            "status": status,
        }
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live VPS Diagnostic Audit Tool")
    parser.add_argument(
        "--target-ip",
        default=None,
        help="Explicit target VPS IP address (if omitted, resolves from --inventory and --alias)",
    )
    parser.add_argument(
        "--inventory",
        default=str(DEFAULT_INVENTORY_PATH),
        help="Path to Ansible inventory file (default: ansible/inventory/hosts.yml)",
    )
    parser.add_argument(
        "--alias",
        default=DEFAULT_TARGET_ALIAS,
        help=f"Inventory host alias in vps_servers (default: {DEFAULT_TARGET_ALIAS})",
    )
    parser.add_argument(
        "--user",
        default=None,
        help="SSH user override (default: from inventory or vexteradmin)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=22,
        help="SSH port when using --target-ip (default: 22)",
    )
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        target = resolve_audit_target(
            target_ip=args.target_ip,
            user=args.user,
            port=args.port,
            inventory_path=Path(args.inventory),
            alias=args.alias,
        )
    except AuditTargetError as exc:
        print(f"Error: Target resolution failed closed: {exc}", file=sys.stderr)
        return 2

    print(
        f"[*] Starting non-destructive live audit against alias={target['alias']} "
        f"({target['user']}@{target['host']}:{target['port']})...\n"
    )

    # 1. External Network Probe
    print("--- 1. External Network Exposure Audit ---")
    external_results = audit_external_network(target["host"])
    for port, info in external_results.items():
        if info["probe_state"] == "OPEN":
            state = "OPEN"
        elif info["probe_state"] == "INCONCLUSIVE":
            state = "INCONCLUSIVE (NO ROUTE)"
        else:
            state = "CLOSED / UNREACHABLE"
        print(f"  [Port {port:4d}] {info['label']:30s} -> {state:24s} [{info['status']}]")
    print()

    # 2. Remote Host Diagnostics
    print("--- 2. Live VPS Diagnostics via Strict SSH ---")
    remote_output = run_remote_diagnostics(target["host"], target["user"], target["port"])
    print(remote_output)

    print("[*] Audit complete. Zero host mutations performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
