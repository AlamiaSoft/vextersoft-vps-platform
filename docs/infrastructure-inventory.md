# Infrastructure Inventory & Host Baseline

**Host Identifier:** `vmi3682629`
**Provider:** Contabo Cloud VPS 6 (Provisioned October 2026)
**Public IPv4:** `<TARGET_HOST_IPV4>` (Refer to private inventory / `.env`)
**Public IPv6:** `<TARGET_HOST_IPV6>`
**Inspection Date:** 2026-10-21
**Inspection Type:** Read-Only Non-Destructive Audit

---

## 1. Compute & Virtualization
- **Hypervisor:** KVM (QEMU virtual machine)
- **vCPU Cores:** 6 vCPUs (AMD EPYC, 2.0 GHz, Little Endian x86_64)
- **Cache Allocation:** L1d 192 KiB, L1i 384 KiB, L2 3 MiB, L3 8 MiB
- **Memory (RAM):** 11 GiB Total (535 MiB Used, 11 GiB Available)
- **Swap:** 0 B (No swap configured)

---

## 2. Operating System & Kernel
- **Distribution:** Ubuntu 24.04.5 LTS (Noble Numbat)
- **Kernel Version:** `Linux 6.8.0-139-generic x86_64`
- **Initial Boot Timestamp:** Tue Oct 20 17:13:39 2026 (Clean pristine installation)
- **Init System:** Systemd 255

---

## 3. Storage & Partitions
- **Primary Block Device:** `/dev/sda` (QEMU HARDDISK)
- **Partition Layout:**
  - `/dev/sda1` (ext4): `193 GB` total, `2.3 GB` used, `191 GB` available (`2%` use) mounted at `/` (label: `cloudimg-rootfs`)
  - `/dev/sda15` (vfat): `105 MB` total, `6.2 MB` used mounted at `/boot/efi` (UEFI)
  - `/dev/sda16` (ext4): `881 MB` total, `117 MB` used mounted at `/boot`
- **Optical Device:** `/dev/sr0` mounted as `cidata` (ISO 9660 cloud-init ephemeral media)

---

## 4. Networking & DNS
- **Default Gateway:** `<TARGET_DEFAULT_GATEWAY>` via `eth0`
- **Network Interfaces:**
  - `lo`: `127.0.0.1/8`, `::1/128`
  - `eth0`: `<TARGET_HOST_IPV4>`, `<TARGET_HOST_IPV6>`
- **DNS Resolver:** `systemd-resolved` active on `127.0.0.53:53` and `127.0.0.54:53`

---

## 5. Security & Access Audit
- **Firewall (UFW):** `INACTIVE`
- **Kernel Packet Filtering (iptables):** Default `ACCEPT` on `INPUT`, `FORWARD`, `OUTPUT` (unrestricted)
- **Open Listening Ports:**
  - `0.0.0.0:22` (SSH)
  - `[::]:22` (SSH)
  - `127.0.0.53:53`, `127.0.0.54:53` (Local DNS stub)
- **SSH Daemon Configuration:**
  - `PermitRootLogin yes` (Direct root login active)
  - `PasswordAuthentication yes` (Password authentication active)
  - `PubkeyAuthentication yes`
  - `MaxAuthTries 6`
  - `X11Forwarding yes`
- **Existing User Accounts:**
  - `root` (UID 0)
  - `ubuntu` (UID 1000)
- **Pre-installed Services:**
  - `cloud-init` active
  - `rsyslog`, `cron`, `systemd-resolved`, `systemd-networkd`, `systemd-timesyncd`
  - No web servers (Nginx/Apache), no databases (Postgres/MySQL), and no container runtimes (Docker/Containerd) installed.
