# VexterSoft VPS — Post-Deployment Audit, Documentation & DevOps Handover

## Executive Overview & Deployment Status

- **Status:** **PARTIALLY VERIFIED (OPERATIONAL — EXTERNAL IPV6 & LIVE BACKUP PROOF PENDING)**
- **Audit Date:** 2026-10-22
- **Target Host:** Contabo Ubuntu 24.04.5 LTS VPS (`vmi3682629` / `<TARGET_HOST_IPV4>`)
- **Contracted Hardware Profile:** 6 vCPU / 12 GB contracted RAM (~11.68 GiB OS-usable) / 200 GB SSD (~193 GiB ext4) (Verified via `/proc/meminfo` and `df -h`)
- **Management Ingress:** `https://devops.vextersoft.com/` (Portainer CE 2.45.1-alpine)
- **Access Control:** Outbound Cloudflare Argo Tunnel connector protected by Cloudflare Access identity policy; UFW default deny incoming.

---

## 1. Post-Deployment Audit Summary & Findings Matrix

| Finding ID | Area | Target / Property | Status | Evidence & Test Limitations |
| :--- | :--- | :--- | :---: | :--- |
| **SEC-01** | Ingress | Cloudflare Access Identity Gate | **PASS** | `curl -v -L https://devops.vextersoft.com/` receives `302 Found` with `Www-Authenticate: Cloudflare-Access` and redirects to `https://vextersoft.cloudflareaccess.com` login form ("Log in to Portainer Devops"). Unauthenticated access to Portainer is blocked. |
| **SEC-02** | Exposure | IPv4 Management Ports (9000, 9443, 8000) | **PASS** | External TCP socket probe to `<TARGET_HOST_IPV4>` timed out / refused on all management ports. Zero host port mappings in Docker Compose. |
| **SEC-03** | Exposure | IPv4 Docker API Ports (2375, 2376) | **PASS** | External TCP probe to `<TARGET_HOST_IPV4>` on ports 2375 and 2376 confirmed closed. Docker daemon socket restricted to `/var/run/docker.sock` (`mode 0660`, `root:docker`). |
| **SEC-04** | Exposure | External IPv6 Management Exposure | **PENDING / INCONCLUSIVE (External) · PASS (Host)** | Host-level: UFW default deny routed/incoming, `ss -tulpn` shows only `[::]:22` listening. External probe from test workstation was inconclusive due to client-side IPv4-only ISP routing (`[WinError 10051]`). |
| **SEC-05** | Host SSH | Pubkey Authentication Enforced | **PASS** | `sudo sshd -T` confirms `pubkeyauthentication yes`, `passwordauthentication no`, `kbdinteractiveauthentication no`, `permitrootlogin without-password`. |
| **SEC-06** | Host Firewall | UFW Restrictive Baseline | **PASS** | `sudo ufw status verbose` confirms active status, default incoming deny, default routed deny, and only port 22/tcp allowed. |
| **SEC-07** | Host IDS | Fail2ban Active Protection | **PASS** | `fail2ban-client status sshd` reports active jail monitoring journald, with over 350 malicious brute-force IPs banned. |
| **SEC-08** | Storage | Resource Allocation Reconciliation | **PASS** | Raw `/proc/meminfo` confirms `MemTotal: 12247552 kB` (12 GB contracted RAM / ~11.68 GiB OS-usable) and `df -h /` confirms 193 GiB ext4 SSD (`/dev/sda1`), matching the Contabo plan. |
| **SEC-09** | Secret Hygiene | Vault File Untracked in Git | **PASS** | `git log --all --full-history -- ansible/vault/vextersoft_vps.vault.yml` confirmed 0 commits. `.gitignore` rule active. |
| **SEC-10** | Backup | Volume Backup & Sandbox Restore | **PROCEDURE DOCUMENTED / CI MECHANICS TESTED / LIVE PROOF PENDING** | Shared helper `scripts/portainer_backup.py` and runbook cover quiesced `try...finally` restart, archive verification, and isolated sandbox restore. Automated CI tests mechanics in an ephemeral runner; live off-host backup copy and supervised VPS sandbox restore remain pending. |

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
- **External IPv6 (`<TARGET_HOST_IPV6>`):** Marked `PENDING / INCONCLUSIVE` from the external vantage point because the test workstation lacked IPv6 ISP routing (`[WinError 10051]`). Host-level `ufw status verbose` and `ss -tulpn` were verified separately (`PASS`), but are not treated as a substitute for an external IPv6 probe.

