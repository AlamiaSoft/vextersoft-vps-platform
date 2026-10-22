# VexterSoft VPS — Post-Deployment Audit, Documentation & DevOps Handover

## Executive Overview & Deployment Status

- **Status:** **OPERATIONAL & VERIFIED**  
- **Audit Date:** 2026-10-22  
- **Target Host:** Contabo Ubuntu 24.04.5 LTS VPS (`vmi3682629` / `5.189.128.157`)  
- **Contracted Hardware Profile:** 6 vCPU / 12 GB RAM / 200 GB SSD (Verified via `/proc/meminfo` and `df -h`)  
- **Management Ingress:** `https://devops.vextersoft.com/` (Portainer CE 2.45.1-alpine)  
- **Security Posture:** Zero public management exposure; outbound Cloudflare Argo Tunnel connector; UFW default deny incoming.

---

## 1. Post-Deployment Audit Summary

### 1.1 Host Security & Access Posture
- **Operating System:** Ubuntu 24.04.5 LTS (`noble`), Kernel `6.8.0-139-generic x86_64`.
- **Hardware Resources (Direct Raw Query):**
  - **vCPU:** 6 vCPUs (AMD EPYC, `nproc = 6`).
  - **Memory:** `12,541,493,248 bytes` total (~12.54 GB decimal / 11.68 GiB binary, `MemTotal: 12247552 kB`). Exactly matches the contracted Contabo 12 GB plan.
  - **Storage:** `/dev/sda1` (ext4) 193 GiB total, 7.3 GiB used (4%), 186 GiB available mounted at `/`. Matches contracted 200 GB SSD.
  - **Swap:** 4.0 GiB file-backed swap (`/swapfile`) active.
- **Administrative User (`vexteradmin`):** Configured with passwordless sudo (`/etc/sudoers.d/90-vexteradmin`), member of `sudo` and `docker` groups.
- **SSH Hardening (`sudo sshd -T`):**
  - Port: `22`
  - Public Key Authentication: `yes`
  - Password Authentication: `no`
  - Keyboard-Interactive Authentication: `no`
  - Permit Root Login: `without-password` (prohibit-password)
  - X11 Forwarding: `no`
- **Firewall & Intrusion Prevention:**
  - **UFW:** Active with restrictive baseline defaults:
    - Default incoming: `deny`
    - Default outgoing: `allow`
    - Default routed: `deny`
    - Rules: Port 22/tcp ALLOW IN (IPv4 and IPv6) only.
  - **Fail2ban:** Active with `sshd` jail actively protecting port 22.
  - **Host Listening Sockets (`ss -tulpn`):** Only `0.0.0.0:22`, `[::]:22` (sshd) and `127.0.0.53/54:53` (local DNS resolver) are listening. Zero database or management ports are bound to host interfaces.

### 1.2 Docker & Management Containers
- **Engine Version:** Docker Engine `29.9.2` (API `1.56`) with Docker Compose v2 plugin.
- **Management Project Location:** `/opt/vextersoft/management` (mode `0750`).
- **Secrets Storage:** Root-managed file `/opt/vextersoft/management/secrets/tunnel-token` (mode `0440`, owned by `root:65532`).
- **Containers Status (`docker ps`):**
  - `vextersoft-management-portainer-1`: `Up (healthy)`, Image `portainer/portainer-ce:2.45.1-alpine`. Ports `8000, 9000, 9443` bound strictly to private Docker network `vextersoft-management`.
  - `vextersoft-management-cloudflared-1`: `Up (healthy)`, Image `cloudflare/cloudflared:2026.10.2`. Non-root user `65532:65532`.
- **Persistent Volume:** `vextersoft_portainer_data` mounted at `/data` inside Portainer. Initial admin credentials and environment configurations safely persisted.
- **Networks:** `vextersoft-management` (bridges cloudflared & portainer) and `vextersoft-tunnel-egress` (egress only).

### 1.3 External Verification: Direct Origin Inaccessibility
Independent external TCP probes were executed against the public origin IP (`5.189.128.157`) from an external network:
- **Port 22 (SSH):** Accessible (`TcpTestSucceeded: True`)
- **Port 9000 (Portainer HTTP):** Unreachable / Filtered (`TcpTestSucceeded: False`)
- **Port 9443 (Portainer HTTPS):** Unreachable / Filtered (`TcpTestSucceeded: False`)
- **Port 8000 (Portainer Edge):** Unreachable / Filtered (`TcpTestSucceeded: False`)
- **Port 2375 / 2376 (Docker API):** Unreachable / Filtered (`TcpTestSucceeded: False`)

**Conclusion:** Direct external access to management and Docker services is completely blocked. Docker container networking does not expose ports to the public internet because no host port mappings (`-p`) are used.

