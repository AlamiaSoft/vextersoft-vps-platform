# Trainee Runbook: Provision a Fresh VexterSoft Test VPS

**Audience:** DevOps trainee engineer  
**Risk class:** LOCAL-REPO for this document; host-changing steps below require separate owner approval  
**Target:** One newly assigned, disposable test VPS from the approved test-resource pool  
**Supported OS:** Ubuntu 24.04 LTS (the repository playbooks validate against this release)  
**Status:** Procedure for a human operator; this document does not authorize or perform any VPS or Cloudflare changes.

> [!CAUTION]
> Use only the exact fresh test VPS assigned by the owner. Do **not** use the existing VexterSoft VPS, a customer server, or production. Do not reinstall an OS, change DNS, deploy ingress, or run a host-changing phase without explicit approval naming the target and phase. If any target detail is ambiguous, stop.

This runbook intentionally uses the repository's existing bootstrap and Ansible playbooks. Do not improvise a parallel manual installation procedure or skip verification steps.

## 1. What success looks like

When the owner asks for a full test setup, the expected order is:

1. Confirm the VPS is fresh, disposable, assigned to you, and recoverable from the provider console.
2. Establish trusted SSH access and bootstrap the `vexteradmin` administrator.
3. Prepare WSL2/Ansible and validate target identity/connectivity.
4. Apply and verify **Phase B: baseline hardening**.
5. Apply and verify **Phase C: Docker Engine and Compose**.
6. If specifically requested and prerequisites are ready, apply **Phase D: Cloudflare Tunnel + Portainer**.
7. Run read-only acceptance checks, capture sanitized evidence, and hand over the report.

A phase is not complete merely because its command exited successfully. Record the actual verification evidence. If ingress is not approved or Cloudflare prerequisites are unavailable, leave Phase D deferred and report that clearly.

## 2. Before touching the server

### 2.1 Get the assignment in writing

Ask the owner to provide/confirm all of the following:

- [ ] Provider and VPS resource/pool identifier.
- [ ] Exact public IPv4 address and, if relevant, IPv6 address.
- [ ] Confirmation that this is a **fresh disposable test resource** and contains no data to preserve.
- [ ] Ubuntu 24.04 LTS image and SSH port (default 22).
- [ ] Initial access method and a secure way to receive the initial root password.
- [ ] Confirmation that the provider console/rescue console works.
- [ ] Owner approval in the relevant GitHub issue for each host-changing phase.
- [ ] For ingress only: assigned management hostname, correct Cloudflare account/tunnel, approved Access policy, outbound TCP or UDP 7844 availability, and approval to deploy.

Do not put the root password, private key, SSH passphrase, tunnel token, or Vault password in GitHub, chat, issue comments, command-line arguments, or the handoff report.

### 2.2 Verify the target is really the assigned test VPS

In the provider console, check the resource ID, image, addresses, and that it is the resource assigned to you. Confirm the owner has authorized changes to this exact resource. If there is any possibility that the IP belongs to another machine, stop and ask.

Take a provider snapshot if the platform supports it and the owner approves. Confirm console/rescue access before proceeding. Do not assume a snapshot exists because a provider offers snapshots.

### 2.3 Know the stop conditions

Stop immediately and notify the owner if:

- The IP, provider resource ID, OS release, SSH port, or inventory alias does not match the assignment.
- The SSH host-key fingerprint cannot be verified through a trusted provider console or other approved out-of-band source.
- A command fails, a verification result is unexpected, or a playbook reports a failed task.
- A firewall or SSH change may have interrupted access.
- Docker/host networking differs from the playbook's expected preflight conditions.
- An existing file, package, listener, or container suggests the VPS is not fresh.
- A command proposes deleting data, replacing an existing configuration, changing DNS, or exposing a management port unexpectedly.

Do not repeatedly rerun a failed playbook blindly. Capture the failed task and sanitized output, preserve the current session, and escalate.

## 3. Prepare the Windows workstation and repository

