# Sprint Current State

**Last Updated:** 2026-10-21  
**Current Phase:** Local implementation and validation of Cloudflare Tunnel + Portainer automation

## Completed and verified phases

- Bootstrap plan audit and execution DAG (Issue #2 / PR #8) refreshed and rebased against main.
- Windows/WSL operator environment and Ansible workflow were established.
- Baseline hardening was applied and verified on the initial Ubuntu 24.04 VPS.
- Docker Engine and the Compose plugin were installed through Ansible; the Docker phase completed at `f5c08cb` and was merged to main in commit `7b25538`.
- The current host uses a restrictive UFW baseline, with SSH as the only inbound allow rule; Docker API and management ports are not intentionally published.
- The working repository's current main checkout contains unrelated local edits. Keep those edits untouched; ingress work is isolated in branch `agent/issue-6-cloudflare-portainer` in a separate worktree.

## In progress

- Build the local Cloudflare Tunnel + Portainer Ansible phase, Compose template, per-server secret/config pattern, recovery documentation, and operator commands.
- Local implementation does not imply a Cloudflare tunnel/DNS/Access policy exists or that containers were deployed.
- No VPS or Cloudflare account changes are authorized by this local implementation task.

## Next steps

1. Finish local playbook syntax, lint, template rendering, and operator script validation.
2. Review the diff, commit the local implementation, and hand it off for review.
3. Owner creates/verifies a remotely managed Cloudflare tunnel, configures the exact management hostname, and places its token in the local Ansible Vault file.
4. Obtain separate explicit approval for deploying the ingress phase to a named VPS.
5. Verify the tunnel connector, health checks, absence of public management ports, Access allow/deny behavior, and Portainer login.
6. Add application hostnames only as explicitly reviewed public routes; leave app deployments in Portainer stacks.

## Scope boundary

This repository automates generic VPS setup and app infrastructure. Odoo Cloud control-plane features, customer billing, multi-customer lifecycle logic, and Odoo staging/production orchestration are excluded and belong in the separate VexterSoft Odoo Cloud initiative.
