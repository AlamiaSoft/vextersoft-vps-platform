# DevOps Engineer Operational Handover Playbook

**Platform:** VexterSoft Cloud VPS Platform
**Target Environment:** Contabo Ubuntu 24.04 LTS VPS (`vmi3682629` / `<TARGET_HOST_IPV4>`)
**Host Profile:** 6 vCPU / 12 GB contracted RAM (~11.68 GiB OS-usable) / 200 GB SSD (~193 GiB ext4)
**Management Console:** `https://devops.vextersoft.com`
**Last Updated:** 2026-10-22

---

## 1. System Architecture & Ingress Flow

```
[ DevOps Engineer Browser ]
              │
              ▼ HTTPS (TCP 443)
[ Cloudflare Edge / Anycast ]
              │
              ├─> Cloudflare Access (Identity & SSO Gate - Portainer Devops)
              │
              ▼ Cloudflare Argo Tunnel (Encrypted Outbound Egress)
[ VPS Host (<TARGET_HOST_IPV4>) ]
  ├── UFW: Port 22 ALLOW only (9000, 9443, 8000, 2375 BLOCKED)
  │
  └── Docker Engine (v29.9.2)
        │
        ├── [vextersoft-management-cloudflared-1] (Non-root user 65532)
        │     │  (Internal Docker Network: vextersoft-management)
        │     ▼ HTTP :9000
        ├── [vextersoft-management-portainer-1] (v2.45.1-alpine)
        │     │
        │     ├── Mounted Volume: vextersoft_portainer_data -> /data
        │     └── Mounted Socket: /var/run/docker.sock
        │
        └── Future Application Networks (Dedicated, isolated per app)
```

### Core Security Invariants
1. **Zero Exposed Management Sockets:** Portainer ports `9000`, `9443`, `8000` and the Docker daemon `2375`/`2376` must **never** be published to `0.0.0.0`, `[::]`, or `127.0.0.1`.
2. **Egress-Only Tunneling:** All ingress traffic arrives via Cloudflare Tunnel. No inbound firewall rules are opened for web traffic.
3. **Restricted SSH Access:** Password authentication is permanently disabled. Access requires an Ed25519 key for `vexteradmin` with strict host-key verification (`StrictHostKeyChecking=yes`).
4. **Zero Secrets in Git:** All secrets and credentials are git-ignored. The local Vault file (`ansible/vault/vextersoft_vps.vault.yml`) was deleted post-deployment; server-side tokens reside in `/opt/vextersoft/management/secrets/tunnel-token` (`mode 0440`, owned by `root:65532`).

---

## 2. Operator Workstation Prerequisites

The canonical control node is **Ubuntu on WSL2** (or any compliant Linux workstation):
- **Python**: 3.12+ with virtualenv located at `~/.venvs/vps-ansible`
- **Ansible Core**: 2.16+ with `community.docker` collection
- **SSH Client**: OpenSSH client with SSH Agent loaded with the authorized Ed25519 key
- **PowerShell (optional)**: For running helper scripts (`scripts/vextersoft.ps1`)

### Session Initialization & Target Resolution in WSL
Never rely on undefined shell variables or unvalidated `.env` files. Resolve the canonical target from the ignored local Ansible inventory (`ansible/inventory/hosts.yml`):

```bash
# [LOCAL WORKSTATION — WSL2]
cd /mnt/e/Alamia/vextersoft-vps-platform
source ~/.venvs/vps-ansible/bin/activate

# Verify SSH key is loaded in agent
ssh-add -l

# Resolve and verify the single canonical target host from Ansible inventory
ansible-inventory -i ansible/inventory/hosts.yml --list \
  | python3 scripts/resolve_ansible_target.py vextersoft_vps

# Verify connectivity to VPS via strict SSH host-key checking
ansible -i ansible/inventory/hosts.yml vextersoft_vps -m ping
```

---

## 3. Routine Diagnostic & Health Commands

All commands in this section are **strictly read-only** (`READ-ONLY` risk class) and can be run without host-change approval.

### A. One-Command Full Live Audit (Persistent Operational Tool)
The repository includes a non-destructive audit tool (`scripts/diagnostics/audit_vps_live.py`) that resolves the target deterministically via `ansible/inventory/hosts.yml` (or explicit `--target-ip`) and fails closed on missing, placeholder (`<...>`), or documentation-range addresses:

