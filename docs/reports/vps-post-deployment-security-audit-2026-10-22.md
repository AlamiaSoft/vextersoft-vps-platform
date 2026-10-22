# VPS Post-Deployment Security & Configuration Audit Report

**Date of Audit:** 2026-10-22
**Target Host Identifier:** `vmi3682629`
**Target Host IPv4:** `<TARGET_HOST_IPV4>` (Resolved via ignored `ansible/inventory/hosts.yml`)
**Target Host IPv6:** `<TARGET_HOST_IPV6>`
**Management Ingress:** `https://devops.vextersoft.com`
**Auditor:** Automated Agentic Security Framework (Antigravity)
**Overall Deployment Status:** **PARTIALLY VERIFIED (OPERATIONAL — EXTERNAL IPV6 & LIVE BACKUP PROOF PENDING)**

---

## 1. Executive Summary

A post-deployment security, host configuration, access control, and network exposure audit was conducted on the VexterSoft Contabo Ubuntu 24.04 LTS VPS following the completion of Phase D (Cloudflare Tunnel + Private Portainer CE Ingress).

While the management stack is live and all testable controls passed, overall audit sign-off is classified as **PARTIALLY VERIFIED** until two pending operational proofs are completed: (1) an external port scan from an IPv6-native network vantage point, and (2) an executed off-host Portainer volume backup and supervised sandbox restore on the VPS.

Summary of findings:
1. **Cloudflare Access Verification [PASS]:** Unauthenticated external HTTP requests to `https://devops.vextersoft.com` are intercepted by Cloudflare Edge with a `302 Found` redirect to `vextersoft.cloudflareaccess.com`, demanding email OTP authentication ("Log in to Portainer Devops") before any traffic reaches Portainer.
2. **Zero Exposed Management Sockets [PASS]:** Ports `9000`, `9443`, `8000`, `2375`, and `2376` are not listening on `0.0.0.0`, `[::]`, or `127.0.0.1` on the host. Container communication occurs strictly across the isolated internal Docker bridge network `vextersoft-management`.
3. **Direct Origin Inaccessibility (IPv4) [PASS]:** Independent external TCP socket probes from an external network confirmed that ports 80, 443, 9000, 9443, 8000, 2375, and 2376 are closed/unreachable on `<TARGET_HOST_IPV4>`.
4. **Direct Origin Inaccessibility (IPv6) [PENDING / INCONCLUSIVE - External Vantage · PASS - Host Inspection]:** On the host, UFW denies all routed/incoming IPv6 traffic except port 22, and `ss -tulpn` confirms only `[::]:22` is listening. However, host firewall inspection is **not** a substitute for an external IPv6 probe: because the audit workstation lacked IPv6 ISP routing (`[WinError 10051]`), external IPv6 reachability remains **PENDING / INCONCLUSIVE** until tested from an IPv6-capable external host.
5. **Host Hardening Baseline [PASS]:** UFW is active with `default deny incoming`, `default allow outgoing`, and `default deny routed`. Fail2ban `sshd` jail is actively monitoring systemd journal logs. SSH password and keyboard-interactive authentication are disabled; only Ed25519 key authentication is permitted.
6. **Zero Secrets in Git & Vault Lifecycle [PASS]:** Local Vault file `ansible/vault/vextersoft_vps.vault.yml` was deleted post-deployment by the owner. Git history inspection confirms the file was **never committed**. The running tunnel container reads its persistent secret at `/opt/vextersoft/management/secrets/tunnel-token` (`mode 0440`, owned by `root:65532`).
7. **Backup & Sandbox Restore Readiness [PROCEDURE DOCUMENTED / CI MECHANICS TESTED / LIVE OFF-HOST BACKUP & SUPERVISED RESTORE PENDING]:** Reusable helper `scripts/portainer_backup.py` and runbook instructions are implemented and tested in GitHub Actions using disposable Docker volumes and real Portainer CE containers. Executing the first live off-host backup copy and supervised sandbox restore on the VPS remains pending.

---

## 2. Findings Matrix

