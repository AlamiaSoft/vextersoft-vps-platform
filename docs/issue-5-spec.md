# Issue #5 Specification: Container Runtime (Docker & Compose)

## 1. Objective
Install official Docker Engine and Docker Compose plugin on Ubuntu 24.04 LTS via an idempotent Ansible playbook, applying global logging safeguards (`json-file` log rotation) and systemd journal caps to protect the ~193 GB filesystem from disk exhaustion.

## 2. Context & Background
Read-only inspection confirmed zero container runtimes currently exist. The host will run multiple application stacks (Odoo 20, PostgreSQL, ZelixVet, marketing demo). High-volume container output requires proactive log limits.

## 3. Dependency DAG
- **Depends on:** #4 (Baseline Hardening)
- **Blocks:** #6 (Cloudflare Tunnel & Portainer deployment)
- **Concurrency:** Single host-changing task.

## 4. Risk Classification & Approval Gate
- **Risk Class:** `HOST-CHANGE`
- **Requires Owner Approval Before Mutation:** YES (Mandatory)
- **Required Approval Items:** Approval to add official Docker repository and install Docker CE runtime packages.

## 5. Scope
### In-Scope
- Write Ansible playbook `ansible/playbooks/02-docker-engine.yml`.
- Add official Docker GPG key and APT repository (`https://download.docker.com/linux/ubuntu noble`).
- Install pinned Docker CE, containerd, and `docker-compose-plugin`.
- Configure `/etc/docker/daemon.json` with log rotation (`max-size: 20m`, `max-file: 5`).
- Add user `vexteradmin` to `docker` group.
- Configure systemd journal cap (`SystemMaxUse=1G`).

### Out-of-Scope
- No containerized application deployment.
- No public host port publishing (`-p 0.0.0.0:...`).

## 6. Acceptance Criteria
- [ ] Docker service active and enabled on boot (`systemctl is-active docker`).
- [ ] Docker Compose plugin verified (`docker compose version`).
- [ ] `/etc/docker/daemon.json` validated and active.
- [ ] Non-root user `vexteradmin` can run `docker info` without sudo.
- [ ] Test container `docker run --rm hello-world` executes successfully.
- [ ] Completion comment posted with sanitized terminal evidence.

## 7. Verification Plan & Test Commands
```bash
docker --version
docker compose version
docker run --rm hello-world
docker info --format '{{json .LoggingDriver}}'
```

## 8. Rollback & Emergency Recovery
- **Standard Rollback:**
  ```bash
  sudo systemctl stop docker docker.socket
  sudo apt-get remove -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  ```
- **Data Safeguard Invariant:**
  DO NOT remove `/var/lib/docker` during routine rollback. Volume or container state deletion is classified as `PRODUCTION-DESTRUCTIVE` and requires verified backups and separate, explicit owner authorization.
