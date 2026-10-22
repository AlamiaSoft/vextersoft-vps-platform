# Infrastructure Inventory & Host Baseline

**Host Identifier:** `vmi3682629`
**Provider:** Contabo Cloud VPS
**Contracted Profile:** 6 vCPU / 12 GB RAM / 200 GB SSD
**Public IPv4:** `<TARGET_HOST_IPV4>` (Resolved via ignored `ansible/inventory/hosts.yml`)
**Public IPv6:** `<TARGET_HOST_IPV6>`
**Last Audit Date:** 2026-10-22
**Audit Type:** Post-Deployment Verification & Security Audit
**Status:** Operational — Partially Verified (Phase A through D Complete; External IPv6 & Live Off-Host Backup Proof Pending)

---

## 1. Compute & Virtualization
- **Hypervisor:** KVM (QEMU virtual machine, `Standard PC _i440FX + PIIX, 1996_`)
- **vCPU Cores:** 6 vCPUs (AMD EPYC, Little Endian x86_64, `nproc = 6`)
- **Memory (RAM):**
  - **Provider Assigned:** 12 GB RAM
  - **Measured Total (`free -b`):** 12,541,493,248 bytes (~12.54 GB decimal / 11.68 GiB binary)
  - **Linux Kernel Total (`/proc/meminfo`):** `MemTotal: 12247552 kB`
  - **Measured Available (`/proc/meminfo`):** `MemAvailable: 11574188 kB` (~11 GiB available, ~660 MiB used)
  *(Note on historical discrepancy: An earlier report erroneously recorded 15 GiB RAM due to a local WSL execution anomaly during interactive command quoting. Direct raw query via `/proc/meminfo` confirms exactly 12,247,552 kB matching the contracted 12 GB Contabo plan).*
- **Swap:** 4.0 GiB swapfile (`/swapfile`, file, priority -2)

---

## 2. Operating System & Kernel
- **Distribution:** Ubuntu 24.04.5 LTS (Noble Numbat)
- **Kernel Version:** Linux 6.8.0-139-generic x86_64
- **Init System:** Systemd 255
- **Time Synchronization:** systemd-timesyncd active

---

## 3. Storage & Partitions
- **Primary Block Device:** `/dev/sda` (QEMU HARDDISK)
- **Partition Layout:**
  - `/dev/sda1` (ext4): 193 GiB total, 7.3 GiB used (4%), 186 GiB available mounted at `/` (label: `cloudimg-rootfs`)
  - `/dev/sda15` (vfat): 105 MiB mounted at `/boot/efi` (UEFI)
  - `/dev/sda16` (ext4): 881 MiB mounted at `/boot`
  - `/swapfile`: 4.0 GiB file-backed swap
- **Docker Persistent Storage:**
  - Named Volume: `vextersoft_portainer_data` (Driver: local) mounted at `/data` in Portainer

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
- **Docker Engine:** `29.9.2` (API: `1.56`)
- **Docker Compose:** v2 plugin installed
- **Daemon Configuration:** Restricted socket `/var/run/docker.sock` (mode `0660`, group `docker`), no TCP listeners (`0.0.0.0:2375`/`2376` absent).
- **Management Project Location:** `/opt/vextersoft/management`
  - Permissions: directory `0750`, `secrets/` directory `0750` (group `65532`)
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
  - `vextersoft-management` (bridge, `internal: true`): Attaches `portainer` and `cloudflared`
  - `vextersoft-tunnel-egress` (bridge, `internal: false`): Attaches `cloudflared` for outbound routing

---

## 6. Public Ingress & Cloudflare Integration
- **Management Endpoint:** `https://devops.vextersoft.com`
- **Tunnel Connection:** Outbound encrypted tunnel connector to Cloudflare Edge
- **Service Route:** `http://portainer:9000` (internal Docker DNS resolution over `vextersoft-management`)
- **Host Listening Ports (`ss -tulpn` verified):**
  - `0.0.0.0:22`, `[::]:22` (sshd)
  - `127.0.0.53:53`, `127.0.0.54:53` (systemd-resolved)
  - Zero other TCP/UDP ports listening on host interfaces.
- **External Network Audit (Direct Origin Scan on `<TARGET_HOST_IPV4>`):**
  - Port 22 (SSH): Accessible (`PASS`)
  - Port 80 / 443 (HTTP/HTTPS): Closed / Unreachable (`PASS`)
  - Port 9000 (Portainer HTTP): Closed / Unreachable (`PASS`)
  - Port 9443 (Portainer HTTPS): Closed / Unreachable (`PASS`)
  - Port 8000 (Portainer Edge): Closed / Unreachable (`PASS`)
  - Port 2375 / 2376 (Docker API): Closed / Unreachable (`PASS`)
- **External IPv6 Audit (`<TARGET_HOST_IPV6>`):**
  - Host-level UFW & listening sockets: `PASS` (`deny (incoming)`, `deny (routed)`, only `[::]:22` listening)
  - External IPv6 vantage scan: `PENDING / INCONCLUSIVE` (Audit workstation lacked IPv6 ISP route; requires external IPv6-capable probe)