| Finding ID | Area | Target / Property | Status | Evidence & Test Limitations |
| :--- | :--- | :--- | :---: | :--- |
| **SEC-01** | Ingress | Cloudflare Access Identity Gate | **PASS** | `curl -v -L https://devops.vextersoft.com/` receives `302 Found` with `Www-Authenticate: Cloudflare-Access` and redirects to `https://vextersoft.cloudflareaccess.com` login form ("Log in to Portainer Devops"). Unauthenticated access to Portainer is blocked. |
| **SEC-02** | Exposure | IPv4 Management Ports (9000, 9443, 8000) | **PASS** | External TCP socket probe to `<TARGET_HOST_IPV4>` timed out / refused on all management ports. Zero host port mappings in Docker Compose. |
| **SEC-03** | Exposure | IPv4 Docker API Ports (2375, 2376) | **PASS** | External TCP probe to `<TARGET_HOST_IPV4>` on ports 2375 and 2376 confirmed closed. Docker daemon socket restricted to `/var/run/docker.sock` (`mode 0660`, `root:docker`). |
| **SEC-04** | Exposure | External IPv6 Management Exposure | **PENDING / INCONCLUSIVE (External) · PASS (Host)** | Host-level: UFW default deny routed/incoming, `ss -tulpn` shows only `[::]:22` listening. External probe from test workstation could not traverse IPv6 (`[WinError 10051]`); external IPv6 reachability remains pending an IPv6-capable external vantage test. |
| **SEC-05** | Host SSH | Pubkey Authentication Enforced | **PASS** | `sudo sshd -T` confirms `pubkeyauthentication yes`, `passwordauthentication no`, `kbdinteractiveauthentication no`, `permitrootlogin without-password`. |
| **SEC-06** | Host Firewall | UFW Restrictive Baseline | **PASS** | `sudo ufw status verbose` confirms active status, default incoming deny, default routed deny, and only port 22/tcp allowed. |
| **SEC-07** | Host IDS | Fail2ban Active Protection | **PASS** | `fail2ban-client status sshd` reports active jail monitoring journald, with over 350 malicious brute-force IPs banned. |
| **SEC-08** | Storage | Resource Allocation Reconciliation | **PASS** | Raw `/proc/meminfo` confirms `MemTotal: 12247552 kB` (12 GB contracted RAM / ~11.68 GiB binary OS-usable) and `df -h /` confirms 193 GiB ext4 SSD (`/dev/sda1` on 200 GB disk), matching the Contabo Cloud VPS 6 plan. |
| **SEC-09** | Secret Hygiene | Vault File Untracked in Git | **PASS** | `git log --all --full-history -- ansible/vault/vextersoft_vps.vault.yml` confirmed 0 commits. `.gitignore` rule active. |
| **SEC-10** | Backup | Volume Backup & Sandbox Restore | **PROCEDURE DOCUMENTED / CI MECHANICS TESTED / LIVE PROOF PENDING** | Shared helper `scripts/portainer_backup.py` and runbook cover quiesced `try...finally` restart, archive integrity verification, and isolated sandbox restore. CI tests mechanics in an ephemeral runner; live off-host backup copy and supervised VPS sandbox restore remain pending. |

---

## 3. Detailed Audit Evidence & Technical Diagnostics

### 3.1 Cloudflare Access & Public Ingress Verification
A completely unauthenticated HTTP request was issued against the public management URL from an external network with clean cookie and cache states:

```bash
curl.exe -v -s -L --max-redirs 5 https://devops.vextersoft.com/
```

**Observed Redirect Chain & Headers:**
```http
> GET / HTTP/1.1
> Host: devops.vextersoft.com
< HTTP/1.1 302 Found
< Date: Thu, 22 Oct 2026 09:58:37 GMT
< Www-Authenticate: Cloudflare-Access resource_metadata="https://devops.vextersoft.com/.well-known/cloudflare-access-protected-resource/"
< Location: https://vextersoft.cloudflareaccess.com/cdn-cgi/access/login/devops.vextersoft.com?kid=2004855daf51bfad9072ed4bca11bfcaf84ca419d9849693347226e9100e6514&...
```

**Terminating Response Content (Sanitized Excerpt):**
```html
<div class="AuthBox-App">
  <h1 class="Card-title">Log in to Portainer Devops</h1>
</div>
<form class="AuthFormLogin" action="https://vextersoft.cloudflareaccess.com/cdn-cgi/access/verify-code/devops.vextersoft.com..." method="post">
  <label for="email">Email</label>
  <input id="email" class="EmailInput" type="email" required placeholder="example@email.com">
  <button type="submit" class="Button Button-is-primary">Send login code</button>
</form>
```
*Conclusion:* The public hostname `devops.vextersoft.com` routes through Cloudflare Access. Unauthenticated visitors cannot reach the Portainer setup or login screen.

---

### 3.2 Direct Origin External Accessibility Audit

Independent network socket probes were executed against origin IPv4 (`<TARGET_HOST_IPV4>`) and IPv6 (`<TARGET_HOST_IPV6>`) from an external workstation:

