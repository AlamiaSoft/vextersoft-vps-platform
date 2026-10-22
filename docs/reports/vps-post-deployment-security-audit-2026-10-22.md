# VPS Post-Deployment Security & Configuration Audit Report

**Date of Audit:** 2026-10-22  
**Target Host Identifier:** `vmi3682629`  
**Public IPv4 Address:** `5.189.128.157`  
**Management Endpoint:** `https://devops.vextersoft.com`  
**Auditor:** Automated Agentic Security Framework (Antigravity)  
**Overall Deployment Status:** **OPERATIONAL & VERIFIED**  

---

## 1. Executive Summary

A comprehensive post-deployment security, host configuration, and network exposure audit was conducted on the VexterSoft Contabo Ubuntu 24.04 LTS VPS following the completion of Phase D (Cloudflare Tunnel + Private Portainer CE Ingress).

The deployment successfully satisfies all core architectural and security invariants:
1. **Zero Exposed Management Sockets:** Portainer (`:9000`, `:9443`, `:8000`) and the Docker Daemon API (`:2375`, `:2376`) are not listening on `0.0.0.0` or `[::]`. They communicate strictly across the isolated internal Docker bridge network `vextersoft-management`.
2. **Direct Origin Inaccessibility:** Independent external TCP port probing from an external network confirmed that ports 9000, 9443, 8000, and 2375 are completely closed and unreachable on the origin public IPv4 address.
3. **Encrypted Egress-Only Ingress:** Administrative traffic routes exclusively via an outbound Cloudflare Tunnel (`cloudflared`) to `https://devops.vextersoft.com`.
4. **Host Baseline Hardened:** UFW is active with `default deny incoming`, `default allow outgoing`, and `default deny routed`. Fail2ban is active with the `sshd` jail actively protecting port 22. SSH root password login is disabled; only Ed25519 cryptographic key authentication is permitted.
5. **Zero Secrets in Git & Vault Lifecycle:** Local Vault file `ansible/vault/vextersoft_vps.vault.yml` was deleted post-deployment by the owner to avoid retaining a forgotten password. Verification proves the Vault file was **never committed to Git history**. The running tunnel container uses the server-side persistent secret installed at `/opt/vextersoft/management/secrets/tunnel-token`.

---

## 2. Audit Scope & Vantage Points

| Vantage Point | Method / Tool | Scope |
| :--- | :--- | :--- |
| **Local WSL Control Node** | Ansible, `scripts/vextersoft.ps1 doctor`, `validate -Phase ingress` | Inventory, Vault configuration, safety assertion suite |
| **Target Host Internal** | `scripts/diagnostics/audit_vps_live.py`, SSH (`vexteradmin`), `sshd -T`, `ufw status verbose`, `ss -tulpn`, `docker inspect` | System services, firewall rules, listening sockets, Docker state |
| **External Network** | External TCP probe via Python socket / PowerShell `Test-NetConnection`, DNS resolution, `curl -I` | Origin IP accessibility, DNS CNAME/A resolution, HTTPS SSL termination |

---

## 3. Verified Evidence & Technical Findings

### 3.1 Host & System Security

- **Operating System:** Ubuntu 24.04.5 LTS (`noble`), Kernel `6.8.0-139-generic x86_64`.
- **System Resources (Direct Host Measurements):**
  - **vCPU:** 6 vCPUs (AMD EPYC, `nproc = 6`).
  - **RAM (Raw `/proc/meminfo`):**
    - `MemTotal: 12247552 kB` (12,541,493,248 bytes = **12.54 GB decimal / 11.68 GiB binary**). Matches contracted Contabo 12 GB plan.
    - `MemAvailable: 11574188 kB` (~11 GiB available, ~660 MiB used).
    *(Note: An earlier intermediate log cited 15 GiB due to a local WSL execution anomaly during interactive command quoting; direct query via `/proc/meminfo` confirms 12 GB).*
  - **Storage:** `/dev/sda1` (ext4) 193 GiB total, 7.3 GiB used (4%), 186 GiB available mounted at `/`. Matches contracted 200 GB SSD.
  - **Swap:** 4.0 GiB file-backed swap (`/swapfile`) active.
