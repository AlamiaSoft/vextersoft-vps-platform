# Project: VexterSoft VPS Platform

## Objective

Build a practical, reusable workflow to provision and operate VexterSoft VPS servers from Windows/WSL with Ansible. The automation should work across supported VPS providers when their Ubuntu, network, firewall, and console prerequisites have been verified.

The starting workflow prepares Ubuntu 24.04 with:

- SSH key access, SSH hardening, firewall defaults, fail2ban, and baseline system settings.
- Docker Engine and the Docker Compose plugin.
- Portainer with persistent storage for managing application stacks.
- Cloudflare Tunnel for private management ingress, with Cloudflare Access and Portainer authentication protecting the management hostname.
- Explicit public application hostnames that do not inherit the Portainer Access policy.
- Operator commands, validation, recovery procedures, and post-change verification.

A server-specific inventory alias, domain, and encrypted tunnel credential should be the only per-server setup normally required. Provider-specific firewall and networking differences must be documented and checked rather than assumed.

## Application workflow

Portainer stacks are the preferred workflow for deploying and managing applications. The platform should provide safe infrastructure primitives and public/private routing, while application stack definitions remain independent and reusable.

Odoo, ZelixVet, Laravel, or other application deployments may later use this infrastructure, but they do not define this repository's architecture or control plane.

## Explicit exclusions

Do not implement an Odoo-specific hosting control plane, multi-customer lifecycle logic, customer billing, Odoo staging/production orchestration, or customer-facing deployment panel here. Those belong to the separate future VexterSoft Odoo Cloud initiative.

## Safety requirements

- Do not expose SSH private keys, passwords, Cloudflare tokens, or other secrets in Git, terminal output, logs, or generated documentation.
- Keep SSH strict host-key verification enabled. Never accept unknown host keys automatically.
- Require explicit operator confirmation before host-changing phases and separate owner approval for sensitive server or Cloudflare changes.
- Do not expose the Docker API, databases, Portainer, or management ports on public host interfaces.
- Inspect UFW, Docker forwarding, IPv4/IPv6, provider firewall, and current services before making network changes.
- Do not reinstall an operating system without a concrete reason and explicit approval.
- Prefer idempotent Ansible playbooks over undocumented manual server configuration.
- Pin or deliberately manage image versions, retain Portainer data during routine rollback, and verify backups before restore or volume changes.

## Provisioning workflow

1. Inspect provider, Ubuntu release, networking, firewall, storage, SSH trust, and local WSL/Ansible tools.
2. Prepare the local inventory and SSH agent without weakening host-key checks.
3. Validate inventory and playbook syntax, then prove Ansible ping.
4. Apply baseline hardening with explicit confirmation and verify SSH, UFW, swap, and fail2ban.
5. Install Docker Engine and Compose with explicit confirmation, then verify services and container execution.
6. Configure Cloudflare Tunnel and Access prerequisites, then separately approve ingress deployment.
7. Deploy application stacks through Portainer with explicit public/private routing.
8. Verify access policies, host port exposure, persistence, restart behavior, rollback, and recovery.

Do not run several host-changing phases as one unattended operation.
