# System Architecture: VexterSoft VPS Platform

## 1. Intent & Scope
Provide a reproducible, hardened, and isolated multi-tenant application hosting platform for VexterSoft on an initial Contabo Cloud VPS 6 instance, capable of horizontal migration and dedicated instance replication for future enterprise clients.

## 2. Invariants
- **Zero Exposed Management Sockets:** Portainer, PostgreSQL clusters, Redis caches, and internal Docker networks MUST NOT listen on public interfaces (`0.0.0.0` or `[::]`).
- **Edge Routing Isolation:** Administrative endpoints (e.g., `devops.vextersoft.com`) MUST be fronted by Cloudflare Tunnel + Cloudflare Zero Trust Access.
- **Client App Accessibility:** Client-facing web applications (Odoo 20, ZelixVet, client demo environments) MUST route through public Cloudflare Tunnel hostnames with standard TLS, without forcing client end-users into Zero Trust identity walls.
- **Environment Isolation:** Staging and Production databases, persistent volume directories, and container networks MUST be strictly isolated from each other.
- **Idempotence & Safety:** Every host-level modification MUST be defined as an idempotent Ansible playbook. No changes to SSH, firewall, or persistent storage may occur without a verified rollback/recovery plan.

## 3. High-Level Topology
```
Cloudflare Edge Network
   │ (Outbound Encrypted WireGuard/QUIC Tunnel)
   ▼
Contabo Cloud VPS 6 (Ubuntu 24.04 LTS / 6 vCPU / 11 GB RAM)
   │
   ├── cloudflared daemon (Container / Service)
   │
   └── Docker Engine & Isolated Networks
         ├── devops-net ── Portainer CE (Internal:9000 -> devops.vextersoft.com)
         ├── odoo-prod-net ── VexterSoft Odoo 20 + PostgreSQL 16
         ├── zelixvet-prod-net ── ZelixVet Production + Isolated DB
         ├── zelixvet-staging-net ── ZelixVet Staging + Isolated DB
         └── demo-net ── Hospital/Clinic Marketing Demonstration
```

## 4. Tradeoffs & Decisions
- **Cloudflare Tunnel vs. Direct Inbound Ports (80/443):**
  - *Tradeoff:* Requires outbound tunnel connectivity to Cloudflare's edge; eliminates the need for opening inbound ports or handling local dynamic DDOS filtering directly on the VPS.
- **Docker Compose vs. Kubernetes/k3s:**
  - *Tradeoff:* For a single 6-core / 11 GB host, Docker Compose with Portainer provides near-zero overhead, immediate inspectability, and simpler disaster recovery compared to Kubernetes control plane resource consumption.
