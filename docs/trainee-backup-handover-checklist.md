# Trainee Handover & Backup Operational Proof Checklist

**Epic:** [#27 — Make VPS backup/restore workflow safe, tested, and trainee-ready](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/27)  
**Central Tracker:** [#14 — VexterSoft VPS Platform Execution Checklist](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/14)  
**Canonical Helper:** [`scripts/portainer_backup.py`](../scripts/portainer_backup.py)  
**Canonical Runbook:** [`docs/devops-handover-runbook.md`](devops-handover-runbook.md)  

---

## 1. Automated CI Mechanics (Verified in Ephemeral Runner Only)

- [x] **Shared Helper Implemented (`#28`):** `scripts/portainer_backup.py` provides `backup`, `verify-archive`, and `restore-sandbox` subcommands with `try...finally` container-restart protection on failure, gzip/tar/`portainer.db` integrity checks, and hard rejection of production or non-empty target volumes.
- [x] **Unit Test Suite (`#28`, `#30`, `#31`):** `tests/test_portainer_backup.py`, `tests/test_ci_backup_workflow.py`, `tests/test_backup_runbook.py`, and `tests/test_audit_reconciliation.py` cover invalid inputs, `source == target` rejection, corrupt/missing archives, `try...finally` restart-on-failure guarantees, and fail-closed target resolution.
- [x] **GitHub Actions Docker Smoke Job (`#29`):** `.github/workflows/pr-safety.yml` (`backup-restore-smoke`) initializes a disposable volume with a real `portainer/portainer-ce:2.45.1-alpine` container (zero published host ports), executes quiesced backup, verifies the archive, restores into a fresh sandbox volume, boots a second Portainer container, verifies `InstanceID` database persistence, exercises failure paths, and cleans up all disposable resources in `if: always()`.

> **Important Scope Boundary:**  
> A green CI run proves that `scripts/portainer_backup.py` and the backup/restore mechanics work against disposable Docker volumes in an ephemeral GitHub-hosted Linux runner. **It does NOT prove that a live VPS backup has been copied off-host or that a supervised restore has been performed on the production VPS.**

---

## 2. Local / Operator Preflight & Safe Sandbox Restore Workflow (Trainee-Safe)

Before performing any diagnostic or backup check, trainees must complete these preflight steps without relying on undefined shell variables or `.env` files:

- [ ] **Step 2.1 — Workstation & SSH Readiness (`READ-ONLY`):**
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts/vextersoft.ps1 doctor
  powershell -ExecutionPolicy Bypass -File scripts/vextersoft.ps1 validate -Phase ingress
  ```
- [ ] **Step 2.2 — Canonical Target Resolution (`READ-ONLY`):**
  Confirm `ansible/inventory/hosts.yml` resolves `vextersoft_vps` to the real VPS IP (never `<TARGET_HOST_IP>` or `192.0.2.1`):
  ```bash
  ansible-inventory -i ansible/inventory/hosts.yml --list \
    | python3 scripts/resolve_ansible_target.py vextersoft_vps
  ```
- [ ] **Step 2.3 — Live Read-Only Audit (`READ-ONLY`):**
  ```bash
  python3 scripts/diagnostics/audit_vps_live.py --inventory ansible/inventory/hosts.yml --alias vextersoft_vps
  ```
- [ ] **Step 2.4 — Local Archive Verification (`READ-ONLY`):**
  Whenever an archive is downloaded to the workstation, verify its gzip stream, tar structure, `portainer.db` marker, and SHA-256 digest:
  ```bash
  python3 scripts/portainer_backup.py verify-archive --archive-path ./backups/<ARCHIVE_NAME>.tar.gz
  ```

---

## 3. Pending Live Operational Proof (To Be Completed & Evidenced with Owner)

The overall post-deployment audit (`docs/reports/vps-post-deployment-security-audit-2026-10-22.md`) remains labeled **`PARTIALLY VERIFIED`** until the following live operational tasks are executed and their sanitized terminal evidence is recorded on GitHub:

- [ ] **Pending Proof 3.1 — Designate Off-Host Backup Destination:**
  Owner designates the approved off-host storage location (encrypted operator workstation directory or off-host backup storage) and retention policy.
- [ ] **Pending Proof 3.2 — First Live VPS Portainer Backup & Off-Host Copy (`SEC-10`):**
  1. Obtain owner approval if using `--quiesce-container vextersoft-management-portainer-1` (briefly stops Portainer UI; `HOST-CHANGE`).
  2. Run `python3 scripts/portainer_backup.py backup --source-volume vextersoft_portainer_data --archive-path "$BACKUP_FILE" --quiesce-container vextersoft-management-portainer-1 --sudo`.
  3. Confirm Portainer returned to `Up (healthy)`.
  4. Copy `"$BACKUP_FILE"` off-host via `scp` and verify matching SHA-256 with `python3 scripts/portainer_backup.py verify-archive`.
- [ ] **Pending Proof 3.3 — Supervised Live Sandbox Restore (`SEC-10`):**
  1. Run `python3 scripts/portainer_backup.py restore-sandbox --archive-path "$BACKUP_FILE" --target-volume "portainer_sandbox_restore_$(date -u +%Y%m%d_%H%M%S)" --source-volume vextersoft_portainer_data --sudo`.
  2. Record the JSON verification output showing `portainer.db` restored in the sandbox volume.
  3. Remove the disposable sandbox volume (`sudo docker volume rm <SANDBOX_VOL>`).
- [ ] **Pending Proof 3.4 — External IPv6 Vantage Port Scan (`SEC-04`):**
  From an external host with native IPv6 routing, run:
  ```bash
  python3 scripts/diagnostics/audit_vps_live.py --target-ip <TARGET_HOST_IPV6>
  ```
  and verify that ports 80, 443, 8000, 9000, 9443, 2375, and 2376 return `CLOSED / UNREACHABLE [PASS]` rather than `INCONCLUSIVE`.

---

## 4. Hard Stop & Escalation Gates (Separate Owner Approval Required)

Trainees and AI agents must **STOP** and obtain explicit written owner approval on the relevant GitHub Issue before performing any of the following:

| Action | Risk Classification | Mandatory Gate |
| :--- | :---: | :--- |
| Stopping/restarting live `portainer` or `cloudflared` containers (including `--quiesce-container`) | `HOST-CHANGE` | Explicit owner approval on GitHub before execution. |
| Modifying UFW rules, SSH daemon config, swap, or host packages | `HOST-CHANGE` | Explicit owner approval + dual-session SSH safety gate. |
| Restoring into or replacing `vextersoft_portainer_data` in production | `PRODUCTION-DESTRUCTIVE` | Explicit owner approval naming target host, volume, verified backup SHA-256, outage window, and rollback copy. Never use `rm -rf /target/*`. |
| Deleting any persistent Docker volume (`docker volume rm vextersoft_portainer_data` or `compose down -v`) | `PRODUCTION-DESTRUCTIVE` | Prohibited in routine operations; requires explicit destructive approval and verified off-host backup. |
| Rotating Cloudflare Tunnel tokens or modifying Cloudflare Access policies | `PRODUCTION-DESTRUCTIVE` | Explicit owner approval + coordinated Vault update. |
