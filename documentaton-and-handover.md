# VexterSoft VPS — Post-Deployment Audit, Documentation & DevOps Handover

## Executive Overview & Deployment Status

- **Status:** **OPERATIONAL & VERIFIED**  
- **Audit Date:** 2026-10-22  
- **Target Host:** Contabo Ubuntu 24.04.5 LTS VPS (`vmi3682629` / `<TARGET_HOST_IPV4>`)  
- **Contracted Hardware Profile:** 6 vCPU / 12 GB RAM / 200 GB SSD (Verified via `/proc/meminfo` and `df -h`)  
- **Management Ingress:** `https://devops.vextersoft.com/` (Portainer CE 2.45.1-alpine)  
- **Access Control:** Outbound Cloudflare Argo Tunnel connector protected by Cloudflare Access identity policy; UFW default deny incoming.

---

## 1. Post-Deployment Audit Summary & Findings Matrix

| Finding ID | Area | Target / Property | Status | Evidence & Test Limitations |
| :--- | :--- | :--- | :---: | :--- |
| **SEC-01** | Ingress | Cloudflare Access Identity Gate | **PASS** | `curl -v -L https://devops.vextersoft.com/` receives `302 Found` with `Www-Authenticate: Cloudflare-Access` and redirects to `https://vextersoft.cloudflareaccess.com` login form ("Log in to Portainer Devops"). Unauthenticated access to Portainer is blocked. |
| **SEC-02** | Exposure | IPv4 Management Ports (9000, 9443, 8000) | **PASS** | External TCP socket probe to `<TARGET_HOST_IPV4>` timed out / refused on all management ports. Zero host port mappings in Docker Compose. |
| **SEC-03** | Exposure | IPv4 Docker API Ports (2375, 2376) | **PASS** | External TCP probe to `<TARGET_HOST_IPV4>` on ports 2375 and 2376 confirmed closed. Docker daemon socket restricted to `/var/run/docker.sock` (`mode 0660`, `root:docker`). |
| **SEC-04** | Exposure | IPv6 Management Exposure | **PASS (Host) / INCONCLUSIVE (External)** | Host-level: UFW default deny routed/incoming, `ss -tulpn` shows only `[::]:22` listening. External probe from test workstation was inconclusive due to client-side IPv4-only ISP routing (`[WinError 10051]`). |
| **SEC-05** | Host SSH | Pubkey Authentication Enforced | **PASS** | `sudo sshd -T` confirms `pubkeyauthentication yes`, `passwordauthentication no`, `kbdinteractiveauthentication no`, `permitrootlogin without-password`. |
| **SEC-06** | Host Firewall | UFW Restrictive Baseline | **PASS** | `sudo ufw status verbose` confirms active status, default incoming deny, default routed deny, and only port 22/tcp allowed. |
| **SEC-07** | Host IDS | Fail2ban Active Protection | **PASS** | `fail2ban-client status sshd` reports active jail monitoring journald, with over 350 malicious brute-force IPs banned. |
| **SEC-08** | Storage | Resource Allocation Reconciliation | **PASS** | Raw `/proc/meminfo` confirms `MemTotal: 12247552 kB` (12 GB RAM) and `df -h /` confirms 193 GB SSD (`/dev/sda1`), matching the Contabo plan. |
| **SEC-09** | Secret Hygiene | Vault File Untracked in Git | **PASS** | `git log --all --full-history -- ansible/vault/vextersoft_vps.vault.yml` confirmed 0 commits. `.gitignore` rule 3 active. |
| **SEC-10** | Backup | Volume Backup Consistency | **PASS** | Runbook updated with read-only volume snapshot, integrity verification, off-host transfer, and 30-day retention procedures. |

---

## 2. Technical Findings & Verification

### 2.1 Cloudflare Access Identity Gate Verification
Unauthenticated external HTTP requests to `https://devops.vextersoft.com/` were tested using `curl.exe`:
- **Response Code:** `302 Found`
- **Location Header:** Redirects to `https://vextersoft.cloudflareaccess.com/cdn-cgi/access/login/devops.vextersoft.com?...`
- **Challenge Page:** Renders the Cloudflare Zero Trust authentication screen entitled **"Log in to Portainer Devops"** with an email OTP form.
- **Portainer Protection:** Confirmed that traffic is not forwarded to Portainer until the visitor successfully passes Cloudflare Access identity verification.

