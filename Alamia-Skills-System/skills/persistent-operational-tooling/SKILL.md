---
name: persistent-operational-tooling
description: >-
  Use when performing recurring operational, repository-maintenance, API, GitHub,
  diagnostic, or verification workflows where reusable scripts or tooling may help.
  Prefer discovering and reusing existing tools over repeatedly generating disposable scripts.
---

# Persistent Operational Tooling & Reuse

## Objective

Reduce repeated work, preserve operational knowledge, and make useful tooling available to later agent runs and developers without accumulating unnecessary abstractions.

## Mandatory workflow

1. **Discover before creating.** Inspect relevant existing scripts, installed skills, MCP/connector tools, CLI utilities, and repository conventions before creating a new utility.
2. **Prefer the simplest suitable capability.** Use an already available authorized tool, native command, or existing project utility when it reliably meets the need. Do not build a wrapper merely to duplicate a working connector/tool.
3. **Persist reusable utilities.** If a script is likely to be useful again, place it in an appropriate repository directory and make it parameterized, documented, and independently runnable. Follow local conventions (for example, `scripts/github/`, `scripts/diagnostics/`, or `scripts/architecture/`); these are examples, not mandatory universal paths.
4. **Avoid repeated throwaway scripts.** Do not repeatedly create and delete scripts for recurring GitHub, API, diagnostics, testing, or maintenance workflows when a reusable utility is appropriate.
5. **Use judgment for one-offs.** Simple one-off shell commands, direct tool calls, and genuinely disposable experiments may be appropriate. Do not create permanent scripts for trivial tasks or merely to comply with a blanket rule.
6. **Improve before multiplying.** Extend a suitable existing utility instead of creating a competing one. Keep the change focused and avoid unrelated refactoring.
7. **Secure by default.** Never hardcode credentials or tokens. Use approved credential storage or environment injection, least privilege, input validation, and safe output handling. Do not print secrets or place sensitive responses in tracked files.
8. **Verify before relying on it.** Test new or changed utilities using appropriate non-destructive checks. Document prerequisites, example invocations, actual outcomes, and known limitations. Never report tests as passing unless they ran and passed.
9. **Capture governed learning.** Record the observed issue, evidence, corrective principle, confidence, and applicability. Check for duplicate skills. Submit genuinely reusable lessons through the Skills System review/approval process; do not silently promote unverified observations.
10. **Respect repository boundaries.** Treat this skill as shared guidance, not authority to override local project rules. Bootstrap should register this skill non-destructively and preserve project-owned instructions and entries.

## Decision test

Before creating a script, answer:

- Is this workflow likely to recur?
- Does an existing connector, CLI, script, or test helper already do it?
- Would a reusable script meaningfully improve safety, reliability, or repeated effort?
- Can it be parameterized and tested without introducing disproportionate maintenance burden?

If the task is genuinely one-off or an existing tool is sufficient, do not create a script.

## Completion report

For a new or materially changed utility, report:

- Why it was needed and what existing capability was insufficient.
- File path, intended usage, prerequisites, and security considerations.
- Exact verification commands and actual results.
- Any reusable learning candidate and its approval status.
