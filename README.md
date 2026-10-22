# VexterSoft VPS Platform

> **Automated, hardened, and isolated multi-tenant application hosting infrastructure for VexterSoft on Contabo Cloud VPS.**

---

## 1. Architecture Overview & Deployment State

The VexterSoft platform provides containerized application hosting with zero public exposure of internal management ports or databases.

```
[ Internet Traffic ]
        │
        ├──> [ Cloudflare Edge: devops.vextersoft.com ] ── (Zero Trust Access) ──┐
        │                                                                        │
        └──> [ Cloudflare Edge: future app routes ] ────── (Public TLS, Planned) ┤
                                                                                 │
┌────────────────────────────────────────────────────────────────────────────────▼─────────┐
│ Contabo Cloud VPS 6 (Ubuntu 24.04.5 LTS / 6 vCPU / 12 GB RAM (~11.68 GiB) / 200 GB SSD)  │
│                                                                                          │
│  CURRENTLY DEPLOYED SERVICES (Phase D Operational):                                      │
│  [ cloudflared daemon ] (Outbound encrypted tunnel — zero inbound web ports required)    │
│          │                                                                               │
│          └──> [ vextersoft-management ] ── Portainer CE 2.45.1-alpine (Internal :9000)   │
│                                                                                          │
│  PLANNED / FUTURE APPLICATION WORKLOADS (Not Yet Deployed):                              │
│          ├──> [ net-odoo ] ────────── VexterSoft Odoo 20 + PostgreSQL 16 (Planned)       │
│          ├──> [ net-zelixvet-prod ] ── ZelixVet Prod + Isolated Database (Planned)       │
│          ├──> [ net-zelixvet-stg ] ─── ZelixVet Staging + Isolated Database (Planned)    │
│          └──> [ net-demo ] ────────── Marketing Demonstration (Planned)                  │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

### Deployed vs. Planned Workloads
- **Currently Deployed on VPS (`vmi3682629`):**
  - **Host Baseline & Runtime:** Ubuntu 24.04.5 LTS, UFW restrictive firewall (port 22/tcp allow only), Fail2ban `sshd` jail, 4.0 GiB swap, Docker Engine `29.9.2` + Compose v2.
  - **Management & Ingress Plane (`/opt/vextersoft/management`):** `cloudflare/cloudflared:2026.10.2` and `portainer/portainer-ce:2.45.1-alpine` isolated on internal network `vextersoft-management` and outbound bridge `vextersoft-tunnel-egress`, gated at `https://devops.vextersoft.com` by Cloudflare Access.
- **Planned Future Workloads (Target Architecture Only):**
  - Application stacks (Odoo 20, ZelixVet Production/Staging, Marketing Demo) are **not yet deployed** on the VPS. When onboarded, each public frontend will attach to its own dedicated Docker network via `cloudflare_public_routes` while keeping databases on private internal networks.

---

## 2. Security & Operational Invariants

1. **Zero Public Management Ports:** Portainer, Docker APIs, PostgreSQL clusters, and internal networks never bind to `0.0.0.0`, `[::]`, or `127.0.0.1` on the host. Ingress is mediated exclusively through outbound Cloudflare Tunnels.
2. **Access Tier Separation:**
   - Management (`devops.vextersoft.com`): Gated behind Cloudflare Zero Trust Access + Portainer authentication.
   - Client Applications (Planned): Accessible through explicit per-app Cloudflare edge hostnames with standard TLS, without attaching management or database networks.
3. **Multi-Environment Isolation:** Staging, Production, and Demonstration environments use strictly separated container networks, volume directories, and database credentials.
4. **Governed Agent Lifecycle:** All changes follow [AGENT_PROTOCOL.md](AGENT_PROTOCOL.md) with risk categorization and mandatory approval gates before any host mutation.

---

## 3. Directory Layout

- **`.agents/`**: AI agent workspace guidelines and lifecycle definitions.
- **`.ai/`**: Canonical AI architecture knowledge base and current state tracker.
- **`Alamia-Skills-System/`**: Portable lifecycle and atomic development skills suite.
- **`docs/`**: Platform documentation, audits, inventories, specifications, and recovery runbooks:
  - [`docs/infrastructure-inventory.md`](docs/infrastructure-inventory.md): Reconciled hardware (`6 vCPU / 12 GB contracted RAM (~11.68 GiB OS-usable) / 200 GB SSD (~193 GiB ext4)`), OS, disk, and network baseline.
  - [`docs/devops-handover-runbook.md`](docs/devops-handover-runbook.md): Operator & trainee runbook for diagnostics, `scripts/portainer_backup.py` backup/sandbox-restore workflows, and route onboarding.
  - [`docs/cloudflare-portainer-runbook.md`](docs/cloudflare-portainer-runbook.md): Cloudflare Tunnel + Portainer provisioning, Vault setup, and rollback guide.
  - [`docs/reports/vps-post-deployment-security-audit-2026-10-22.md`](docs/reports/vps-post-deployment-security-audit-2026-10-22.md): Post-deployment security audit report (`PARTIALLY VERIFIED` — pending external IPv6 probe and live off-host backup proof).
- **`ansible/`**: Idempotent configuration management playbooks, templates, and inventory examples.
- **`scripts/`**: Operational diagnostic, backup/restore, bootstrap, and repository safety tooling:
  - [`scripts/portainer_backup.py`](scripts/portainer_backup.py): Reusable Portainer volume backup, archive integrity verifier, and sandbox-restore helper.
  - [`scripts/diagnostics/audit_vps_live.py`](scripts/diagnostics/audit_vps_live.py): Non-destructive read-only live audit script with fail-closed inventory target resolution.
  - [`scripts/resolve_ansible_target.py`](scripts/resolve_ansible_target.py): Canonical Ansible inventory target resolver.
  - [`scripts/ci_validate.py`](scripts/ci_validate.py): Local and CI syntax and repository safety validator.
- **`tests/`**: Automated unit and regression test suite (`python -m unittest discover -s tests -v`).

---

## 4. Bootstrap Roadmap & Execution DAG

The infrastructure setup and hardening roadmap tracks across these governed issues:

1. **[Issue #1](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/1):** Establish Antigravity ↔ GitHub Protocol (`AGENT_PROTOCOL.md`). *(Complete)*
2. **[Issue #2](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/2):** Review Bootstrap Plan & Prepare Execution DAG. *(Complete)*
3. **[Issue #4](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/4):** `[HOST-CHANGE]` Baseline Host Hardening (User, SSH Key, Swap, UFW, fail2ban). *(Deployed & Verified)*
4. **[Issue #5](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/5):** `[HOST-CHANGE]` Container Runtime Setup (Docker CE, Compose, Log Safeguards). *(Deployed & Verified)*
5. **[Issue #6](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/6):** `[HOST-CHANGE]` Edge Ingress & Management (Cloudflare Tunnel, Portainer CE). *(Deployed & Verified)*
6. **[Issue #7](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/7):** `[READ-ONLY]` Platform Verification & Recovery Runbook. *(Partially Verified — External IPv6 & Live Off-Host Backup Proof Pending)*
7. **[Epic #27](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/27):** Make VPS Backup/Restore Workflow Safe, Tested, and Trainee-Ready (`#28`–`#32`).