### 1.4 Public Ingress & Cloudflare Routing
- **DNS Resolution:** `devops.vextersoft.com` CNAME points to `8c9411a4-1ace-42df-aa2f-39df6cbc4d57.cfargotunnel.com` and resolves to Cloudflare Anycast edge addresses.
- **HTTPS Termination:** Terminated at Cloudflare Edge; proxies over outbound encrypted Argo Tunnel directly to `http://portainer:9000` on the private `vextersoft-management` Docker network.
- **HTTP Response:** Returns `HTTP/1.1 200 OK` from Cloudflare Edge.
- **Portainer Setup:** Admin credentials initialized by repository owner, and environment successfully connected to local Docker socket (`vextersoft-vps`).

---

## 2. RAM Specification Reconciliation (Task B Findings)

- **Owner Query:** Discrepancy observed between documented Contabo specification (12 GB RAM) and earlier mention of 15 GiB RAM.
- **Measured Reality on Live VPS:**
  - `free -b`: `12,541,493,248 bytes` total (~12.54 GB decimal)
  - `/proc/meminfo`: `MemTotal: 12247552 kB` (~11.68 GiB binary)
  - `systemd-detect-virt`: `kvm`
  - `hostnamectl`: `Static hostname: vmi3682629`
  - `nproc`: `6`
- **Root Cause of Discrepancy:**
  An earlier diagnostic step executed an interactive command line in PowerShell where inner quotes were stripped, causing SSH to disconnect and the subsequent `free -h` command to execute locally in the operator's WSL instance (which has 16 GB RAM assigned) rather than on the remote VPS. Direct raw queries via `/proc/meminfo` and the newly created `scripts/diagnostics/audit_vps_live.py` confirm exactly **12,247,552 kB (12 GB)**, resolving the discrepancy with 100% confidence.

---

## 3. Operational Vault Lifecycle & Recovery (Task A Findings)

- **Post-Deployment Vault State:** The owner deleted `ansible/vault/vextersoft_vps.vault.yml` after the one-time deployment to avoid retaining a forgotten Vault password.
- **Git History Verification:** `git log --all --full-history -- ansible/vault/vextersoft_vps.vault.yml` confirms that the file was **never committed to Git history**.
- **Server-Side Token Status:** The running `cloudflared` container reads its token directly from the persistent secret file `/opt/vextersoft/management/secrets/tunnel-token` (`mode 0440`, owned by `root:65532`). Deleting the local Vault file does not impact the live tunnel, container health, or reboot survival.
- **Future Deployment Recovery Procedure:** Documented in [docs/devops-handover-runbook.md](file:///e:/Alamia/vextersoft-vps-platform/docs/devops-handover-runbook.md#5-local-vault-handling-vs-running-system-credentials): obtain a fresh token from Cloudflare, run `ansible-vault create`, choose a fresh password, and deploy with `--ask-vault-pass`.

---

## 4. Persistent Operational Tooling

Per the persistent operational tooling standard, a reusable, non-destructive audit utility has been added to the repository:

**[scripts/diagnostics/audit_vps_live.py](file:///e:/Alamia/vextersoft-vps-platform/scripts/diagnostics/audit_vps_live.py)**
- Tests external TCP reachability for ports 22, 9000, 9443, 8000, 2375, and 2376.
- Safely queries live host resources, CPU, memory, storage, UFW rules, and active listeners over SSH without shell-quoting ambiguity.
- Gathers Docker daemon version, container health status, networks, volumes, and recent container logs.
- Performs zero mutations on the live host.

---

## 5. Updated Repository Documentation

The following canonical documentation files have been created or refreshed to reflect the verified post-deployment state:

1. **[docs/infrastructure-inventory.md](file:///e:/Alamia/vextersoft-vps-platform/docs/infrastructure-inventory.md)**: Updated with the live system specifications (12 GB RAM, 200 GB SSD, 6 vCPU), kernel version, UFW configuration, Docker engine details, and container inventories.
2. **[.ai/transient/sprint/00-current-state.md](file:///e:/Alamia/vextersoft-vps-platform/.ai/transient/sprint/00-current-state.md)**: Updated to mark Phase D as complete, operational, and verified.
3. **[docs/reports/vps-post-deployment-security-audit-2026-10-22.md](file:///e:/Alamia/vextersoft-vps-platform/docs/reports/vps-post-deployment-security-audit-2026-10-22.md)**: Comprehensive, dated security audit report providing full command-level evidence across all test vantage points.
4. **[docs/devops-handover-runbook.md](file:///e:/Alamia/vextersoft-vps-platform/docs/devops-handover-runbook.md)**: Practical operational runbook for DevOps engineers covering routine diagnostics, logging, restarts, Portainer volume backups/restores, upgrades, and how to safely onboard future application routes.