### 2.3 SSH Diagnostic Exit Code 1 Investigation
- **Observed Behavior:** An earlier interactive diagnostic step failed with exit code 1 (`syntax error near unexpected token '('`).
- **Investigation:** Caused by Windows PowerShell stripping nested quotes when invoking `wsl bash -c` with regex parentheses `grep -E "^(...)"`.
- **Finding:** Purely a client-side PowerShell shell quoting artifact. When executed cleanly, `sudo sshd -T` returned `0`, verifying strict enforcement of public key authentication and disabled password logins.

### 2.4 RAM Specification Reconciliation
- **Owner Query:** Investigation into documented Contabo 12 GB RAM versus earlier mention of 15 GiB.
- **Evidence:** Raw query of `/proc/meminfo` on `vmi3682629` confirms `MemTotal: 12247552 kB` (12,541,493,248 bytes = 12 GB contracted RAM / ~11.68 GiB binary OS-usable), matching the Contabo plan. The 15 GiB figure originated from an accidental local WSL2 command execution during nested quote stripping.

### 2.5 Vault File Lifecycle & Secret Hygiene
- **Vault File Status:** `ansible/vault/vextersoft_vps.vault.yml` was deleted locally post-deployment by the owner to prevent holding a forgotten Vault password.
- **Git History Inspection:** Confirmed never tracked or committed (`git log --all --full-history` returned 0 commits).
- **Server-Side Secret Invariant:** Live container reads `/opt/vextersoft/management/secrets/tunnel-token` (`mode 0440`, owned by `root:65532`). Deleting the local Vault file has zero impact on live tunnel health or reboot recovery.

---

## 3. Persistent Operational Tooling

Per repository standards, reusable operational utilities are maintained in `scripts/`:

1. **[scripts/diagnostics/audit_vps_live.py](scripts/diagnostics/audit_vps_live.py)**
   - Resolves the target host deterministically via `ansible/inventory/hosts.yml` and `scripts/resolve_ansible_target.py` (or explicit validated `--target-ip`), failing closed on missing, placeholder (`<...>`), or documentation-range (`192.0.2.1`) targets.
   - Probes external TCP reachability for ports 22, 80, 443, 8000, 9000, 9443, 2375, and 2376 (reporting `INCONCLUSIVE` when local IPv6 routing is unavailable).
   - Safely queries live host resources, CPU, raw memory (`/proc/meminfo`), storage, swap, UFW rules, and active listeners over SSH without shell-quoting ambiguity.
2. **[scripts/portainer_backup.py](scripts/portainer_backup.py)**
   - Single reusable helper for Portainer volume backup (`backup`), archive integrity verification (`verify-archive`), and isolated sandbox restoration (`restore-sandbox`).
   - Guarantees restarting Portainer in a `try...finally` block during quiesced backups and refuses production or non-empty target volumes during sandbox restores.

---

## 4. Updated Repository Documentation

The following canonical documentation files have been refreshed:

1. **[docs/infrastructure-inventory.md](docs/infrastructure-inventory.md)**: Updated with the live system specifications (12 GB contracted RAM / ~11.68 GiB OS-usable, 200 GB SSD / ~193 GiB ext4, 6 vCPU), kernel version, UFW configuration, Docker engine details, and container inventories.
2. **[.ai/transient/sprint/00-current-state.md](.ai/transient/sprint/00-current-state.md)**: Updated to reflect Phase D operational status and pending external IPv6 / live backup proof items.
3. **[docs/reports/vps-post-deployment-security-audit-2026-10-22.md](docs/reports/vps-post-deployment-security-audit-2026-10-22.md)**: Comprehensive security audit report providing full command-level evidence and PASS/FAIL/INCONCLUSIVE matrices.
4. **[docs/devops-handover-runbook.md](docs/devops-handover-runbook.md)**: Practical operational runbook for DevOps engineers and trainees covering routine diagnostics, `scripts/portainer_backup.py` backup/restore procedures, trainee stop/escalation gates, and onboarding future application routes.

---

## 5. Remaining Owner Actions & Pending Operational Proof

1. **Cloudflare Access Identity Policies:** Confirm that the Cloudflare Zero Trust Access policy under `Log in to Portainer Devops` restricts access strictly to authorized email addresses/domains.
2. **First Off-Host Backup & Supervised Sandbox Restore (`SEC-10`):** Designate an approved off-host backup location, run `scripts/portainer_backup.py backup` on the VPS during an approved window, copy the verified archive off-host, and execute a supervised `restore-sandbox` test.
3. **External IPv6 Vantage Scan (`SEC-04`):** Run `python3 scripts/diagnostics/audit_vps_live.py --target-ip <TARGET_HOST_IPV6>` from an IPv6-capable external network to close the external IPv6 reachability item.
