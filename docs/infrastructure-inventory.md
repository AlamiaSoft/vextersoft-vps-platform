# Infrastructure Inventory & Host Baseline

**Host Identifier:** `vmi3682629`  
**Provider:** Contabo Cloud VPS  
**Public IPv4:** `<TARGET_HOST_IPV4>` (Refer to private inventory / `.env`)  
**Public IPv6:** `<TARGET_HOST_IPV6>`  
**Last Audit Date:** 2026-10-22  
**Audit Type:** Post-Deployment Verification & Security Audit  
**Status:** Deployed & Operational (Phase A through D Complete)  

---

## 1. Compute & Virtualization
- **Hypervisor:** KVM (QEMU virtual machine)
- **vCPU Cores:** 6 vCPUs (AMD EPYC, Little Endian x86_64)
- **Memory (RAM):** 15 GiB Total (~610 MiB Used, ~14 GiB Available)
- **Swap:** 4.0 GiB partition (`/dev/sdc`) active with priority -2

---

## 2. Operating System & Kernel
- **Distribution:** Ubuntu 24.04.1 LTS (Noble Numbat)
- **Kernel Version:** Linux 6.8.0-139-generic x86_64
- **Init System:** Systemd 255
- **Time Synchronization:** systemd-timesyncd active

---

## 3. Storage & Partitions
- **Primary Block Device:** `/dev/sdd` (ext4)
- **Partition Layout:**
  - `/dev/sdd`: 1007 GiB total, 4.4 GiB used (1%), 952 GiB available mounted at `/`
  - `/dev/sdc`: 4.0 GiB swap partition
- **Docker Persistent Storage:**
  - Volume: `vextersoft_portainer_data` (Driver: local) mounted at `/data` in Portainer

---

## 4. Host Firewall & Security Posture
- **Firewall (UFW):** Active
  - **Default Policies:** `deny (incoming)`, `allow (outgoing)`, `deny (routed)`
  - **Inbound Rules:**
    - `22/tcp ALLOW IN Anywhere` (SSH Administrative Access)
    - `22/tcp (v6) ALLOW IN Anywhere (v6)` (SSH Administrative Access)
  - **Forwarding Rules:** Zero database DNAT rules; routed traffic default denied.
- **Fail2ban:** Active
  - **Jails:** `sshd` active, monitoring systemd journal, actively banning brute-force attempts.
- **SSH Daemon Configuration (`sshd -T` verified):**
  - `port 22`
  - `pubkeyauthentication yes`
  - `passwordauthentication no`
  - `kbdinteractiveauthentication no`
  - `permitrootlogin without-password`
  - `x11forwarding no`
  - `allowagentforwarding yes`
- **User Accounts:**
  - `vexteradmin` (UID 1001, GID 1001, Groups: `vexteradmin`, `sudo`, `docker`)
  - Passwordless sudo configured via `/etc/sudoers.d/90-vexteradmin` (`(ALL) NOPASSWD: ALL`)

---

## 5. Docker & Management Services
- **Docker Engine:** `29.9.2` (API: `1.48`)
- **Docker Compose:** v2 plugin installed
- **Daemon Configuration:** Restricted socket `/var/run/docker.sock` (mode `0660`, group `docker`), no TCP listeners (`0.0.0.0:2375`/`2376` absent).
- **Management Project Location:** `/opt/vextersoft/management`
  - Permissions: directory `0750`, `secrets/` directory `0700`
  - Tunnel Token Secret: `/opt/vextersoft/management/secrets/tunnel-token` (`mode 0440`, owner `root:65532`)
- **Active Containers:**
  - `vextersoft-management-portainer-1`:
    - Image: `portainer/portainer-ce:2.45.1-alpine`
    - Status: `Up (healthy)`
    - Ports: `8000/tcp, 9000/tcp, 9443/tcp` (INTERNAL ONLY to Docker network `vextersoft-management`, 0 published to host)
    - Command: `--http-enabled -H unix:///var/run/docker.sock`
    - Healthcheck: Native `wget` spider hitting `http://127.0.0.1:9000/api/system/status` every 30s
  - `vextersoft-management-cloudflared-1`:
    - Image: `cloudflare/cloudflared:2026.10.2`
    - Status: `Up (healthy)`
    - Command: `tunnel --no-autoupdate --metrics 127.0.0.1:2000 run --token-file /run/secrets/cloudflare_tunnel_token`
    - User: `65532:65532` (non-root)
    - Healthcheck: `cloudflared tunnel --metrics 127.0.0.1:2000 ready`
- **Docker Networks:**
  - `vextersoft-management` (bridge): Attaches `portainer` and `cloudflared`
  - `vextersoft-tunnel-egress` (bridge): Attaches `cloudflared` for outbound routing

---

## 6. Public Ingress & Cloudflare Integration
- **Management Endpoint:** `https://devops.vextersoft.com`
- **Tunnel Connection:** Outbound encrypted tunnel connector to Cloudflare Edge
- **Service Route:** `http://portainer:9000` (internal Docker DNS resolution over `vextersoft-management`)
- **Host Listening Ports (`ss -tulpn` verified):**
  - `0.0.0.0:22`, `[::]:22` (sshd)
  - `127.0.0.53:53`, `127.0.0.54:53` (systemd-resolved)
  - Zero other TCP/UDP ports listening on host interfaces.
- **External Network Audit (Direct Origin Scan on `5.189.128.157`):**
  - Port 22 (SSH): Accessible
  - Port 9000 (Portainer HTTP): Closed / Unreachable
  - Port 9443 (Portainer HTTPS): Closed / Unreachable
  - Port 8000 (Portainer Edge): Closed / Unreachable
  - Port 2375 (Docker API): Closed / Unreachable
