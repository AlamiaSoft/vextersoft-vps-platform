# Initial discovery plan

> Historical discovery notes only. This file records the original plan; current scope and operational status are maintained in `project-description.md`, `docs/00-current-state.md`, and the active runbooks.

## 1. Local tooling and control environment

- **Host OS:** Windows with PowerShell.
- **Native tools:** OpenSSH, Git, and WSL2 with Ubuntu 24.04 for Ansible execution.
- **Secret hygiene:** Local environment files, private keys, inventory details, and credentials must remain untracked. Use repository-relative links in tracked documentation.

## 2. Initial read-only VPS inspection

The original read-only audit findings and detailed inventory are documented in:
- Raw VPS inspection notes (preserved in untracked local diagnostic logs)
- [Infrastructure inventory](docs/infrastructure-inventory.md)
- [System architecture](.ai/permanent/architecture/01-system-architecture.md)
- [Security audit and hardening plan](docs/security-audit-and-hardening-plan.md)

The initial host was a newly provisioned Ubuntu 24.04 VPS. At the time of inspection, the audit flagged missing swap, an inactive firewall, and permissive SSH settings as hardening priorities. These are historical findings and should not be treated as the current live state; use the latest verified status and current runbooks for deployment decisions.

## 3. Phased implementation plan

1. **Baseline hardening:** create a non-root administrator, verify key-based SSH, harden SSH, configure swap and Fail2ban, and apply a restrictive firewall.
2. **Docker runtime:** install the official Docker Engine and Compose plugin, configure bounded logging, and verify the runtime.
3. **Cloudflare Tunnel and Portainer:** deploy the connector, route the management hostname through Cloudflare Access, require Portainer authentication, and verify that management/database ports are not publicly exposed.

All host-changing phases require a reviewed plan, explicit approval, and post-change verification.

## 4. Configuration and approvals

- Keep host-specific IPs, gateways, SSH details, and inventory variables in ignored local configuration.
- Use placeholders in tracked documentation when examples need an address.
- Store tunnel tokens in an encrypted local Ansible Vault file; do not place credentials in Git or chat.
- Cloudflare DNS and Access configuration, as well as deployment to a live VPS, require separate review and approval.