Use a supported Windows workstation with PowerShell, Git, and WSL2. The WSL distribution used by the current operator wrapper defaults to `Ubuntu-24.04`.

Open **PowerShell** and choose a working directory approved for development. Clone the repository if needed:

```powershell
git clone https://github.com/AlamiaSoft/vextersoft-vps-platform.git
Set-Location .\vextersoft-vps-platform
git status --short --branch
```

If you already have a checkout, update it without overwriting local work:

```powershell
git status --short --branch
git pull --ff-only
```

If Git reports local changes or the pull cannot fast-forward, stop and ask for help. Do not discard local edits.

Confirm the expected files exist:

```powershell
Test-Path .\scripts\bootstrap.ps1
Test-Path .\scripts\vextersoft.ps1
Test-Path .\ansible\playbooks\01-baseline-hardening.yml
Test-Path .\ansible\playbooks\02-docker-engine.yml
Test-Path .\ansible\playbooks\03-cloudflared-portainer.yml
```

All should return `True`.

## 4. Prepare the SSH key and verify the server host key

### 4.1 Create the dedicated SSH key if you do not already have it

The repository's bootstrap expects the Windows SSH key at `%USERPROFILE%\.ssh\vextersoft_vps` and its public key at `%USERPROFILE%\.ssh\vextersoft_vps.pub`. If the pair already exists and belongs to you, do not overwrite it.

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\vextersoft_vps" -C "vextersoft-devops-trainee"
```

Use a strong passphrase. Keep the private key private; share only the public key through the approved provisioning process. Never paste either key into chat or commit it.

### 4.2 Establish trusted host-key verification

Obtain the SSH host-key fingerprint from the provider console or another owner-approved, out-of-band source. A key collected over the same untrusted network is not independent proof of identity.

If you use `ssh-keyscan` to collect the candidate public host key, treat it as **untrusted input** until its fingerprint matches the trusted fingerprint exactly. Do not blindly append the result to `known_hosts`, disable host-key checking, or accept a changed key without investigation.

The bootstrap process must verify the host identity. If it cannot establish a trusted match, stop. Record the verified fingerprint in the internal handoff, not private key material.

## 5. Bootstrap the administrator account

From PowerShell at the repository root, run the bootstrap against the assigned test VPS only:

```powershell
.\scripts\bootstrap.ps1 -HostIp "<ASSIGNED_TEST_VPS_IPV4>"
```

Replace the placeholder with the assigned address locally. The script securely prompts for the initial root password and the local SSH key passphrase. Do not place credentials in the command itself.

The bootstrap provisions `vexteradmin`, installs the public key, checks sudo, attempts an independent key-based login, inspects the effective SSH configuration, and writes the ignored local Ansible inventory.

Wait for the final summary. Confirm all required bootstrap-access checks passed and there are no failed steps. A bootstrap success does **not** mean SSH hardening, UFW, swap, fail2ban, Docker, or ingress have been applied.

**If bootstrap fails:** do not continue to Ansible host-changing steps. Save the sanitized summary and relevant local log path (under the ignored `logs/bootstrap/` directory), verify access through the provider console, and notify the owner. Do not attach raw logs until you have checked that they contain no sensitive information.

## 6. Prepare WSL2 and Ansible

Run these commands in **PowerShell** from the repository root:

```powershell
.\scripts\vextersoft.ps1 doctor
```

This is read-only. If it reports missing WSL, inventory, key, trusted host key, or Ansible prerequisites, resolve the reported issue before continuing.

Prepare the WSL-side tooling and trusted SSH identity:

```powershell
.\scripts\vextersoft.ps1 prepare
```

The command installs the repository's required Ansible collections and safely makes the existing Windows SSH identity and already trusted host-key entry available to WSL. It must not disable host-key checking or automatically trust an unknown key.

If Ansible itself is missing, open the configured WSL Ubuntu terminal and run:

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv
python3 -m venv ~/.venvs/vps-ansible
source ~/.venvs/vps-ansible/bin/activate
python -m pip install --upgrade pip
python -m pip install ansible
cd /path/to/vextersoft-vps-platform
ansible-galaxy collection install -r ansible/requirements.yml
```

