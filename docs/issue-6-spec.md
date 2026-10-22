# Issue #6 Specification: Edge Ingress & Management (Cloudflare Tunnel & Portainer)

## 1. Objective
Deploy Portainer CE and the Cloudflare Tunnel daemon (`cloudflared`) via Docker Compose and an Ansible playbook, establishing `devops.vextersoft.com` ingress with zero public port exposure on the VPS host.

## 2. Context & Background
Per `project-description.md`, Portainer must be accessible at `devops.vextersoft.com`, protected by Cloudflare Access and Portainer native authentication. Client-facing applications (Odoo, ZelixVet) must route independently through Cloudflare Tunnels without requiring Cloudflare Access walls for end users. Management and database sockets must remain completely unexposed on public host interfaces.

## 3. Dependency DAG
- **Depends on:** #5 (Container Runtime Setup)
- **Blocks:** #7 (Platform Validation & Runbook)
- **Concurrency:** Single host-changing task.

## 4. Risk Classification & Approval Gate
- **Risk Class:** `HOST-CHANGE`
- **Requires Owner Approval Before Mutation:** YES (Mandatory)
- **Required Approval Items:**
  1. Cloudflare Tunnel token in `.env`.
  2. Owner authorization to run Portainer and Cloudflare Tunnel containers.

## 5. Scope
### In-Scope
- Write Ansible playbook `ansible/playbooks/03-cloudflared-portainer.yml`.
- Create isolated Docker bridge networks:
  - `net-mgmt` (Portainer + cloudflared)
  - `net-odoo-internal` (isolated database & internal apps)
  - `net-zelixvet-prod` / `net-zelixvet-staging`
- Deploy Portainer CE container (attached to `net-mgmt`, bound strictly to internal network or `127.0.0.1:9000`).
- Deploy `cloudflared` container using Cloudflare Tunnel token to route `devops.vextersoft.com` -> Portainer (`http://portainer:9000`).

### Out-of-Scope
- No direct exposure of port 9000/9443 or Docker daemon socket to `0.0.0.0` or `[::]`.
- No application database migrations.

## 6. Acceptance Criteria
- [ ] Portainer container running and healthy on internal network.
- [ ] `cloudflared` container connected and reporting healthy tunnel status.
- [ ] `ss -tulpn` confirms port 9000 is NOT listening on `0.0.0.0` or `[::]`.
- [ ] `devops.vextersoft.com` returns Portainer login behind Cloudflare Access.
- [ ] Completion comment posted with sanitized terminal outputs.

## 7. Verification Plan & Test Commands
```bash
docker ps --filter "name=portainer|cloudflared"
ss -tulpn | grep 9000 || echo "Port 9000 is safely unexposed to public interfaces"
curl -I https://devops.vextersoft.com
```

## 8. Rollback & Emergency Recovery
- **Standard Rollback:**
  ```bash
  cd /opt/vextersoft/management && docker compose stop
  # Alternatively, stop and remove containers WITHOUT removing volumes:
  cd /opt/vextersoft/management && docker compose down
  ```
- **Data Safeguard Invariant:**
  DO NOT pass `-v` to `docker compose down` during routine rollback. Passing `-v` destroys persistent volume state (Portainer config, admin credentials, database volumes). Volume deletion is strictly `PRODUCTION-DESTRUCTIVE` and requires separate explicit approval and backup verification.
