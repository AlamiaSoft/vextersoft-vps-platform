# AI Workspace Instructions (AGENTS.md)

This file contains the foundational rules for all AI agents working in this repository. It is automatically injected into the context of every new conversation.

## 1. The Canonical Execution Protocol
All agents MUST strictly follow and enforce [AGENT_PROTOCOL.md](../AGENT_PROTOCOL.md). 
- Every non-trivial task must be tied to a GitHub Issue and follow the issue lifecycle comments (Pre-execution comment, Checkpoint when blocked, Completion comment with sanitized terminal evidence).
- Feature / task branches must follow: `agent/issue-<number>-<short-slug>`.
- Changes must be submitted via Pull Request targeting `main`. Agents must NOT merge PRs or close issues unilaterally without explicit owner authorization.

## 2. Risk Classification & Approval Gates
- **`READ-ONLY`**: Diagnostic inspection only. Self-authorized.
- **`LOCAL-REPO`**: Code/docs/playbook updates in local repo. Self-authorized.
- **`HOST-CHANGE`**: Any system package, user, SSH, UFW, swap, Docker, or service modification on the VPS. **Requires explicit owner approval recorded on GitHub before execution.**
- **`PRODUCTION-DESTRUCTIVE`**: Production cutovers, database restores, volume deletion, or lockout-prone changes. **Requires explicit owner approval naming target & operation, plus validated rollback.**
- *Note:* Silence, general plan review, or generic words like "continue" do **NOT** constitute approval for host-changing or destructive actions.

## 3. Host Safety & Security Invariants
- **Dual-Session SSH Gate:** Before altering SSH configuration or firewall rules, prove non-root SSH key sudo access in an independent secondary session while preserving the primary session.
- **Zero Exposed Management Sockets:** Portainer, PostgreSQL, Redis, and internal Docker networks must never bind to public host interfaces (`0.0.0.0` or `[::]`). Administrative traffic must route exclusively through Cloudflare Tunnel + Cloudflare Access.
- **Zero Secrets Invariant:** Never log, commit, or post secrets, private keys, or tokens to GitHub or documentation.
- **OS Reinstallation Prohibited:** Never reinstall the OS unless an explicit, concrete reason is approved by the owner.

## 4. The AI Bootstrap Sequence
If entering a fresh conversation without full project context, follow this read order:
1. Read `.ai/README.md` (Master Index)
2. Read `.ai/transient/sprint/00-current-state.md`
3. Read `.ai/permanent/architecture/01-system-architecture.md`
4. Read `.ai/indexes/repository.md` to map concepts to code.
5. Read `AGENT_PROTOCOL.md` for workflow rules.
6. Only then inspect the source code or work on tasks.

## 5. Documentation Ownership
- Document *intent, invariants, tradeoffs, and failure modes*.
- Maintain documentation integrity in `.ai/` and `docs/` concurrently with implementation.