Replace `/path/to/vextersoft-vps-platform` with the actual WSL path. Return to PowerShell and run `doctor` and `prepare` again.

Do not copy private keys into the repository. Host inventory and per-host settings are local ignored files; verify that they are not staged or tracked.

## 7. Validate the exact target before any host change

In PowerShell:

```powershell
.\scripts\vextersoft.ps1 validate -Phase baseline
```

Confirm that the printed target IP, SSH user, SSH port, and inventory alias match the assignment. The default alias is `vextersoft_vps`. Do not proceed if any value is surprising.

The validation should pass the playbook syntax check and Ansible ping (`pong`) while strict SSH host-key checking remains enabled. This proves connectivity and basic execution only; it does not prove that any configuration was applied.

If validation fails, stop and diagnose the failure. Do not change `ansible.cfg` to disable host-key checking.

## 8. Phase B — Baseline hardening

**Risk class: HOST-CHANGE. Explicit owner approval is required before execution.**

### Preflight

- [ ] Owner approval names the exact test VPS and baseline-hardening operation in the GitHub issue.
- [ ] Provider console/rescue access has been tested.
- [ ] Current SSH session stays open throughout the change.
- [ ] A second independent terminal can authenticate to the VPS using the intended administrator key and `sudo`.
- [ ] Inventory target and SSH port are correct; current playbook expects Ubuntu 24.04 and SSH port 22.
- [ ] `doctor` and `validate -Phase baseline` pass.
- [ ] You have read `ansible/playbooks/01-baseline-hardening.yml` and understand the changes: admin policy, SSH hardening, UFW, 4 GiB swap, fail2ban, unattended upgrades, and system tuning.

### Execute

Only after the approval is present, run in PowerShell:

```powershell
.\scripts\vextersoft.ps1 baseline -ApproveHostChange
```

Read the displayed target and playbook summary, then enter the requested typed confirmation. If the target does not match the assigned test VPS exactly, cancel.

### Verify before continuing

- [ ] The command completed without failed tasks and ran its post-change checks.
- [ ] Open a **new** independent SSH session using the admin key; verify `sudo -n true` succeeds. Do not rely only on the old session.
- [ ] Verify effective SSH settings and confirm password authentication is disabled and public-key authentication is enabled.
- [ ] Verify UFW is active with incoming default deny, outgoing default allow, and the intended SSH port allowed.
- [ ] Verify swap is active (expected 4 GiB unless the playbook/owner-approved configuration says otherwise).
- [ ] Verify fail2ban is installed and active.
- [ ] Confirm there is no unexpected loss of connectivity.

Useful read-only checks from WSL, using the configured inventory:

```bash
ansible -i ansible/inventory/hosts.yml vextersoft_vps -m ping
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a "sshd -T"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a "ufw status verbose"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a "swapon --show"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a "systemctl is-active fail2ban"
```

Review the effective SSH output for the expected settings; do not dump unrelated system information into a public issue.

If the SSH session fails or the firewall result is unexpected, **stop**. Use the provider console/rescue path with the owner. Do not proceed to Docker until the baseline is verified.

## 9. Phase C — Docker Engine and Compose

**Risk class: HOST-CHANGE. Requires separate explicit owner approval.**

### Preflight

- [ ] Phase B is verified and recorded.
- [ ] Owner approval names this VPS and the Docker installation phase.
- [ ] New SSH session, sudo, Ansible ping, and baseline checks still pass.
- [ ] Read `ansible/playbooks/02-docker-engine.yml`. It uses pinned official Docker packages and storage/logging safeguards; it intentionally refuses to remove conflicting packages or overwrite unsafe Docker daemon settings.

Validate:

```powershell
.\scripts\vextersoft.ps1 validate -Phase docker
```