```bash
# [LOCAL WORKSTATION] Run using canonical Ansible inventory resolution
python3 scripts/diagnostics/audit_vps_live.py --inventory ansible/inventory/hosts.yml --alias vextersoft_vps
```
This tool verifies:
- External TCP accessibility of ports 22, 80, 443, 9000, 9443, 8000, 2375, and 2376 from the local vantage point (reporting IPv6 external checks as `INCONCLUSIVE` if the local workstation lacks IPv6 routing).
- Host identity, CPU, raw memory (`/proc/meminfo`), and swap status.
- UFW rules, Fail2ban status, and active socket listeners.
- Docker containers, volumes, networks, and recent container logs.

### B. Quick Preflight Health Check (via PowerShell)
```powershell
# [LOCAL WORKSTATION — PowerShell]
powershell -ExecutionPolicy Bypass -File scripts/vextersoft.ps1 doctor
powershell -ExecutionPolicy Bypass -File scripts/vextersoft.ps1 validate -Phase ingress
```

### C. Direct Container & Service Status (via Ansible or SSH)
```bash
# [LOCAL WORKSTATION — WSL2] Check management containers health and status
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a \
  "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

# [LOCAL WORKSTATION — WSL2] Check container resource utilization
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a \
  "docker stats --no-stream"

# [LOCAL WORKSTATION — WSL2] Inspect Docker volumes and networks
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a \
  "docker network ls"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a \
  "docker volume ls"
```

### D. Reading Container Logs Safely
```bash
# [LOCAL WORKSTATION — WSL2] View Cloudflare Tunnel connector logs (last 50 lines)
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a \
  "docker logs --tail 50 vextersoft-management-cloudflared-1"

# [LOCAL WORKSTATION — WSL2] View Portainer server logs (last 50 lines)
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a \
  "docker logs --tail 50 vextersoft-management-portainer-1"
```

---

## 4. Maintenance, Backup & Recovery Lifecycle

### A. Restarting the Management Stack (`HOST-CHANGE`)
Restarting running services on the VPS is a `HOST-CHANGE` operation and requires owner approval before execution:
```bash
# [ON VPS AS vexteradmin] Restart without modifying volumes or configuration
sudo docker compose -p vextersoft-management -f /opt/vextersoft/management/compose.yml restart
```

### B. Portainer Persistent Data Backup Procedure (`scripts/portainer_backup.py`)

All Portainer volume backups and sandbox restores use the repository's single canonical helper: **`scripts/portainer_backup.py`**. Do not use ad-hoc `docker stop ... && docker run ... && docker start` shell one-liners, which can leave Portainer stopped if `tar` fails.

#### 1. Backup Scope & Limitations (Must Read)
- **What IS backed up:** Only the named Docker volume `vextersoft_portainer_data` (mounted at `/data` inside Portainer), which stores Portainer's embedded BoltDB database (`portainer.db`), internal TLS certificates, user accounts, and environment definitions.
- **What is NOT backed up by this archive:**
  1. **Management Compose file** (`/opt/vextersoft/management/compose.yml` — rendered from `ansible/templates/cloudflared-portainer.compose.yml.j2`).
  2. **Cloudflare Tunnel secret** (`/opt/vextersoft/management/secrets/tunnel-token` — recovered/rotated via Cloudflare Zero Trust and Ansible Vault).
  3. **Host OS & Firewall state** (UFW, SSHD, Fail2ban, sysctl — managed by `01-baseline-hardening.yml` and `02-docker-engine.yml`).
  4. **Downstream application data** (future PostgreSQL clusters, Odoo filestores, or application volumes must have their own dedicated backup jobs).

