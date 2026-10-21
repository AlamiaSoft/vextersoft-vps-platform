# WSL Ansible Operator Runbook

This runbook covers the operator workflow used to bootstrap a VPS from Windows PowerShell and then run Ansible from WSL2. It deliberately keeps SSH host-key checking enabled.

## Short operator workflow

The repository entry point is `scripts/vextersoft.ps1`. It runs Ansible in the selected WSL distribution, uses the repository's `ansible/ansible.cfg`, checks the inventory host alias, and never disables SSH host-key verification.

From PowerShell at the repository root:

```powershell
.\scripts\vextersoft.ps1 doctor
.\scripts\vextersoft.ps1 prepare
.\scripts\vextersoft.ps1 validate -Phase baseline
```

Implemented actions:

- `doctor`: read-only checks for repository/inventory, WSL distro, Ansible/collections, SSH agent and the trusted host key.
- `prepare`: installs the repository Ansible collections locally, safely copies the configured Windows SSH key only if the WSL copy is absent or identical, transfers only the already trusted host-key entry, and loads the key into a persistent WSL SSH agent socket. It does not change the VPS.
- `validate`: checks playbook syntax and runs Ansible ping against the selected alias using strict host-key checking.
- `baseline`, `docker`, `ingress`: each requires the explicit `-ApproveHostChange` switch and a typed confirmation phrase after displaying the target. The ingress action also prompts for the Ansible Vault password. Each action validates and pings before applying the corresponding playbook.

Examples:

```powershell
.\scripts\vextersoft.ps1 validate -Phase ingress
.\scripts\vextersoft.ps1 baseline -ApproveHostChange
.\scripts\vextersoft.ps1 docker -ApproveHostChange
.\scripts\vextersoft.ps1 ingress -ApproveHostChange
```

The displayed confirmation is an additional operator gate, not a substitute for the repository protocol's owner approval requirement. Do not use host-changing actions until the exact host, playbook effects, recovery path, and owner approval have been reviewed.

A Git worktree does not copy ignored local inventory or host configuration. Before using this entry point in a new worktree, create or securely copy `ansible/inventory/hosts.yml` and the per-host files under `ansible/inventory/host_vars/<inventory-alias>/`. Those files are ignored; keep them out of commits.

The workflow does not silently install Ansible itself. If `doctor` reports that Ansible is missing, use the WSL installation procedure below, then run `prepare`. If the configured Windows key or trusted host-key entry is missing, stop and establish it through the trusted bootstrap/console path; never accept a key automatically.

## Scope and current state

- The Windows bootstrap script establishes and verifies the `vexteradmin` account, its public key, and passwordless sudo, then writes the local Ansible inventory.
- Windows OpenSSH and WSL OpenSSH maintain separate home directories, private-key locations, and `known_hosts` files. A successful Windows bootstrap does not automatically make the host trusted in WSL.
- Passing the Ansible syntax check and receiving `pong` from the Ansible ping module verifies tooling, SSH trust/authentication, and connectivity. It does **not** mean a playbook has been applied.
- Do not commit private keys, raw bootstrap logs, passwords, or credentials to this repository.

## 1. Run the Windows bootstrap

From PowerShell at the repository root:

```powershell
.\scripts\bootstrap.ps1 -HostIp "<VPS_IPV4>"
```

Complete the requested root-password and local SSH-key passphrase prompts. Confirm the bootstrap summary reports no failed steps and that key-based admin login and passwordless sudo are verified. Keep the generated inventory on the local machine if it contains environment-specific connection details.

## 2. Prepare Ansible in WSL2

Open the WSL2 Ubuntu terminal. Use your actual repository path if it differs from the example below:

```bash
cd /mnt/e/Alamia/vextersoft-vps-platform
python3 --version
```

If Ansible is not already installed in a dedicated virtual environment:

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv
python3 -m venv ~/.venvs/vps-ansible
source ~/.venvs/vps-ansible/bin/activate
python -m pip install --upgrade pip
python -m pip install ansible
```

Install the repository's required collections:

```bash
ansible-galaxy collection install -r ansible/requirements.yml
```

## 3. Make the Windows SSH identity and trusted host key available in WSL

The operator command handles this transfer after confirming the source key and matching host key exist. It copies no key contents to the terminal. The transfer remains strict: an unknown host key is never accepted, and a conflicting WSL key entry stops preparation.

The key is loaded into a persistent WSL agent socket at `/tmp/vextersoft-ssh/agent.sock`. The passphrase prompt appears in the WSL terminal. Never paste a passphrase into chat or save it in a shell script.

To perform the steps manually, run them in the WSL account that runs Ansible:

```bash
VPS_IP="<VPS_IPV4>"
WINPROFILE=$(wslpath "$(cmd.exe /c echo %USERPROFILE% | tr -d '\r')")
WINSSH="$WINPROFILE/.ssh"
test -f "$WINSSH/vextersoft_vps"
test -f "$WINSSH/known_hosts"
ssh-keygen -F "$VPS_IP" -f "$WINSSH/known_hosts"
install -d -m 700 ~/.ssh
cp "$WINSSH/vextersoft_vps" ~/.ssh/vextersoft_vps
chmod 600 ~/.ssh/vextersoft_vps
```

Stop if the private key or matching host-key entry is missing. Never replace this step with blindly accepting a key from `ssh-keyscan`.

## 4. Validate before applying a phase

The repository Ansible configuration keeps `host_key_checking = True`. Run:

```bash
export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"
ansible-playbook --syntax-check -i ansible/inventory/hosts.yml ansible/playbooks/01-baseline-hardening.yml
ansible -i ansible/inventory/hosts.yml vps_servers -m ping
```

Syntax validation and `pong` confirm the local playbook parser, inventory, SSH trust/authentication, and connectivity. They do not confirm that server configuration changed.

## 5. Run host-changing phases

The PowerShell operator prints the target, requires `-ApproveHostChange`, then asks for a typed confirmation phrase before execution. It stops after any failed validation or verification. Manual commands must follow the same approval and verification gate.

The baseline playbook configures the secure Ubuntu baseline. The Docker phase installs Docker Engine and Compose. The ingress phase installs Cloudflare Tunnel and Portainer. The ingress playbook defaults its extra approval flag to false, does not change UFW, and publishes no host ports.

Use `docs/cloudflare-portainer-runbook.md` for Cloudflare token setup, DNS/Access configuration, ingress deployment, verification, rollback, and recovery. Cloudflare account changes and VPS deployment require separate approval; neither is run by `doctor`, `prepare`, or `validate`.

## 6. Continue the deployment in dependency order

1. Baseline hardening, followed by a new SSH connection and checks for SSH directives, UFW, swap, and fail2ban.
2. Docker Engine and Compose, followed by Docker/containerd health and disposable container verification.
3. Cloudflare Tunnel and Portainer, after the Cloudflare hostname, Access policy, token, and egress prerequisites are ready.
4. Applications through Portainer stacks. Keep public web frontends separate from their databases; only explicitly approved app frontends should join tunnel ingress networks.
5. Read-only acceptance and recovery checks for host ports, tunnel status, Access behavior, persistent data, and backups.

Complete one host-changing phase at a time and verify it before moving to the next.