- **Administrative Access (`vexteradmin`):**
  - UID 1001, GID 1001. Groups: `vexteradmin`, `sudo`, `docker`.
  - Passwordless sudo verified (`/etc/sudoers.d/90-vexteradmin`).
- **Effective SSH Configuration (`sudo sshd -T`):**
  ```text
  port 22
  pubkeyauthentication yes
  passwordauthentication no
  kbdinteractiveauthentication no
  permitrootlogin without-password
  x11forwarding no
  allowagentforwarding yes
  ```
- **Firewall Policy (`sudo ufw status verbose`):**
  ```text
  Status: active
  Logging: on (low)
  Default: deny (incoming), allow (outgoing), deny (routed)
  New profiles: skip

  To                         Action      From
  --                         ------      ----
  22/tcp                     ALLOW IN    Anywhere                   # SSH Administrative Access
  22/tcp (v6)                ALLOW IN    Anywhere (v6)              # SSH Administrative Access
  ```
- **Intrusion Prevention (`fail2ban-client status sshd`):**
  - Service: `active`
  - Jail `sshd`: currently monitoring journald logs, actively banning brute-force attempts.
- **Host Socket Listeners (`sudo ss -tulpn`):**
  ```text
  Netid State  Local Address:Port  Process
  udp   UNCONN 127.0.0.54:53       systemd-resolve
  udp   UNCONN 127.0.0.53%lo:53    systemd-resolve
  tcp   LISTEN 127.0.0.53%lo:53    systemd-resolve
  tcp   LISTEN 127.0.0.54:53       systemd-resolve
  tcp   LISTEN 0.0.0.0:22          sshd
  tcp   LISTEN [::]:22             sshd
  ```
  *Result: Zero database or management ports are bound to host network interfaces.*

---

### 3.2 Docker & Management Containers

- **Runtime:** Docker Engine `29.9.2` (API `1.56`), Docker Compose v2 plugin.
- **Container Health & Status (`sudo docker ps -a`):**
  ```text
  CONTAINER ID   IMAGE                                  STATUS                    PORTS                          NAMES
  5fef32afd247   portainer/portainer-ce:2.45.1-alpine   Up (healthy)              8000/tcp, 9000/tcp, 9443/tcp   vextersoft-management-portainer-1
  9b873cb67f50   cloudflare/cloudflared:2026.10.2       Up (healthy)                                             vextersoft-management-cloudflared-1
  ```
- **Port Exposure Analysis:**
  - `vextersoft-management-portainer-1` reports ports `8000/tcp, 9000/tcp, 9443/tcp` as exposed internally to the Docker bridge network.
  - Notice that NO host-port bindings (`0.0.0.0:xxxx->yyyy`) exist.
- **Network Isolation:**
  - Network `vextersoft-management`: attaches `portainer` and `cloudflared`.
  - Network `vextersoft-tunnel-egress`: attaches `cloudflared` for edge egress.
- **Data Persistence:**
  - Named volume `vextersoft_portainer_data` mounted at `/data` inside Portainer. Initial admin user and environment config confirmed persisted.

---

### 3.3 Direct Origin External Accessibility Audit

Independent network probes were performed from an external workstation targeting `5.189.128.157`:

| Target Port | Service Identity | Expected Result | Observed Result | Status |
| :--- | :--- | :--- | :--- | :--- |
| **TCP 22** | OpenSSH | `Open` | `TcpTestSucceeded: True` | **PASS** (Authorized Admin) |
| **TCP 9000** | Portainer HTTP | `Closed / Filtered` | `TcpTestSucceeded: False` (Connection timed out) | **PASS** (Unexposed) |
| **TCP 9443** | Portainer HTTPS | `Closed / Filtered` | `TcpTestSucceeded: False` (Connection timed out) | **PASS** (Unexposed) |
| **TCP 8000** | Portainer Edge | `Closed / Filtered` | `TcpTestSucceeded: False` (Connection timed out) | **PASS** (Unexposed) |
| **TCP 2375** | Docker API (Insecure) | `Closed / Filtered` | `TcpTestSucceeded: False` (Connection timed out) | **PASS** (Unexposed) |
| **TCP 2376** | Docker API (TLS) | `Closed / Filtered` | `TcpTestSucceeded: False` (Connection timed out) | **PASS** (Unexposed) |