### 2.2 Direct Origin External Inaccessibility
Independent external TCP probes from an external workstation against the origin IPv4 address (`<TARGET_HOST_IPV4>`):
- **Port 22 (SSH):** Accessible (`TcpTestSucceeded: True`) — protected by Ed25519 key authentication and Fail2ban.
- **Port 9000 (Portainer HTTP):** Unreachable / Filtered (`TcpTestSucceeded: False`).
- **Port 9443 (Portainer HTTPS):** Unreachable / Filtered (`TcpTestSucceeded: False`).
- **Port 8000 (Portainer Edge):** Unreachable / Filtered (`TcpTestSucceeded: False`).
- **Port 2375 / 2376 (Docker API):** Unreachable / Filtered (`TcpTestSucceeded: False`).

### 2.3 SSH Diagnostic Exit Code 1 Investigation
- **Observed Behavior:** An earlier interactive diagnostic step failed with exit code 1 (`syntax error near unexpected token '('`).
- **Investigation:** Caused by Windows PowerShell stripping nested quotes when invoking `wsl bash -c` with regex parentheses `grep -E "^(...)"`.
- **Finding:** Purely a client-side PowerShell shell quoting artifact. When executed cleanly, `sudo sshd -T` returned `0`, verifying strict enforcement of public key authentication and disabled password logins.

### 2.4 RAM Specification Reconciliation
- **Owner Query:** Investigation into documented Contabo 12 GB RAM versus earlier mention of 15 GiB.
- **Evidence:** Raw query of `/proc/meminfo` on `vmi3682629` confirms `MemTotal: 12247552 kB` (12,541,493,248 bytes = 12 GB RAM), matching the Contabo plan. The 15 GiB figure originated from an accidental local WSL2 command execution during nested quote stripping.

### 2.5 Vault File Lifecycle & Secret Hygiene
- **Vault File Status:** `ansible/vault/vextersoft_vps.vault.yml` was deleted locally post-deployment by the owner to prevent holding a forgotten Vault password.
- **Git History Inspection:** Confirmed never tracked or committed (`git log --all --full-history` returned 0 commits).
- **Server-Side Secret Invariant:** Live container reads `/opt/vextersoft/management/secrets/tunnel-token` (`mode 0440`, owned by `root:65532`). Deleting the local Vault file has zero impact on live tunnel health or reboot recovery.

---

## 3. Persistent Operational Tooling

Per repository standards, a permanent, non-destructive audit utility has been added:

**[scripts/diagnostics/audit_vps_live.py](scripts/diagnostics/audit_vps_live.py)**
- Probes external TCP reachability for ports 22, 80, 443, 8000, 9000, 9443, 2375, and 2376.
- Safely queries live host resources, CPU, raw memory (`/proc/meminfo`), storage, swap, UFW rules, and active listeners over SSH without shell-quoting ambiguity.
- Gathers Docker daemon version, container health status, networks, volumes, and tails container logs.

---

## 4. Updated Repository Documentation

The following canonical documentation files have been refreshed:

1. **[docs/infrastructure-inventory.md](docs/infrastructure-inventory.md)**: Updated with the live system specifications (12 GB RAM, 200 GB SSD, 6 vCPU), kernel version, UFW configuration, Docker engine details, and container inventories.
2. **[.ai/transient/sprint/00-current-state.md](.ai/transient/sprint/00-current-state.md)**: Updated to mark Phase D as complete, operational, and verified.
3. **[docs/reports/vps-post-deployment-security-audit-2026-10-22.md](docs/reports/vps-post-deployment-security-audit-2026-10-22.md)**: Comprehensive security audit report providing full command-level evidence and PASS/FAIL/INCONCLUSIVE matrices.
4. **[docs/devops-handover-runbook.md](docs/devops-handover-runbook.md)**: Practical operational runbook for DevOps engineers covering routine diagnostics, logging, restarts, Portainer volume backups/restores, upgrades, and how to safely onboard future application routes.

---

## 5. Remaining Owner Actions & Recommendations

1. **Cloudflare Access Identity Policies:** Ensure that your Cloudflare Zero Trust Access policy under `Log in to Portainer Devops` restricts access strictly to authorized email addresses/domains.
2. **Automate Volume Backups:** Set up a nightly cron job on the host running the volume backup procedure documented in Section 4.B of [docs/devops-handover-runbook.md](docs/devops-handover-runbook.md).
