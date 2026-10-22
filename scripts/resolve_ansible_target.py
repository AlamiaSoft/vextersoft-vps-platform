#!/usr/bin/env python3
"""Resolve one explicitly selected VPS target from Ansible inventory JSON."""
from __future__ import annotations

import json
import re
import sys
from typing import Any

ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]+$")
HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
USER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class TargetError(ValueError):
    """Raised when the selected inventory target cannot be verified safely."""


def group_hosts(inventory: dict[str, Any], group_name: str, seen: set[str] | None = None) -> set[str]:
    seen = seen or set()
    if group_name in seen:
        raise TargetError("Inventory group nesting contains a cycle.")
    seen.add(group_name)
    group = inventory.get(group_name)
    if not isinstance(group, dict):
        raise TargetError("Required inventory group 'vps_servers' is missing or invalid.")
    hosts = group.get("hosts", [])
    children = group.get("children", [])
    if not isinstance(hosts, list) or not all(isinstance(host, str) for host in hosts):
        raise TargetError("Inventory host membership is ambiguous.")
    if not isinstance(children, list) or not all(isinstance(child, str) for child in children):
        raise TargetError("Inventory child-group membership is ambiguous.")
    result = set(hosts)
    for child in children:
        result.update(group_hosts(inventory, child, seen.copy()))
    return result


def resolve_target(inventory: dict[str, Any], alias: str) -> dict[str, Any]:
    if not ALIAS_RE.fullmatch(alias):
        raise TargetError("Inventory alias contains unsupported characters.")
    if alias not in group_hosts(inventory, "vps_servers"):
        raise TargetError("Selected alias is not a member of the playbook target group 'vps_servers'.")
    metadata = inventory.get("_meta", {})
    hostvars = metadata.get("hostvars", {}) if isinstance(metadata, dict) else {}
    target = hostvars.get(alias) if isinstance(hostvars, dict) else None
    if not isinstance(target, dict):
        raise TargetError("Selected alias does not resolve to exactly one inventory host.")

    host = target.get("ansible_host")
    user = target.get("ansible_user")
    port = target.get("ansible_port", 22)
    ssh_port = target.get("ssh_port", port)
    connection = target.get("ansible_connection", "ssh")
    if not isinstance(host, str) or not HOST_RE.fullmatch(host):
        raise TargetError("Selected host must have a literal, unambiguous ansible_host value.")
    if not isinstance(user, str) or not USER_RE.fullmatch(user):
        raise TargetError("Selected host must have a literal, unambiguous ansible_user value.")
    if connection != "ssh":
        raise TargetError("Only SSH targets are supported by this VPS operator workflow.")
    if isinstance(port, bool) or not str(port).isdigit() or not 1 <= int(port) <= 65535:
        raise TargetError("Selected host has an invalid SSH port.")
    if isinstance(ssh_port, bool) or not str(ssh_port).isdigit() or not 1 <= int(ssh_port) <= 65535:
        raise TargetError("Selected host has an invalid baseline SSH port.")
    return {"alias": alias, "host": host, "user": user, "port": int(port), "ssh_port": int(ssh_port)}


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: resolve_ansible_target.py INVENTORY_ALIAS", file=sys.stderr)
        return 2
    try:
        inventory = json.load(sys.stdin)
        if not isinstance(inventory, dict):
            raise TargetError("Ansible inventory output is invalid.")
        result = resolve_target(inventory, sys.argv[1])
    except (json.JSONDecodeError, TargetError) as exc:
        print(f"Target validation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())