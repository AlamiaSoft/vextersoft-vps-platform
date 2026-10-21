# Security Audit & Proposed Hardening Plan

## 1. Security Findings & Deficiencies (Current State)

| Item | Finding | Risk / Impact |
| :--- | :--- | :--- |
| **Root Password Login** | `PermitRootLogin yes` with password authentication allowed | Vulnerable to internet brute-force attacks against the root password on port 22. |
| **No Active Firewall** | UFW is `inactive`, iptables policy is `ACCEPT` on all chains | Once services or Docker containers start, any bound host ports would immediately be publicly exposed to the internet. |
| **No Brute-force Protection** | `fail2ban` or equivalent rate-limiting is not installed | Unlimited failed SSH attempts possible across internet scanners. |
| **Zero Swap Space** | `0B` swap configured on an 11 GiB RAM host | Risk of sudden Linux OOM (Out-of-Memory) killer terminating PostgreSQL or Odoo under burst memory conditions. |
| **Privileged Workloads** | Operations currently running as `root` | Violates principle of least privilege. |

---

## 2. Proposed Phase 1 Hardening (Requires Approval)

### Step 1: Safe SSH Key Setup & Non-Root Administrator
1. Generate / configure a dedicated administrative user (e.g. `vexteradmin` or `devops`) with passwordless `sudo` rights.
2. Install the administrator's authorized SSH public key.
3. Verify SSH key login on a separate, secondary SSH session **before** touching `root` access or disabling password authentication.
4. Disable root password authentication (`PermitRootLogin prohibit-password` or disabled entirely once admin key is verified).
5. Disable password authentication (`PasswordAuthentication no`) once verified.

### Step 2: Swap Allocation
- Allocate a safe 4 GiB swapfile (`/swapfile`) with `swappiness=10` to handle memory spikes gracefully without disk thrashing.

### Step 3: Firewall Configuration (UFW)
- Set default incoming policy to `DENY`, default outgoing to `ALLOW`.
- Allow SSH (`22/tcp`, or designated custom port).
- Restrict all Docker / database / management ports from direct public internet exposure.
- Enable UFW only after confirming current SSH session survivability.

### Step 4: Intrusion Prevention
- Install and configure `fail2ban` monitoring SSH with automatic IP banning upon repeated failed authentications.

---

## 3. Proposed Phase 2 Architecture (Docker, Portainer, Cloudflare)

```
[ Internet ]
      │
      ▼
[ Cloudflare Edge ]
      │ (Cloudflare Tunnel - outbound connection only, zero inbound ports needed)
      ▼
[ cloudflared daemon on VPS ]
      │
      ├──> Portainer (devops.vextersoft.com - protected by Cloudflare Access + Portainer auth)
      ├──> Odoo 20 (VexterSoft internal - direct client access via Cloudflare tunnel hostname)
      ├──> ZelixVet Tomken Vet (Prod & Staging - separate database + filestore containers)
      └──> Marketing Demo Environment
```

- **Zero Inbound Management Exposure:** Portainer and internal database services will NOT bind to `0.0.0.0` or open public ports on the host. They will communicate internally via Docker bridge networks and be exposed exclusively through the outbound encrypted Cloudflare Tunnel.
- **Client Odoo Access:** Routed through Cloudflare edge hostnames without requiring Cloudflare Access Zero Trust logins for public clients.
