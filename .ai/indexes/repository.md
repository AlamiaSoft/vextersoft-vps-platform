# Repository Index & Concept Map

## Directory Layout
- **`.agents/`**: AI agent lifecycle skills and configuration (`AGENTS.md`, `skills.json`).
- **`.ai/`**: Canonical AI knowledge base (architecture, current state, standards).
- **`.alamia/`**: Discovered project profile managed by `Alamia-Skills-System`.
- **`Alamia-Skills-System/`**: Portable lifecycle and atomic development skills suite.
- **`docs/`**: Production infrastructure documentation, audits, inventories, and recovery runbooks.
  - `docs/infrastructure-inventory.md`: Reconciled VPS hardware (`6 vCPU / 12 GB RAM / 200 GB SSD`), OS, disk, and network inventory.
  - `docs/devops-handover-runbook.md`: Canonical DevOps and trainee runbook covering diagnostics, `scripts/portainer_backup.py` backup/sandbox-restore procedures, and route onboarding.
  - `docs/trainee-backup-handover-checklist.md`: Trainee handover checklist separating CI-tested mechanics, safe sandbox restore steps, pending live operational proof, and approval gates.
  - `docs/cloudflare-portainer-runbook.md`: Cloudflare Tunnel and Portainer CE deployment, Vault handling, and rollback runbook.
  - `docs/operator-runbook-wsl-ansible.md`: Windows PowerShell + WSL2 Ansible operator workflow.
  - `docs/reports/vps-post-deployment-security-audit-2026-10-22.md`: Post-deployment security audit report (`PARTIALLY VERIFIED`).
  - `docs/security-audit-and-hardening-plan.md`: Security analysis and step-by-step remediation plan.
- **`scripts/`**: Automation, backup/restore, GitHub CLI, and diagnostic utility scripts.
  - `scripts/portainer_backup.py`: Single reusable helper for Portainer volume backup, archive verification, and isolated sandbox restore.
  - `scripts/diagnostics/audit_vps_live.py`: Non-destructive read-only live audit script with fail-closed target resolution.
  - `scripts/resolve_ansible_target.py`: Deterministic Ansible inventory target resolver.
  - `scripts/ci_validate.py`: Repository syntax, secret-hygiene, and public-IP validator.
  - `scripts/github/gh_client.py`: Authenticated GitHub Issues/PR/Actions CLI helper using `git credential fill`.
- **`tests/`**: Unit and regression test suite (`python -m unittest discover -s tests -v`).
- **`project-description.md`**: Master client brief and requirements.