#### 2. Consistency Model: Why `:ro` Alone Does Not Guarantee Database Consistency
- Mounting `vextersoft_portainer_data` as `:ro` (`readonly`) inside the helper container only prevents the **backup container** from writing to the volume. It **does not** pause or flush Portainer's own in-flight BoltDB writes if the Portainer container is still running.
- **Quiesced Backup (Recommended / Application-Consistent):** Pass `--quiesce-container vextersoft-management-portainer-1` to `scripts/portainer_backup.py backup`. The helper stops Portainer before archiving and uses a `try...finally` block that **always attempts to restart Portainer (`docker start`) even if archive creation or verification fails**, removing any partial archive on error. *(Note: Stopping Portainer briefly interrupts the management UI (`HOST-CHANGE`), so schedule quiesced backups during approved maintenance windows).*
- **Live Read-Only Snapshot (Crash-Consistent Only):** Omit `--quiesce-container` for a zero-downtime snapshot when no administrative changes are being made in Portainer.

#### 3. Step-by-Step Backup Execution & Verification
Copy `scripts/portainer_backup.py` to `/usr/local/sbin/portainer_backup.py` (or `/tmp/portainer_backup.py`) on the VPS, or execute from a checkout on the host:

```bash
# [ON VPS AS vexteradmin]
# Step 1: Preflight — verify Portainer is currently running and healthy, and check free disk space
sudo docker inspect -f '{{.State.Running}} ({{.State.Health.Status}})' vextersoft-management-portainer-1
df -h /var/backups

# Step 2: Ensure restricted backup directory exists (root-only, mode 0700)
sudo install -d -m 0700 -o root -g root /var/backups/vextersoft-portainer

# Step 3: Execute quiesced backup + built-in archive verification via shared helper
BACKUP_FILE="/var/backups/vextersoft-portainer/portainer-backup-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
python3 scripts/portainer_backup.py backup \
  --source-volume vextersoft_portainer_data \
  --archive-path "$BACKUP_FILE" \
  --quiesce-container vextersoft-management-portainer-1 \
  --sudo

# Step 4: Postflight — confirm Portainer is running and healthy after backup
sudo docker inspect -f '{{.State.Running}} ({{.State.Health.Status}})' vextersoft-management-portainer-1
```

#### 4. Standalone Archive Integrity Verification
`scripts/portainer_backup.py backup` runs verification automatically, but you should also run `verify-archive` after copying an archive to another machine or before any restore test:

```bash
# Verifies: file exists, size > 0, full gzip stream validity, tar readability,
# no path-traversal members, and non-empty portainer.db presence. Outputs SHA-256 JSON.
sudo python3 scripts/portainer_backup.py verify-archive \
  --archive-path "$BACKUP_FILE"
```

#### 5. Off-Host Storage Transfer & Retention
A backup stored only on the VPS disk (`/var/backups/vextersoft-portainer`) does **not** protect against VPS disk corruption or provider instance failure.
1. Pull the verified archive to an approved off-host backup destination or operator workstation:
   ```bash
   # [LOCAL WORKSTATION — WSL2] Copy archive from VPS and restrict permissions
   mkdir -p ./backups && chmod 0700 ./backups
   # Replace <VPS_HOST> with the host resolved via scripts/resolve_ansible_target.py
   scp vexteradmin@<VPS_HOST>:/var/backups/vextersoft-portainer/portainer-backup-YYYYMMDDTHHMMSSZ.tar.gz ./backups/
   chmod 0600 ./backups/portainer-backup-*.tar.gz

   # Verify the off-host copy locally using the exact same helper
   python3 scripts/portainer_backup.py verify-archive \
     --archive-path ./backups/portainer-backup-YYYYMMDDTHHMMSSZ.tar.gz
   ```
2. Compare the local `sha256` output against the VPS `sha256` output to confirm bit-for-bit transfer integrity.
3. **Retention:** Retain 30 days of verified backups on `/var/backups/vextersoft-portainer` after confirming off-host copies exist.

#### 6. Failure Recovery During Backup
- If `tar` or archive verification fails during a quiesced backup, `scripts/portainer_backup.py` automatically deletes the partial/corrupt archive file and executes `sudo docker start vextersoft-management-portainer-1` in its `finally` block.
- If the helper prints `CRITICAL: Failed to restart Portainer container`, immediately run:
  ```bash
  sudo docker start vextersoft-management-portainer-1
  sudo docker compose -p vextersoft-management -f /opt/vextersoft/management/compose.yml ps
  ```
  and escalate to the platform owner before retrying.

---

### C. Portainer Restoration & Recovery Testing

