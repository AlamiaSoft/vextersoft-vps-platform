# VexterSoft VPS Platform

> **Automated, hardened, and isolated multi-tenant application hosting infrastructure for VexterSoft on Contabo Cloud VPS.**

---

## 1. Architecture Overview

The VexterSoft platform provides containerized application hosting with zero public exposure of internal management ports or databases.

```
[ Internet Traffic ]
        │
        ├──> [ Cloudflare Edge: devops.vextersoft.com ] ── (Zero Trust Access) ──┐
        │                                                                        │
        └──> [ Cloudflare Edge: client apps (*.vextersoft.com) ] ── (Public TLS) ──┤
                                                                                 │
┌────────────────────────────────────────────────────────────────────────────────▼─────────┐
│ Contabo Cloud VPS 6 (Ubuntu 24.04 LTS / 6 vCPU / 11 GB RAM / 193 GB SSD)                  │
│                                                                                          │
│  [ cloudflared daemon ] (Outbound encrypted tunnel — zero inbound ports required)        │
│          │                                                                               │
│          ├──> [ net-mgmt ] ────────── Portainer CE (Internal :9000)                      │
│          ├──> [ net-odoo ] ────────── VexterSoft Odoo 20 + PostgreSQL 16 (Isolated)      │
│          ├──> [ net-zelixvet-prod ] ── ZelixVet Prod + Isolated Database                 │
│          ├──> [ net-zelixvet-stg ] ─── ZelixVet Staging + Isolated Database             │
│          └──> [ net-demo ] ────────── Marketing Demonstration (Synthetic Data)           │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Security & Operational Invariants

1. **Zero Public Management Ports:** Portainer, Docker APIs, PostgreSQL clusters, and internal networks never bind to `0.0.0.0` or `[::]`. Ingress is mediated exclusively through outbound Cloudflare Tunnels.
2. **Access Tier Separation:**
   - Management (`devops.vextersoft.com`): Gated behind Cloudflare Zero Trust Access + Portainer authentication.
   - Client Applications: Directly accessible through Cloudflare edge hostnames with standard TLS, without forcing clients through Cloudflare Access.
3. **Multi-Environment Isolation:** Staging, Production, and Demonstration environments use strictly separated container networks, volume directories, and database credentials.
4. **Governed Agent Lifecycle:** All changes follow [AGENT_PROTOCOL.md](AGENT_PROTOCOL.md) with risk categorization and mandatory approval gates before any host mutation.

---

## 3. Directory Layout

- **`.agents/`**: AI agent workspace guidelines and lifecycle definitions.
- **`.ai/`**: Canonical AI architecture knowledge base and current state tracker.
- **`Alamia-Skills-System/`**: Portable lifecycle and atomic development skills suite.
- **`docs/`**: Platform documentation, audits, inventories, specifications, and recovery runbooks:
  - `docs/infrastructure-inventory.md`: Discovered hardware, OS, disk, and network specs.
  - `docs/security-audit-and-hardening-plan.md`: Security analysis and remediation rules.
  - `docs/bootstrap-review-and-dag.md`: Phase-by-phase execution DAG and review findings.
- **`ansible/`**: Idempotent configuration management playbooks, roles, and inventories.
- **`scripts/`**: Operational diagnostic, bootstrap, and repository safety tooling:
  - `scripts/inspect_vps.py`: Non-destructive read-only SSH audit script.
  - `scripts/ci_validate.py`: Local and CI syntax and repository safety validator.
- **`tests/`**: Automated test suite for bootstrap, security, and compose verification.

---

## 4. Bootstrap Roadmap & Execution DAG

The infrastructure setup is divided into atomic, dependency-linked tasks:

1. **[Issue #1](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/1):** Establish Antigravity ↔ GitHub Protocol (`AGENT_PROTOCOL.md`). *(Complete / PR #3 merged)*
2. **[Issue #2](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/2):** Review Bootstrap Plan & Prepare Execution DAG. *(Complete / PR #8 ready for review)*
3. **[Issue #4](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/4):** `[HOST-CHANGE]` Baseline Host Hardening (User, SSH Key, Swap, UFW, fail2ban).
4. **[Issue #5](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/5):** `[HOST-CHANGE]` Container Runtime Setup (Docker CE, Compose, Log Safeguards).
5. **[Issue #6](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/6):** `[HOST-CHANGE]` Edge Ingress & Management (Cloudflare Tunnel, Portainer CE).
6. **[Issue #7](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/7):** `[READ-ONLY]` Platform Verification & Recovery Runbook.
