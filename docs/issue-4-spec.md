# Issue #4 Specification: Baseline Hardening

## 1. Objective
Deploy an idempotent Ansible playbook for baseline host preparation and security hardening on Contabo Cloud VPS 6 (`<TARGET_HOST_IP>`), establishing a non-root administrative sudoer, enforcing SSH key-only access, configuring a 4 GiB swapfile, and enabling UFW with fail2ban.

## 2. Context & Background
Read-only inspection documented in `docs/infrastructure-inventory.md` confirmed:
- Direct root password login on port 22 is exposed without fail2ban.
- Host has 11 GiB RAM and 0 B swap.
- UFW is inactive and iptables default policy is ACCEPT.

## 3. Dependency DAG
- **Depends on:** #1 (Agent Protocol), #2 (Bootstrap Plan Review & DAG)
- **Blocks:** #5 (Container Runtime Setup)
- **Concurrency:** Single host-changing task. No other host-changing tasks may run concurrently.

## 4. Risk Classification & Approval Gate
- **Risk Class:** `HOST-CHANGE`
- **Requires Owner Approval Before Mutation:** YES (Mandatory)
- **Required Approval Items:**
  1. Creation of user `vexteradmin` with sudo permissions.
  2. Administrative SSH public key supplied by the owner to authorize.
  3. Activation of UFW and disabling of root password authentication.

## 5. Scope
### In-Scope
- Write idempotent Ansible playbook `ansible/playbooks/01-baseline-hardening.yml` and inventory.
- Configure administrative user with SSH public key.
- Execute dual-session verification gate before touching sshd configuration.
- Configure 4 GiB swapfile (`/swapfile`) with `vm.swappiness=10`.
- Enable UFW (default deny incoming, allow outgoing, allow 22/tcp on IPv4 and IPv6).
- Install and configure `fail2ban` for SSH protection.

### Out-of-Scope
- No Docker or container installation.
- No Cloudflare Tunnel or DNS changes.
- No OS reinstallation.

## 6. Acceptance Criteria
- [ ] Ansible inventory and baseline playbook committed to git (secrets and public IP excluded).
- [ ] Dual-session key-based sudo access proven in an independent SSH session before password login is disabled.
- [ ] `/etc/ssh/sshd_config.d/99-hardening.conf` syntax verified with `sshd -t` and reloaded cleanly.
- [ ] 4 GiB swap verified active via `free -h` and `swapon --show`.
- [ ] UFW active with IPv4 and IPv6 parity; port 22 allowed; default incoming denied.
- [ ] `fail2ban` running and actively monitoring SSH jail.
- [ ] Completion comment posted with sanitized terminal evidence.

## 7. Verification Plan & Test Commands
```bash
# Verify non-root SSH key login and sudo (run with TARGET_HOST_IP from .env/inventory)
ssh -i <private_key> vexteradmin@<TARGET_HOST_IP> "sudo id && free -h && ufw status verbose && fail2ban-client status sshd"
```

## 8. Rollback & Emergency Recovery
If SSH or network configuration fails:
1. Retain the initial primary SSH connection throughout the execution.
2. If primary connection drops, utilize the Contabo Web VNC/Rescue Console via the Contabo Customer Control Panel to log in as root with the initial root password.
3. Safe Rollback command: `sudo ufw disable && sudo rm -f /etc/ssh/sshd_config.d/99-hardening.conf && sudo systemctl reload ssh`.