#### 1. Routine Validation: Isolated Sandbox Volume Restore (`restore-sandbox`)
Trainees and operators must **never** test backups by overwriting `vextersoft_portainer_data`. Always restore into a disposable sandbox volume using `restore-sandbox`, which enforces:
- `target_volume` is never `vextersoft_portainer_data` or `portainer_data`.
- `target_volume != source_volume`.
- The archive passes `verify-archive` before any Docker volume is touched.
- The target volume is newly created or completely empty (never running `rm -rf`).

```bash
# [ON VPS OR TEST HOST]
SANDBOX_VOL="portainer_sandbox_restore_$(date -u +%Y%m%d_%H%M%S)"

# 1. Restore archive into isolated sandbox volume and verify portainer.db inside it
python3 scripts/portainer_backup.py restore-sandbox \
  --archive-path "$BACKUP_FILE" \
  --target-volume "$SANDBOX_VOL" \
  --source-volume vextersoft_portainer_data \
  --sudo

# 2. Clean up the disposable sandbox volume immediately after verification
sudo docker volume rm "$SANDBOX_VOL"
```

#### 2. Production Volume Recovery Gate (`PRODUCTION-DESTRUCTIVE`)
> **STOP / ESCALATION GATE FOR TRAINEES & AGENTS:**
> Restoring over or replacing the live Portainer volume (`vextersoft_portainer_data`) or deleting any persistent Docker volume is classified as **`PRODUCTION-DESTRUCTIVE`** under `AGENT_PROTOCOL.md`.
> - **Never** run an unguarded wipe command inside the live volume.
> - **Never** execute a production restore without **explicit written owner approval** recorded on the relevant GitHub Issue naming the target host, target volume, verified backup SHA-256, outage window, and rollback plan.

When an owner-approved production recovery is required:
1. Verify the candidate backup archive with `python3 scripts/portainer_backup.py verify-archive`.
2. Restore the archive into a new staging volume (`portainer_recovery_YYYYMMDD`) via `restore-sandbox` and verify its contents first.
3. Take a backup copy of the current `vextersoft_portainer_data` volume (even if degraded) so current state is preserved for forensic/rollback purposes.
4. Only after owner sign-off on the verified staging volume, coordinate the Compose volume cutover and post-restore health verification (`https://devops.vextersoft.com`).

#### 3. Current Validation Status vs. Pending Operational Proof
- **CI Workflow Mechanics (`TESTED IN CI`):** GitHub Actions (`.github/workflows/pr-safety.yml` -> `backup-restore-smoke`) automatically tests `scripts/portainer_backup.py` on every PR and push to `main` using disposable Docker volumes and real `portainer/portainer-ce:2.45.1-alpine` containers (verifying quiesced backup, `try...finally` container restart on failure, archive integrity, sandbox restore, and Portainer `InstanceID` database persistence).
- **Live VPS Operational Proof (`PENDING`):** Passing CI in an ephemeral GitHub-hosted runner **does not** prove that a real production backup has been copied off-host or restored on the VPS. The following operational handover steps remain pending until executed and evidenced by the operator/owner:
  1. Designate an approved off-host backup storage destination.
  2. Execute the first production `portainer_backup.py backup` run and copy the verified archive off-host.
  3. Execute a supervised `restore-sandbox` verification test and record sanitized terminal evidence.

---

## 5. Local Vault Handling vs. Running System Credentials

### Distinct Operational Realities
1. **The Live Running Host:**
   - Retains the active secret at `/opt/vextersoft/management/secrets/tunnel-token` (`mode 0440`, owned by `root:65532`).
   - Does **not** require Ansible or Vault to keep running, restart containers, or serve traffic.
2. **The Local Workstation:**
   - The local Vault file `ansible/vault/vextersoft_vps.vault.yml` was deleted after the one-time deployment by the owner so no Vault password needs to be remembered.
   - It is **not** required for running diagnostics, inspecting logs, checking container health, or running `scripts/portainer_backup.py`.