Execute only after approval:

```powershell
.\scripts\vextersoft.ps1 docker -ApproveHostChange
```

Read the target confirmation and proceed only if it is correct.

### Verify

From WSL:

```bash
ansible -i ansible/inventory/hosts.yml vextersoft_vps -m ping
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a "systemctl is-active docker"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a "docker version"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a "docker compose version"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a "docker ps --format '{{.Names}}|{{.Ports}}'"
```

Confirm Docker is active, the client/server versions are shown, Compose is available, and no unexpected containers or public host-port bindings exist. If the playbook fails on a conflicting package/configuration, do not remove it manually; report the finding and ask the owner.

## 10. Phase D — Cloudflare Tunnel + Portainer (only if assigned)

**Risk class: HOST-CHANGE plus Cloudflare account configuration. Requires separate explicit owner approval.**

Skip this phase unless the owner specifically asks for ingress setup on this test VPS. Do not create DNS records, Cloudflare Access applications, or tunnels merely because the playbook exists.

Read the complete [Cloudflare Tunnel and Portainer Runbook](cloudflare-portainer-runbook.md) first.

### Prerequisites

- [ ] Phase B and C are fully verified.
- [ ] Owner approval names the exact VPS and ingress operation.
- [ ] A dedicated remotely managed Cloudflare Tunnel has been created in the correct account.
- [ ] The assigned management hostname is approved.
- [ ] Cloudflare Access protects that exact hostname with default-deny and an allow policy for intended identities; MFA is configured as required. No bypass or wildcard management route.
- [ ] Provider egress permits TCP or UDP 7844 to Cloudflare. No inbound web or management ports are opened as a workaround.
- [ ] You can use Ansible Vault locally, and the tunnel token is available from the approved secret source.
- [ ] The tunnel token is not present in Git, shell history, chat, logs, or command-line arguments.

### Configure per-host settings

In WSL from the repository root, find the exact inventory alias. The example below assumes the default alias `vextersoft_vps`:

```bash
mkdir -p ansible/inventory/host_vars/vextersoft_vps
cp ansible/inventory/host_vars/EXAMPLE_HOST/cloudflare.yml.example \
  ansible/inventory/host_vars/vextersoft_vps/cloudflare.yml
```

Edit the ignored local `cloudflare.yml` and set the approved management hostname. Leave `cloudflare_public_routes: []` unless public application routes were explicitly requested.

Create the encrypted token file:

```bash
ansible-vault create ansible/inventory/host_vars/vextersoft_vps/vault.yml
```

Inside the editor, add only the following YAML key with the token obtained from the approved secret source:

```yaml
cloudflare_tunnel_token: "INSERT_REAL_TOKEN_IN_LOCAL_VAULT_EDITOR"
```

The example string above is a placeholder, not a working token. Save and close the editor. Never paste the token into chat or a terminal command. Confirm both per-host files are ignored by Git.

### Validate and deploy

In PowerShell:

```powershell
.\scripts\vextersoft.ps1 validate -Phase ingress
```

Resolve all validation failures before requesting execution. Then, only after the owner approval is present:

```powershell
.\scripts\vextersoft.ps1 ingress -ApproveHostChange
```

Enter the Vault password only at the secure prompt. Review the exact target and typed confirmation. The wrapper's interactive confirmation is an additional safety check, not a substitute for owner approval.

### Verify ingress

Follow the Cloudflare runbook's full checks. At minimum verify:

- [ ] Both cloudflared and Portainer are healthy.
- [ ] The tunnel reports connected in the Cloudflare dashboard.
- [ ] Portainer login is reachable only through the approved Access policy and its own login.
- [ ] An allowed identity can access the management hostname and an unapproved identity is denied.
- [ ] `docker ps`, `ss -lnt`, and firewall checks show no public Portainer, Docker API, database, or metrics port.
- [ ] No application hostname has been made public without explicit review.
- [ ] The tunnel token is not exposed in task output, diffs, or container command arguments.

