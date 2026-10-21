---
name: implement
description: >-
  Use this skill when the developer says "implement", "implement X", or "start coding".
  Orchestrates active feature development, pulls context from project memory/architecture, and routes to atomic skills.
---

# Implement Lifecycle Orchestrator

The `implement` skill manages the active development phase. It is **project-agnostic** and adapts to the discovered project profile.

## Operational Workflow

1. **Resolve Work Context**:
   - Inspect `.alamia/project.json` for project stack, architecture dir, and memory dir.
   - If the developer specified a task (e.g. "implement X"), use that as the primary objective.
   - If no task was specified, inspect the latest session handoff in the discovered handoff directory and propose working on the highest-priority pending objective.

2. **Inspect Architectural Baseline**:
   - Check the project's discovered architecture directory (e.g. `docs/architecture/` or `.ai/permanent/architecture/`).
   - Read any specifications or conventions relevant to the target module or feature.
   - If a spec is needed before coding, invoke the atomic skill `/to-spec`.

3. **Keep GitHub as the shared task communication record**:
   - For GitHub-backed tasks, use the active issue/PR as the durable record for instructions, decisions, progress, review requests, verification evidence, and handoff. Do not leave important decisions only in chat or a local handoff.
   - Post concise progress comments for meaningful milestones and blocker/status updates when useful. Read and respond to new review comments before claiming the task is complete or starting dependent work.
   - **Do not post a completion/final report, mark the PR review-ready, or claim the task is done until every required acceptance test and blocking CI/CD check is green and the required evidence is recorded.** A pending, failing, skipped-without-approved-justification, or unavailable required gate is not green.
   - While gates are not green, post only a truthful progress/blocker update that lists the failing/pending/unavailable checks, evidence, and next action. Never disguise a blocker as a completion report. If a required check cannot run, keep the task unverified/blocked and ask for the needed decision or environment.
   - After gates are green, post a final report with exact commit SHA, changed files, acceptance-criteria results, exact commands/results, CI run/check links, and unresolved non-blocking risks. Never claim a test or check ran unless its result was observed.
4. **Reuse Operational Tooling Before Creating Utilities**:
   - When a task involves recurring GitHub/API, repository-maintenance, diagnostics, or verification work, consult the registered `persistent-operational-tooling` skill before creating a new script.
   - Discover existing scripts, MCP/connector tools, and CLI capabilities first. Prefer an existing suitable tool; persist a script only when reuse provides real value. Do not add a wrapper solely to duplicate an existing capability.
   - Preserve security, local repository conventions, and the human approval boundary for externally consequential actions.

5. **Orchestrate Atomic Implementation**:
   - For testable logic, invoke the atomic skill `/tdd` (test-driven development).
   - Write or update code following the language conventions detected in `.alamia/project.json`.
   - Update or add tests in the project's detected test directory.

6. **Verify Immediate Changes**:
   - Run the project's detected test command (from `.alamia/project.json`) against the modified unit/file.

7. **Handoff to Validation**:
   - Inform the developer of the completed changes.
   - Suggest the next lifecycle phase: `qa` for comprehensive test suite validation.
