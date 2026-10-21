# System Architecture: VexterSoft VPS Platform

## 1. Intent and scope

Provide a practical, reusable workflow for provisioning and maintaining general-purpose VexterSoft VPS infrastructure. Start with a secure Ubuntu baseline, install Docker Engine and Compose, and provide Portainer stacks plus Cloudflare Tunnel ingress. Keep server-specific configuration small and separate from shared automation.

This repository is not an Odoo hosting control plane. Odoo, ZelixVet, and other applications may later run as ordinary Portainer stacks when requested, but customer billing, multi-customer orchestration, or Odoo-specific lifecycle logic belong in a separate project.

## 2. Invariants

- **Management stays private:** Portainer, the Docker API, databases, caches, and internal services never publish management ports on public host interfaces.
- **Access is layered:** Portainer's management hostname is routed through Cloudflare Tunnel and protected by an exact-hostname Cloudflare Access policy plus Portainer authentication.
- **Applications are explicit:** Public app hostname routes are added one at a time and do not inherit Portainer's Access policy. Only web frontends join their per-app ingress networks; databases and caches remain private.
- **No incoming tunnel ports:** cloudflared establishes outbound connections. Do not open inbound ports as a tunnel workaround.
- **Idempotence and approval:** Host changes use Ansible playbooks. Host-changing commands require explicit owner approval and an operator confirmation. Destructive volume/data actions require a separate approval and a verified backup.
- **Provider behavior is verified:** UFW, Docker forwarding, IPv4/IPv6 behavior, provider firewall rules, and disk/network capabilities are checked for each supported provider rather than assumed identical.

## 3. High-level topology

```
Cloudflare DNS / Access
  ├── devops.<server-domain> (Access allowlist + Portainer login)
  └── explicitly configured public app hostnames (public)
          │
          │ outbound Cloudflare Tunnel (TCP/UDP 7844)
          ▼
VPS: supported Ubuntu + Docker Engine/Compose
  ├── Cloudflare Tunnel connector
  │     ├── private management network ── Portainer
  │     ├── outbound egress network ── Cloudflare
  │     └── opt-in per-app frontend networks ── public web services only
  └── private app networks ── databases/caches (not attached to cloudflared)
```

The first management phase deploys Portainer and one connector. Application containers remain independent Portainer stacks. A public application may be added by connecting its frontend to its dedicated Docker network, listing the route in that server's configuration, and adding its hostname/origin in Cloudflare. No tunnel architecture rebuild is required.

## 4. Configuration and trust boundaries

- Shared defaults and playbooks are tracked in Git.
- A small ignored host-specific file selects the management hostname and optional app routes.
- Each server has its own Ansible Vault-encrypted Cloudflare tunnel token.
- DNS and Access are managed in Cloudflare after explicit review; this repository does not store a Cloudflare API credential.
- The Portainer Docker socket is a Unix socket mount, not a TCP listener. Anyone who can control Portainer can effectively control the VPS; restrict both Access identities and Portainer credentials.
- Compose uses deliberately managed image tags rather than `latest`. Review upstream releases before changing them.

## 5. Tradeoffs

- **Cloudflare Tunnel instead of inbound web ports:** Requires outbound connectivity to Cloudflare, but avoids opening inbound 80/443 or a management port on each VPS.
- **Docker Compose and Portainer instead of a cluster:** Keeps resource use and recovery steps simple for the initial one-host workflow.
- **Per-app networks instead of a shared public ingress bridge:** Reduces lateral access between unrelated application stacks while keeping a single connector reusable.