Do not continue to public application deployments unless separately requested and reviewed.

## 11. Final read-only acceptance checks

After the phases approved for this VPS have completed, run the following read-only checks from WSL:

```bash
ansible -i ansible/inventory/hosts.yml vextersoft_vps -m ping
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a "uptime"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a "df -h /"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a "free -h"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a "ufw status verbose"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a "ss -lnt"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -b -m command -a "docker ps --format '{{.Names}}|{{.Status}}|{{.Ports}}'"
```

For phases not installed yet, do not mark their checks as passed. Record them as **not applicable/deferred** with a reason. Compare all listening ports and container bindings with the intended design. Never claim the VPS is secure solely because the playbook returned success.

## 12. Failure handling and rollback

1. Stop at the first failed task or unexpected result. Do not run the next phase.
2. Keep any surviving SSH session open. Do not reboot or close it while diagnosing an access/firewall failure.
3. Capture the failed task name, exit code, sanitized output, timestamp, and phase. Do not include credentials, private keys, Vault contents, tunnel tokens, or raw logs without sanitizing.
4. Use the provider console/rescue console if SSH access is lost. Contact the owner before editing SSH or firewall settings manually.
5. Do not remove Docker packages, delete containers/volumes, overwrite configuration, recreate a VPS, or restore a snapshot unless the owner approves the exact action and confirms data impact.
6. For ingress failure, use the Cloudflare runbook's troubleshooting/rollback instructions. Do not open inbound ports as a shortcut.
7. Retry only after the failure is understood and the owner agrees on the recovery path.

## 13. Trainee handoff report

Submit this report in the owner-approved handoff location. This repository and its GitHub issues may be public: do not post public IPs, provider console details, or other infrastructure identifiers in public issues. Use a private channel for sensitive operational details and sanitized evidence in the public tracker.

```text
VPS resource ID:
Provider / region:
Assigned test purpose:
OS release / architecture:
Target identifier (use a non-sensitive alias in public records):
Bootstrap: PASS / FAIL
Trusted host-key fingerprint verified out-of-band: YES / NO
Independent SSH + sudo check: PASS / FAIL
Phase B baseline: PASS / FAIL / NOT RUN
  Evidence: sanitized command result / timestamp
Phase C Docker + Compose: PASS / FAIL / NOT RUN
  Evidence: sanitized command result / timestamp
Phase D Tunnel + Portainer: PASS / FAIL / DEFERRED
  Management hostname (if approved):
  Access allow/deny test: PASS / FAIL / NOT RUN
  Public management ports absent: PASS / FAIL / NOT RUN
Open issues / deviations:
Snapshot or recovery method:
Final recommendation: READY FOR REVIEW / BLOCKED
Trainee and completion timestamp:
```

Do not include root passwords, SSH private keys, key passphrases, Cloudflare tunnel tokens, Vault passwords, or unredacted secret-bearing logs.

## 14. Completion criteria

The task is ready for owner review only when:

- [ ] The assigned VPS identity and fresh-test status were verified.
- [ ] Bootstrap access was verified with an independent key-based SSH session and sudo.
- [ ] Every approved phase has successful post-change verification.
- [ ] Unapproved phases are explicitly marked deferred, not complete.
- [ ] Public listeners, firewall rules, Docker ports, and management exposure match the intended design.
- [ ] Failure/deviation details and sanitized evidence are recorded.
- [ ] The owner has reviewed the handoff before the VPS is used for further testing.

## Related repository documents

- [WSL Ansible Operator Runbook](operator-runbook-wsl-ansible.md)
- [Cloudflare Tunnel and Portainer Runbook](cloudflare-portainer-runbook.md)
- [Security Audit and Hardening Plan](security-audit-and-hardening-plan.md)
- [Agent Execution Protocol](../AGENT_PROTOCOL.md)
- [Phase tracker issue #14](https://github.com/AlamiaSoft/vextersoft-vps-platform/issues/14)
