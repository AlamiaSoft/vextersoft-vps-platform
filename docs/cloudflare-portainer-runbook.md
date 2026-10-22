# Cloudflare Tunnel and Portainer Runbook

This runbook provisions a single VPS management plane. It does not manage Cloudflare DNS, Cloudflare Access policies, application deployments, billing, or customer hosting. Do those changes deliberately in Cloudflare and through Portainer.

## Architecture and security boundaries

- A remotely managed Cloudflare Tunnel connector runs in Docker and makes outbound connections to Cloudflare. No inbound VPS port is required. Allow outbound TCP or UDP 7844 through the VPS provider firewall and any egress filter. See [Cloudflare's firewall requirements](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/).
- Portainer is reachable from the connector on the private `vextersoft-management` Docker network at `http://portainer:9000`. Compose publishes no host port for Portainer, cloudflared metrics, or the Docker API.
- The management network is internal to Docker. A separate egress network lets cloudflared contact Cloudflare. Portainer mounts the Docker Unix socket; access to that socket is effectively root access to the host. The container uses Portainer's documented `--health-check` mode ([CLI options](https://docs.portainer.io/advanced/cli)).
- Cloudflare Access must protect only the Portainer management hostname, for example `devops.vextersoft.com`. Portainer also requires its own administrator login.
- Public application ingress is opt-in. Each public frontend gets a dedicated Docker network and an explicit route. Databases, Redis, SSH, and management services must not join these public frontend networks.
- The tunnel is remotely managed in Cloudflare. Ansible stores the connector token and deploys the connector, but it does not create DNS records, Access applications, or tunnel routes.

## Prerequisites

- Ubuntu 24.04, which is the currently supported baseline and Docker phase target.
- Docker and the Compose plugin already installed and healthy.
- The baseline firewall is active: incoming deny, outgoing allow, forwarding deny, IPv6 filtering enabled. The playbook checks these settings and makes no firewall changes.
- The provider firewall permits established outbound traffic and outbound TCP or UDP port 7844 to Cloudflare. Provider firewalls and IPv6 behavior vary; confirm them separately.
- Strict SSH host-key verification is working from WSL. Keep `host_key_checking = True`.
- Install Ansible collections from the repository root: `ansible-galaxy collection install -r ansible/requirements.yml`.
- Ansible inventory exists locally at `ansible/inventory/hosts.yml` and names the intended server alias.
- The selected alias must be a member of `vps_servers` and resolve to one literal host, SSH user, and valid port. The operator prints only those target details before asking for typed approval; it refuses placeholders, unsupported connection types, or ambiguous inventory.

## Cloudflare setup required before deployment

1. Confirm `vextersoft.com` (or the selected server's domain) is active in the correct Cloudflare account and that you can administer its DNS and Zero Trust settings.
2. Create a **remotely managed named tunnel** for the VPS in the Cloudflare Zero Trust dashboard. Do not reuse another server's connector token unless you have intentionally designed that shared failure boundary.
3. In the tunnel's public hostname configuration, plan `devops.vextersoft.com` (or the hostname in the per-server config) to route to the service `http://portainer:9000`. The tunnel container can resolve the `portainer` service on its Docker management network.
4. Before enabling that route, create a self-hosted Cloudflare Access application for the exact management hostname. Add a default-deny posture with an allow policy for the intended user/group and require MFA through the chosen identity provider. Do not add a bypass policy. Test both an allowed identity and a denied identity.
5. Do not configure a wildcard hostname. Add future application hostnames one at a time and do not attach the Portainer Access application to them. Cloudflare DNS/Tunnel hostname routing is a separate deliberate configuration step.

Cloudflare owns DNS and Access configuration. The playbook does not need a Cloudflare API token and does not make those account changes.

## Per-server configuration and secret setup

Copy the tracked example using the inventory alias as the directory name:

```bash
mkdir -p ansible/inventory/host_vars/vextersoft_vps
cp ansible/inventory/host_vars/EXAMPLE_HOST/cloudflare.yml.example \
  ansible/inventory/host_vars/vextersoft_vps/cloudflare.yml
```

Edit the non-secret file to set that server's management hostname and optional public routes. The actual `cloudflare.yml` is ignored by Git.

Create the encrypted secret file with the WSL editor:

```bash
ansible-vault create ansible/vault/vextersoft_vps.vault.yml
```

Enter only this YAML variable in the editor, substituting the tunnel token locally:

```yaml
cloudflare_tunnel_token: "PASTE_THE_TUNNEL_TOKEN_IN_THE_EDITOR"
```

Save and close the editor. The file is ignored by Git and encrypted by Ansible Vault. Do not put the token in chat, shell arguments, environment variables, Compose files, issue comments, or logs. The deployment copies it to a root-owned, read-only host file and mounts it into cloudflared as a file secret. Tasks touching the token suppress both logs and diffs. Cloudflare supports `--token-file` for remotely managed tunnels with cloudflared 2025.4.0 and later ([run parameters](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/)).

The playbook verifies that the Vault file begins with the Ansible Vault encryption header and loads the token into a dedicated `cloudflare_vault` namespace. It does not accept a plaintext token variable from inventory or the command line. Keep the management hostname and route list in the ignored `cloudflare.yml`; those per-host values override the safe playbook defaults. The encrypted file lives under `ansible/vault/`, outside Ansible's auto-discovered `host_vars`, so normal `ansible-inventory --list`, `doctor`, and `validate` do not need a Vault password or load the credential into inventory JSON.

For another server, create its own host_vars directory and its own tunnel token. Keep hostnames and app routes in that server's ignored `cloudflare.yml`; keep only credentials in `ansible/vault/<alias>.vault.yml`. If upgrading from the old location, move the encrypted file without decrypting or displaying it, then remove the old `host_vars/<alias>/vault.yml` before running `doctor` or `validate`:

```bash
mkdir -p ansible/vault
mv ansible/inventory/host_vars/vextersoft_vps/vault.yml ansible/vault/vextersoft_vps.vault.yml
```

Create a new Vault file at the new path with `ansible-vault create ansible/vault/vextersoft_vps.vault.yml`.

## Validation and deployment

Run from WSL at the repository root. The normal Ansible config enforces SSH host-key checking and the inventory's SSH identity.

```bash
export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"
ansible-playbook --syntax-check \
  -i ansible/inventory/hosts.yml \
  ansible/playbooks/03-cloudflared-portainer.yml
ansible -i ansible/inventory/hosts.yml vextersoft_vps -m ping
```

Review the playbook and its preflight output. The preflight refuses to proceed if Docker is unhealthy, UFW defaults are not restrictive, forwarding or IPv6 policy differs, Docker is configured with a TCP API listener, or Docker/host listeners already publish management ports.

Only after separate owner approval for this exact VPS and phase, run:

```bash
ansible-playbook --ask-vault-pass --diff \
  -i ansible/inventory/hosts.yml \
  --limit vextersoft_vps \
  -e cloudflare_deployment_approved=true \
  ansible/playbooks/03-cloudflared-portainer.yml
```

The PowerShell operator performs syntax and strict SSH connectivity checks without asking for the Vault password. It asks for the Vault password once, at deployment time. The command above is the direct Ansible equivalent. The PowerShell ingress action additionally requires `-ApproveHostChange` and the exact typed phrase `APPLY ingress <inventory-alias>`; it sets `cloudflare_deployment_approved=true` only after that confirmation. The playbook's own approval variable defaults to false. Do not run it enabled until the Cloudflare tunnel, exact hostname, Access policy, provider egress, and target inventory have been reviewed. Do not disable host-key checking.

After Ansible succeeds, verify:

```bash
ansible -i ansible/inventory/hosts.yml vextersoft_vps -m ping
ansible -i ansible/inventory/hosts.yml vextersoft_vps -m command -a \
  "docker compose -f /opt/vextersoft/management/compose.yml ps"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -m command -a \
  "docker ps --format '{{.Names}}|{{.Ports}}'"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -m command -a "ss -lnt"
ansible -i ansible/inventory/hosts.yml vextersoft_vps -m command -a "ufw status verbose"
```

Confirm both services report healthy, the tunnel shows connected in Cloudflare, the Portainer login loads after Access authentication, an unapproved identity is denied, and no Docker API or Portainer port is published on the host. Test a future public app with an unauthenticated browser session only after its route has been explicitly configured.

The preflight reads UFW defaults, IPv4/IPv6 forwarding rules, host listeners, Docker port bindings, and Docker network membership. It stops if it cannot inspect both firewall rule tables, finds common database-port listeners/publications/DNAT rules, or finds unexpected containers on management, tunnel-egress, or configured public frontend networks. These checks are guardrails, not a complete firewall audit; review provider firewall rules and Docker networking before approval. The playbook never changes UFW and does not treat UFW as sufficient protection from Docker-published ports.

## Adding a public application route

For each public web frontend:

1. Put the frontend on a dedicated external Docker network. Keep its database/cache on a separate private network that the connector does not join.
2. Add a route entry to that server's ignored `cloudflare.yml`, for example:

   ```yaml
   cloudflare_public_routes:
     - hostname: app.example.com
       network: app_public_frontend
       service: web
       port: 8080
   ```

3. Redeploy the ingress phase after reviewing the diff and getting explicit host-change approval. This attaches cloudflared to the named frontend network; it does not deploy or publish the application container.
4. In Cloudflare, add an exact public hostname route to `http://web:8080`. Do not add an Access application/policy to that hostname. Test from a logged-out browser.
5. Never add database, Docker API, SSH, Portainer, or other management targets to `cloudflare_public_routes`.

## Updates, rollback, and recovery

If the Ansible run fails, do not blindly rerun it. First inspect whether the management project and its persistent resources were created:

```bash
docker compose -p vextersoft-management -f /opt/vextersoft/management/compose.yml ps --all
docker network ls --filter name='vextersoft-management'
docker network ls --filter name='vextersoft-tunnel-egress'
docker volume inspect vextersoft_portainer_data
```

These commands are read-only. Compare the containers, network isolation, and volume labels with the failed task. Preserve the Portainer volume and root-managed token file while investigating. Inspect logs without printing the mounted token or reading its file. Resolve the specific cause, then review the Ansible diff and obtain fresh approval before another host-changing run. If routing or Access is the problem, correct it in Cloudflare separately; do not expose a host port as a workaround.

- Image versions are deliberately managed in the playbook variables: Portainer CE `2.45.1` LTS (`portainer/portainer-ce:2.45.1-alpine`) and cloudflared `2026.10.2`. Review [Portainer releases](https://github.com/portainer/portainer/releases) and [cloudflared releases](https://github.com/cloudflare/cloudflared/releases) before updating tags; do not use `latest`. Test a planned version change before redeploying.
- Normal rollback stops and removes only the Compose containers. It preserves Portainer's external named volume:

  ```bash
  cd /opt/vextersoft/management
  docker compose -p vextersoft-management -f compose.yml down
  ```

  Never add `-v` to routine rollback. Removing `vextersoft_portainer_data` deletes Portainer users, settings, and endpoint metadata and requires a separate destructive approval and a verified backup.
- The Cloudflare DNS route and Access application are managed separately. For a full ingress rollback, first remove/disable the hostname route in Cloudflare, retain the Access policy, then stop the local stack. Existing application containers are not changed by this playbook.
- Before a Portainer upgrade, take a verified quiesced backup of `vextersoft_portainer_data` using the repository's shared helper (`scripts/portainer_backup.py`), which guarantees restarting Portainer in a `finally` block even if archive creation or verification fails:

  ```bash
  sudo install -d -m 0700 -o root -g root /var/backups/vextersoft-portainer
  BACKUP_FILE="/var/backups/vextersoft-portainer/portainer-data-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
  python3 scripts/portainer_backup.py backup \
    --source-volume vextersoft_portainer_data \
    --archive-path "$BACKUP_FILE" \
    --quiesce-container vextersoft-management-portainer-1 \
    --sudo
  ```

  Protect the backup as sensitive data, copy it off the VPS, and verify the off-host copy with `python3 scripts/portainer_backup.py verify-archive --archive-path <FILE>`. Always validate restores into a separate disposable volume first using `python3 scripts/portainer_backup.py restore-sandbox`; never test restore by overwriting the active volume (`PRODUCTION-DESTRUCTIVE`). See `docs/devops-handover-runbook.md` for full backup scope, `:ro` vs. quiesced consistency details, and failure recovery steps.
- If a tunnel token is exposed or invalid, create/rotate the connector token in Cloudflare, update the encrypted per-server Vault file locally, and redeploy only after approval. Revoke the old token in Cloudflare.
- If Portainer data is corrupt, keep the current volume intact, stop the stack, restore a verified backup to a separate volume, and review the recovery plan before switching the Compose volume name.
- When tunnel connectivity fails, verify outbound TCP/UDP 7844 with the provider, confirm the connector status in Cloudflare, inspect container health/logs without printing secret files, and test DNS/Access configuration. Do not open inbound ports as a workaround.
