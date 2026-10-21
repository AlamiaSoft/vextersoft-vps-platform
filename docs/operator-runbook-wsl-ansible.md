# WSL Ansible Operator Runbook

This runbook covers the operator workflow used to bootstrap a VPS from Windows PowerShell and then run Ansible from WSL2. It deliberately keeps SSH host-key checking enabled.

## Scope and current state

- The Windows bootstrap script establishes and verifies the `vexteradmin` account, its public key, and passwordless sudo, then writes the local Ansible inventory.
- Windows OpenSSH and WSL OpenSSH maintain separate home directories, private-key locations, and `known_hosts` files. A successful Windows bootstrap does not automatically make the host trusted in WSL.
- Passing the Ansible syntax check and receiving `pong` from the Ansible ping module verifies tooling, SSH trust/authentication, and connectivity. It does **not** mean the baseline hardening has been applied.
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

Run these commands in the same WSL user account that will run Ansible. They copy the private key into that user's Linux SSH directory and transfer only the matching, pre-existing host-key entry from Windows' `known_hosts`.

Set the VPS address without adding angle brackets:

```bash
VPS_IP="<VPS_IPV4>"
WINPROFILE=$(wslpath "$(cmd.exe /c echo %USERPROFILE% | tr -d '\r')")
WINSSH="$WINPROFILE/.ssh"

test -f "$WINSSH/vextersoft_vps"
test -f "$WINSSH/known_hosts"
ssh-keygen -F "$VPS_IP" -f "$WINSSH/known_hosts"
```

**Stop if the private key or matching host-key entry is missing.** Do not replace this step with blindly accepting a key from `ssh-keyscan`. Establish the host key through the trusted bootstrap/console path before proceeding.

If both checks pass:

```bash
install -d -m 700 ~/.ssh
cp "$WINSSH/vextersoft_vps" ~/.ssh/vextersoft_vps
chmod 600 ~/.ssh/vextersoft_vps

touch ~/.ssh/known_hosts
ssh-keygen -F "$VPS_IP" -f "$WINSSH/known_hosts" \
  | grep -v '^#' >> ~/.ssh/known_hosts
sort -u ~/.ssh/known_hosts -o ~/.ssh/known_hosts
chmod 600 ~/.ssh/known_hosts

eval "$(ssh-agent -s)"
ssh-add ~/.ssh/vextersoft_vps
```

Enter the SSH key's passphrase when prompted. The private key stays in the local SSH directory; never paste or commit its contents.

Verify strict host-key checking, admin-key access, and passwordless sudo:

```bash
ssh -o StrictHostKeyChecking=yes \
  -o IdentitiesOnly=yes \
  -i ~/.ssh/vextersoft_vps \
  "vexteradmin@$VPS_IP" 'sudo -n id -u'
```

Expected output is `0`. If host-key verification fails, stop and reconcile the trusted key; do not disable host-key checking.

## 4. Validate Ansible before changing the VPS

From the repository root in WSL:

```bash
export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"

ansible-playbook --syntax-check \
  -i ansible/inventory/hosts.yml \
  ansible/playbooks/01-baseline-hardening.yml

ansible -i ansible/inventory/hosts.yml vps_servers -m ping
```

Required results:

- The syntax check completes successfully.
- Ansible reports `SUCCESS` and `ping: pong`.
- The configured inventory resolves the intended VPS and the intended admin user.

The repository Ansible configuration intentionally keeps `host_key_checking = True`.

## 5. Apply baseline hardening only after validation

The baseline playbook changes host state: it configures a 4 GiB swapfile, installs baseline security utilities, configures UFW to deny unsolicited inbound traffic while allowing SSH on TCP/22, configures fail2ban, and hardens SSH authentication. Review the playbook and confirm the server uses SSH port 22 before running it.

Keep the current terminal open and run:

```bash
ansible-playbook --diff \
  -i ansible/inventory/hosts.yml \
  ansible/playbooks/01-baseline-hardening.yml
```

If the run fails, especially during UFW or SSH tasks, stop and inspect the failed task and recap before retrying. Do not blindly rerun or manually change SSH settings. The playbook currently allows TCP/22 only under its baseline UFW rules; any future public service ports must be planned deliberately, and app ingress is intended to use Cloudflare Tunnel rather than publicly exposing management or database ports.

## 6. Verify the hardened server

Only after the playbook finishes successfully, use a **new terminal/session** to prove admin key access still works. Do not close the original session until the new login succeeds.

Then check the effective SSH settings, firewall, swap, and fail2ban:

```bash
ssh -o StrictHostKeyChecking=yes \
  -o IdentitiesOnly=yes \
  -i ~/.ssh/vextersoft_vps \
  "vexteradmin@$VPS_IP" 'sudo -n id -u'

ansible -i ansible/inventory/hosts.yml vps_servers -m command -a "ufw status verbose"
ansible -i ansible/inventory/hosts.yml vps_servers -m command -a "swapon --show"
ansible -i ansible/inventory/hosts.yml vps_servers -m command -a "systemctl is-active fail2ban"
ansible -i ansible/inventory/hosts.yml vps_servers -m shell -a "sshd -T -C user=vexteradmin,host=127.0.0.1,addr=127.0.0.1 | grep -E '^(passwordauthentication|permitrootlogin|kbdinteractiveauthentication|pubkeyauthentication) '"
```

Confirm these effective SSH values are present:

- `passwordauthentication no`
- `permitrootlogin prohibit-password` (or the stricter `permitrootlogin no`)
- `kbdinteractiveauthentication no`
- `pubkeyauthentication yes`

Also confirm UFW is active, SSH remains allowed on TCP/22, swap is active, and fail2ban reports `active`. Record the actual outputs in the deployment notes; do not claim hardening is complete until these checks pass.

## 7. Continue the deployment in dependency order

1. **Baseline hardening:** finish the playbook and verify every check in Section 6.
2. **Docker Engine and Compose:** install using the repository's container-runtime task/specification; set Docker log rotation and required networks. Be careful: Docker-published ports can bypass assumptions about UFW rules, so do not publish database or management ports publicly.
3. **Cloudflare Tunnel and Portainer:** deploy the tunnel and Portainer only after Docker is verified. Protect `devops.vextersoft.com` with Cloudflare Access and Portainer's own authentication.
4. **Application environments:** deploy Odoo, ZelixVet staging/production, and demos only after the ingress and isolation model is tested. Public customer application hostnames must not inherit the Cloudflare Access wall intended for the management UI.
5. **Read-only acceptance and recovery checks:** verify host port exposure, tunnel routes, management protection, database isolation, persistent volumes, restart behavior, backups, and documented recovery steps.

Complete one host-changing phase at a time and validate it before moving to the next.
