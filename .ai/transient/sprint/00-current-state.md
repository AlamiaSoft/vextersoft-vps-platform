# Sprint Current State

**Last Updated:** 2026-10-22  
**Current Phase:** Phase D Complete — Cloudflare Tunnel + Private Portainer CE Ingress Operational & Verified

## Completed and verified phases

- **Phase A (Bootstrap):** Initial Contabo VPS bootstrap completed; non-root user `vexteradmin` provisioned with passwordless sudo and Ed25519 public key authentication. Strict host-key checking active.
- **Phase B (Baseline Hardening):** Host hardened with restrictive UFW policy (`default deny incoming`, `default allow outgoing`, `default deny routed`, port 22/tcp allow only), Fail2ban active (`sshd` jail running), 4.0 GiB swap partition enabled, SSH password/keyboard-interactive authentication disabled (`sshd -T` verified).
- **Phase C (Docker Engine):** Docker Engine `29.9.2` and Docker Compose v2 plugin installed and running under systemd with socket permissions restricted to `root:docker`.
- **Phase D (Ingress & Management):**
  - Project directory `/opt/vextersoft/management` and secrets directory `/opt/vextersoft/management/secrets` created (mode `0750` / `0700`).
  - Cloudflare Tunnel connector deployed using root-managed file-based secret (`mode 0440`, group `65532`).
  - Portainer CE deployed using pinned LTS Alpine image `portainer/portainer-ce:2.45.1-alpine`.
  - Zero exposed management ports: Port 9000, 9443, and 8000 are unexposed to the host and bound strictly to private Docker bridge `vextersoft-management`.
  - Container healthchecks active and healthy (`cloudflared tunnel --metrics ready` and Portainer HTTP `/api/system/status` spider check via busybox `wget`).
  - Cloudflare Tunnel routing established: `devops.vextersoft.com` -> `http://portainer:9000`.
  - External port audit verified: Origin IP `5.189.128.157` has ports 9000, 9443, 8000, 2375, and 2376 closed/unreachable externally; only port 22 is open.
  - Portainer CE initial admin setup completed by the owner; environment connected to local Docker socket (`vextersoft-vps`).

## Scope boundary

This repository automates generic VPS setup and app infrastructure. Odoo Cloud control-plane features, customer billing, multi-customer lifecycle logic, and Odoo staging/production orchestration are excluded and belong in the separate VexterSoft Odoo Cloud initiative.
