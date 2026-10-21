# Project: VexterSoft VPS Platform Bootstrap

Act as a senior Linux infrastructure engineer and DevOps automation engineer.

## Objective

Prepare a reusable, documented infrastructure baseline for VexterSoft, starting with an already-provisioned Contabo Cloud VPS 6.

The VPS will initially host:
- Internal VexterSoft Odoo 20.
- ZelixVet for Tomken Vet, with separate staging and production environments.
- A marketing demonstration environment for veterinary clinics and human hospitals.
- Potential Laravel multi-tenant SaaS applications for restaurant ordering and car rental.

Future clients may receive dedicated VPS instances. The infrastructure automation should eventually support other providers.

## Working approach

1. Inspect the local Windows/WSL environment and available tooling.
2. Create a Git-managed infrastructure repository.
3. Connect to the VPS over SSH and inspect its current operating system, architecture, disks, network interfaces, firewall, existing services and SSH configuration.
4. Document findings before changing the server.
5. Create idempotent Ansible playbooks for host preparation and security hardening.
6. Use Docker Engine, Docker Compose, Portainer and Cloudflare Tunnel.
7. Make Portainer accessible at `devops.vextersoft.com`, protected by Cloudflare Access and Portainer authentication.
8. Keep client-facing Odoo applications independently accessible to their intended users, without requiring Cloudflare Access for every client.
9. Ensure PostgreSQL, Docker management ports and other private services are not unintentionally exposed publicly.
10. Document every operational step, verification command, rollback procedure and recovery path.

## Safety requirements

- Do not expose root SSH credentials, private keys, API tokens or other secrets in Git, logs or generated documentation.
- Do not make destructive changes or apply firewall rules that could lock out the administrator without first validating the recovery path.
- Do not reinstall the operating system unless inspection establishes a concrete reason and I explicitly approve it.
- Do not run unreviewed commands that change production infrastructure.
- Prefer idempotent Ansible tasks over ad hoc shell scripts.
- Pin important software versions and document upgrade procedures.
- Separate infrastructure provisioning from application deployment.
- Keep staging and production databases, filestores, configuration and credentials isolated.
- Implement independent off-site backup and restore verification before production is considered ready.
- Request approval before consequential changes to SSH, firewall rules, Docker networking, persistent volumes or externally accessible services.

## Initial deliverables

1. `README.md` with the architecture and setup instructions.
2. `docs/` with an infrastructure inventory, network design, security checklist and recovery runbook.
3. Ansible inventory and configuration files with secrets excluded.
4. Separate playbooks for inspection, baseline hardening, Docker installation, Portainer installation and Cloudflare Tunnel configuration.
5. A validation checklist that can be run after deployment.
6. A clear list of manual prerequisites and tasks that still require my approval.

## First task only

Start with local tooling checks and read-only VPS inspection. Report the findings, proposed changes and any blockers. Do not perform the full bootstrap until I review the plan.