### How to Recreate the Vault File for Future Deployments
If you ever need to re-run `ansible-playbook ansible/playbooks/03-cloudflared-portainer.yml` (e.g. for redeployment, token rotation, or playbook reconfiguration):
1. Copy the tunnel token from Cloudflare Zero Trust Dashboard (Networks > Tunnels).
2. Create a fresh Vault file in WSL:
   ```bash
   cd /mnt/e/Alamia/vextersoft-vps-platform
   source ~/.venvs/vps-ansible/bin/activate
   mkdir -p ansible/vault
   ansible-vault create ansible/vault/vextersoft_vps.vault.yml
   ```
3. Enter a new password of your choice (store it in your password manager).
4. Add the token variable:
   ```yaml
   cloudflare_tunnel_token: "<TOKEN>"
   ```
5. Run the playbook with `--ask-vault-pass`.
6. You can delete `ansible/vault/vextersoft_vps.vault.yml` again after deployment if desired.

---

## 6. Adding Future Application Routes

When adding public web applications (e.g. `app.example.com`):

1. **Rule 1 (Network Isolation):** Each application must have its own dedicated Docker network. Never attach user applications to `vextersoft-management`.
2. **Rule 2 (No Public Host Ports):** Do not use `ports: - 80:80` or `443:443` on application containers.
3. **Rule 3 (Playbook Configuration):**
   Add the public route to `ansible/inventory/host_vars/vextersoft_vps/cloudflare.yml`:
   ```yaml
   cloudflare_public_routes:
     - hostname: app.example.com
       network: app_frontend
       service: web
       port: 8080
   ```
4. **Deploy Ingress:** Run Ansible to attach `cloudflared` to `app_frontend` after obtaining `HOST-CHANGE` owner approval.
5. **Cloudflare Zero Trust:** Add a public hostname route in Cloudflare Dashboard pointing `app.example.com` to `http://web:8080`.

---

## 7. Trainee Handover & Escalation Checklist

| Step / Category | Status | Risk Class | Notes / Action Required |
| :--- | :---: | :---: | :--- |
| **1. Backup/Restore Helper & CI Smoke Test** | **COMPLETE (CI)** | `LOCAL-REPO` | `scripts/portainer_backup.py` + `backup-restore-smoke` job in `.github/workflows/pr-safety.yml` validate mechanics in ephemeral runner only. |
| **2. Local Preflight & Target Validation** | **READY** | `READ-ONLY` | Use `scripts/vextersoft.ps1 doctor` / `validate` or `scripts/resolve_ansible_target.py` with `ansible/inventory/hosts.yml`. |
| **3. Live Off-Host Backup Destination** | **PENDING OWNER** | `READ-ONLY` / Ops | Owner to designate off-host storage location for `portainer-backup-*.tar.gz` archives. |
| **4. First Live Backup & Off-Host Copy** | **PENDING PROOF** | `HOST-CHANGE` (if quiesced) | Run `scripts/portainer_backup.py backup`, copy archive off-host, verify SHA-256 with `verify-archive`. |
| **5. Supervised Live Sandbox Restore Test** | **PENDING PROOF** | `HOST-CHANGE` | Run `scripts/portainer_backup.py restore-sandbox` into a disposable volume (`portainer_sandbox_restore_*`) and remove the test volume. |
| **6. External IPv6 Vantage Port Scan** | **PENDING / INCONCLUSIVE** | `READ-ONLY` | Run `audit_vps_live.py --target-ip <IPV6>` from an IPv6-capable external network to complement host-level UFW/socket proof. |
| **7. Production Volume Cutover / Deletion** | **GATED** | `PRODUCTION-DESTRUCTIVE` | Requires explicit written owner approval on GitHub naming host, volume, verified backup SHA-256, and rollback plan. |

---

## 8. Actions Requiring Explicit Owner Approval

According to `AGENT_PROTOCOL.md`:
- Modifying firewall (UFW) rules or SSH daemon configuration (`HOST-CHANGE`).
- Modifying system swap, kernel parameters, or system packages (`HOST-CHANGE`).
- Stopping or restarting live management containers (`HOST-CHANGE`).
- Reinstalling the operating system (`PROHIBITED` unless approved by owner).
- Replacing or deleting named Docker volumes or executing a production restore (`PRODUCTION-DESTRUCTIVE`).
- Modifying Cloudflare Access policies or rotating tunnel tokens (`PRODUCTION-DESTRUCTIVE`).
