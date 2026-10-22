# DevOps Engineer Operational Handover Playbook

**Platform:** VexterSoft Cloud VPS Platform  
**Target Environment:** Contabo Ubuntu 24.04 LTS VPS (`vmi3682629` / `5.189.128.157`)  
**Host Profile:** 6 vCPU / 12 GB RAM / 200 GB SSD  
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
              ├─> Cloudflare Access (Identity & SSO Gate)
              │
              ▼ Cloudflare Argo Tunnel (Encrypted Outbound Egress)
[ VPS Host (5.189.128.157) ]
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
1. **Zero Exposed Management Sockets:** Portainer ports `9000`, `9443`, `8000` and the Docker daemon `2375` must **never** be published to `0.0.0.0` or `[::]`.
2. **Egress-Only Tunneling:** All ingress traffic arrives via Cloudflare Tunnel. No inbound firewall rules are opened for web traffic.
3. **Restricted SSH Access:** Password authentication is permanently disabled. Access requires an Ed25519 key for `vexteradmin` with strict host-key verification.
4. **Zero Secrets in Git:** All secrets and credentials are git-ignored. The local Vault file was deleted post-deployment; server-side tokens reside in `/opt/vextersoft/management/secrets/tunnel-token` (`mode 0440`).

---

## 2. Operator Workstation Prerequisites

The canonical control node is **Ubuntu on WSL2** (or any compliant Linux workstation):
- **Python**: 3.12+ with virtualenv located at `~/.venvs/vps-ansible`
- **Ansible Core**: 2.16+ with `community.docker` collection
- **SSH Client**: OpenSSH client with SSH Agent loaded with the authorized Ed25519 key
- **PowerShell (optional)**: For running helper scripts (`scripts/vextersoft.ps1`)

### Session Initialization in WSL
```bash
cd /mnt/e/Alamia/vextersoft-vps-platform
source ~/.venvs/vps-ansible/bin/activate

# Verify SSH key is in agent
ssh-add -l

# Verify connectivity to VPS
ansible -i ansible/inventory/hosts.yml vextersoft_vps -m ping
```

---

## 3. Routine Diagnostic & Health Commands

All commands in this section are **strictly read-only** and can be run at any time without approval.

### A. One-Command Full Live Audit (Persistent Operational Tool)
The repository includes a dedicated, non-destructive audit tool that inspects external port exposure and queries live host resources, Docker containers, and logs:

```bash
# Run from Windows PowerShell or WSL
python scripts/diagnostics/audit_vps_live.py
```
This tool verifies:
- External accessibility of ports 22, 9000, 9443, 8000, 2375, and 2376.
- Host identity, CPU, raw memory (`/proc/meminfo`), and swap status.
- UFW rules, Fail2ban status, and active socket listeners.
- Docker containers, volumes, networks, and recent container logs.

### B. Quick Preflight Health Check (via PowerShell)
```powershell
powershell -ExecutionPolicy Bypass -File scripts/vextersoft.ps1 doctor
powershell -ExecutionPolicy Bypass -File scripts/vextersoft.ps1 validate -Phase ingress
```

### C. Direct Container & Service Status (via SSH)
```bash
# Check management containers health and status
ssh vexteradmin@5.189.128.157 "sudo docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

# Check container resource utilization
ssh vexteradmin@5.189.128.157 "sudo docker stats --no-stream"

# Inspect Docker volumes and networks
ssh vexteradmin@5.189.128.157 "sudo docker network ls && sudo docker volume ls"
```

### D. Reading Container Logs Safely
```bash
# View Cloudflare Tunnel connector logs (last 50 lines)
ssh vexteradmin@5.189.128.157 "sudo docker logs --tail 50 vextersoft-management-cloudflared-1"

# View Portainer server logs (last 50 lines)
ssh vexteradmin@5.189.128.157 "sudo docker logs --tail 50 vextersoft-management-portainer-1"
```

---

## 4. Maintenance & Lifecycle Operations

### A. Restarting the Management Stack
If Portainer or Cloudflare Tunnel needs to be restarted:
```bash
# Restart without modifying volumes or configuration
ssh vexteradmin@5.189.128.157 "sudo docker compose -p vextersoft-management -f /opt/vextersoft/management/compose.yml restart"
```

### B. Backing up Portainer Persistent Data
Portainer stores its database (`portainer.db`), TLS keys, and settings inside the named Docker volume `vextersoft_portainer_data`.

To create a consistent, verified tarball backup:
```bash
# Run backup helper container to export the volume to a compressed archive
ssh vexteradmin@5.189.128.157 "sudo docker run --rm \
  -v vextersoft_portainer_data:/source:ro \
  -v /var/backups:/backup \
  alpine:latest tar -czf /backup/portainer-data-\$(date +%Y%m%d-%H%M%S).tar.gz -C /source ."

# Verify backup archive exists and is non-empty
ssh vexteradmin@5.189.128.157 "ls -lh /var/backups/portainer-data-*.tar.gz"
```

### C. Restoring Portainer Data from Backup
1. Stop the Portainer container:
   ```bash
   ssh vexteradmin@5.189.128.157 "sudo docker stop vextersoft-management-portainer-1"
   ```
2. Restore archive into volume:
   ```bash
   ssh vexteradmin@5.189.128.157 "sudo docker run --rm \
     -v vextersoft_portainer_data:/target \
     -v /var/backups:/backup \
     alpine:latest sh -c 'rm -rf /target/* && tar -xzf /backup/<BACKUP_FILE_NAME>.tar.gz -C /target'"
   ```
3. Restart Portainer container:
   ```bash
   ssh vexteradmin@5.189.128.157 "sudo docker start vextersoft-management-portainer-1"
   ```

---

## 5. Local Vault Handling vs. Running System Credentials

### Distinct Operational Realities
1. **The Live Running Host:**
   - Retains the active secret at `/opt/vextersoft/management/secrets/tunnel-token` (`mode 0440`, owned by `root:65532`).
   - Does **not** require Ansible or Vault to keep running, restart containers, or serve traffic.
2. **The Local Workstation:**
   - The local Vault file `ansible/vault/vextersoft_vps.vault.yml` was deleted after the one-time deployment by the owner so no Vault password needs to be remembered.
   - It is **not** required for running diagnostics, inspecting logs, or checking container health.

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
4. **Deploy Ingress:** Run Ansible to attach `cloudflared` to `app_frontend`.
5. **Cloudflare Zero Trust:** Add a public hostname route in Cloudflare Dashboard pointing `app.example.com` to `http://web:8080`.

---

## 7. Actions Requiring Explicit Owner Approval

According to `AGENT_PROTOCOL.md`:
- Modifying firewall (UFW) rules or SSH daemon configuration (`HOST-CHANGE`).
- Modifying system swap, kernel parameters, or system packages (`HOST-CHANGE`).
- Reinstalling the operating system (`PROHIBITED` unless approved by owner).
- Deleting named Docker volumes (`PRODUCTION-DESTRUCTIVE`).
- Modifying Cloudflare Access policies or rotating tunnel tokens (`PRODUCTION-DESTRUCTIVE`).