```text
--- IPv4 Connectivity Test: <TARGET_HOST_IPV4> ---
  Port    22/tcp (SSH Administrative Port)        -> OPEN                 [PASS]
  Port    80/tcp (HTTP Web Standard)              -> CLOSED / FILTERED    [PASS]
  Port   443/tcp (HTTPS Web Standard)             -> CLOSED / FILTERED    [PASS]
  Port  8000/tcp (Portainer Edge Tunnel)          -> CLOSED / FILTERED    [PASS]
  Port  9000/tcp (Portainer Internal HTTP)        -> CLOSED / FILTERED    [PASS]
  Port  9443/tcp (Portainer Internal HTTPS)       -> CLOSED / FILTERED    [PASS]
  Port  2375/tcp (Docker Insecure API)            -> CLOSED / FILTERED    [PASS]
  Port  2376/tcp (Docker TLS API)                 -> CLOSED / FILTERED    [PASS]

--- IPv6 Connectivity Test: <TARGET_HOST_IPV6> ---
  External Client Reachability                    -> PENDING / INCONCLUSIVE (Client ISP IPv4-only route)
  Host-Level IPv6 UFW Policy                      -> PASS (Default deny routed/incoming)
  Host-Level IPv6 Listening Sockets               -> PASS (Only [::]:22 active; zero management listeners)
```

---

### 3.3 Root Cause Analysis of Previous Diagnostic Exit Code 1
In an earlier diagnostic step, the command `SSH and user diagnostic` failed with exit code 1:
- **Observed Error:** `/bin/bash: -c: line 1: syntax error near unexpected token '('`
- **Root Cause:** When running `wsl bash -c` from PowerShell, nested unescaped parentheses in `grep -E \"^(pubkeyauthentication|...)\"` were evaluated by PowerShell rather than remote bash, causing a local client syntax error before the SSH connection opened.
- **Verification:** Direct execution of `sudo sshd -T` without nested shell quoting succeeded with exit code 0 (`rc=0`), confirming full compliance of the remote SSH daemon.

---

### 3.4 Docker Container Health & Volume Persistence
- **Runtime:** Docker Engine `29.9.2` (API `1.56`), Docker Compose v2 plugin.
- **Container Health & Status (`sudo docker ps -a`):**
  ```text
  NAMES                                 IMAGE                                  STATUS                    PORTS
  vextersoft-management-portainer-1     portainer/portainer-ce:2.45.1-alpine   Up (healthy)              8000/tcp, 9000/tcp, 9443/tcp (internal)
  vextersoft-management-cloudflared-1   cloudflare/cloudflared:2026.10.2       Up (healthy)              (egress only)
  ```
- **Portainer Healthcheck:** BusyBox `wget` HTTP spider hitting `http://127.0.0.1:9000/api/system/status` every 30s.
- **Cloudflared Healthcheck:** `cloudflared tunnel --metrics 127.0.0.1:2000 ready` every 30s.
- **Persistent Storage:** Volume `vextersoft_portainer_data` mounted at `/data` inside Portainer. Initial admin account and local environment connection (`vextersoft-vps`) safely stored in BoltDB.

---

## 4. Operational Vault Lifecycle & Recovery Procedure

1. **Local Vault Deletion Verified:** `ansible/vault/vextersoft_vps.vault.yml` was deleted locally post-deployment by the owner to avoid retaining a forgotten Vault password.
2. **Git History Cleanliness:** `git log --all --full-history -- ansible/vault/vextersoft_vps.vault.yml` confirms that the file was **never committed to Git history**.
3. **Server-Side Secret Invariant:** The running `cloudflared` container reads its token directly from `/opt/vextersoft/management/secrets/tunnel-token` (`mode 0440`, owned by `root:65532`).
4. **Recovery Procedure:** Documented in `docs/devops-handover-runbook.md`. If redeployment is needed, obtain the token from Cloudflare Zero Trust, run `ansible-vault create`, choose a new password, and deploy with `--ask-vault-pass`.

---

## 5. Audit Conclusion & Remaining Operational Proof Items

The deployment is **OPERATIONAL** and all directly testable controls (`SEC-01` through `SEC-03`, `SEC-05` through `SEC-09`) passed verification. Overall security sign-off remains **PARTIALLY VERIFIED** until the following two non-code operational proofs are recorded:
1. **External IPv6 Reachability (`SEC-04`):** Execute `python3 scripts/diagnostics/audit_vps_live.py --target-ip <TARGET_HOST_IPV6>` from an IPv6-capable external network to complement the verified host-level UFW and socket state.
2. **Live Off-Host Backup & Supervised Sandbox Restore (`SEC-10`):** Execute `scripts/portainer_backup.py backup` on the VPS, transfer the verified archive to an approved off-host storage destination, and run a supervised `restore-sandbox` test into a disposable volume.