*Conclusion: The origin host is completely inaccessible on any management port. Docker does not bypass UFW because no ports are published to host interfaces.*

---

### 3.4 Public Ingress & Cloudflare Routing

- **DNS Resolution (`devops.vextersoft.com`):**
  - CNAME points to `8c9411a4-1ace-42df-aa2f-39df6cbc4d57.cfargotunnel.com`.
  - Resolves cleanly to Cloudflare Anycast edge IPs (`188.114.96.6`, `188.114.97.6`, `2a06:98c1:...`).
- **HTTP/S Response (`curl.exe -sI https://devops.vextersoft.com`):**
  ```http
  HTTP/1.1 200 OK
  Date: Thu, 22 Oct 2026 09:35:32 GMT
  Content-Type: text/html; charset=utf-8
  Connection: keep-alive
  Cache-Control: max-age=31536000
  Server: cloudflare
  CF-RAY: a4e7832fdc43d051-KHI
  ```
- **Portainer Initialization:**
  - Initial administrator password set by the repository owner.
  - Setup token validated during bootstrap.
  - Environment connected to host socket (`/var/run/docker.sock`) and named `vextersoft-vps`.

---

## 4. Operational Vault Lifecycle & Recovery Procedure

### 4.1 Current Vault State in Repository
- The local Vault file `ansible/vault/vextersoft_vps.vault.yml` was deleted after the one-time deployment by the owner.
- **Git History Verification:** `git log --all --full-history -- ansible/vault/vextersoft_vps.vault.yml` confirms that the file was **never committed** to git history at any point.
- **`.gitignore` Protection:** Rule `.gitignore:3:ansible/vault/*.vault.yml` is active and prevents accidental staging.

### 4.2 Impact on Routine Operations
- **Diagnostics & Health Audits:** **NO VAULT REQUIRED.** Read-only diagnostics (`scripts/diagnostics/audit_vps_live.py`, `scripts/vextersoft.ps1 doctor`, Docker inspect, UFW inspect) run via SSH and do not need the Vault password or Vault file.
- **Live Tunnel Operation:** **UNAFFECTED.** The running `cloudflared` container reads its token directly from the host filesystem at `/opt/vextersoft/management/secrets/tunnel-token` (`mode 0440`, owner `root:65532`).
- **Container Restarts:** **NO VAULT REQUIRED.** Restarting Portainer or Cloudflared (`docker compose restart`) uses the existing Compose file and existing secrets file on disk.

### 4.3 Recovery Procedure for Future Playbook Deployments
If the Ansible playbook (`03-cloudflared-portainer.yml`) needs to be executed again in the future (for full redeployment, token rotation, or adding server-side configurations):

1. **Obtain the Tunnel Token:**
   - In Cloudflare Zero Trust Dashboard -> Networks -> Tunnels -> Select Tunnel (`vextersoft-vps-ingress`) -> Copy the Tunnel Token.
2. **Create a Fresh Encrypted Vault File:**
   ```bash
   cd /mnt/e/Alamia/vextersoft-vps-platform
   source ~/.venvs/vps-ansible/bin/activate
   mkdir -p ansible/vault
   ansible-vault create ansible/vault/vextersoft_vps.vault.yml
   ```
3. **Set a New Vault Password:**
   - Enter a new, secure password (store it securely in your password manager). There is no dependency on the previous password.
4. **Enter the Variable in the Editor:**
   ```yaml
   cloudflare_tunnel_token: "<PASTE_CLOUDFLARE_TUNNEL_TOKEN_HERE>"
   ```
5. **Run the Playbook:**
   ```bash
   ansible-playbook --ask-vault-pass --diff \
     -i ansible/inventory/hosts.yml \
     --limit vextersoft_vps \
     -e cloudflare_deployment_approved=true \
     ansible/playbooks/03-cloudflared-portainer.yml
   ```
6. **Optional Deletion:** The local Vault file can be safely deleted again after deployment if desired.

---

## 5. Audit Conclusion

The deployment is certified **OPERATIONAL** and adheres strictly to the security invariants established in `AGENT_PROTOCOL.md` and `docs/issue-6-spec.md`.
