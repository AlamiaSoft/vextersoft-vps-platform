---
name: Agent Task Specification
about: Structured task specification for AI agent and human engineer lifecycle execution
title: "[TASK] "
---

## 1. Objective
<!-- Clear 1-2 sentence description of what will be achieved -->

## 2. Context & Background
<!-- Architectural context, relevant documentation links, discovered invariants -->

## 3. Dependency DAG
- **Depends on:** <!-- e.g., #1, None -->
- **Blocks:** <!-- e.g., #3 -->
- **Concurrency:** <!-- Single host-changing task / Can run concurrently with offline docs -->

## 4. Risk Classification & Approval Gate
- **Risk Class:** `READ-ONLY` | `LOCAL-REPO` | `HOST-CHANGE` | `PRODUCTION-DESTRUCTIVE`
- **Requires Owner Approval Before Mutation:** Yes / No
- **Approval Evidence:** <!-- Link to owner comment authorizing execution if HOST-CHANGE/PRODUCTION-DESTRUCTIVE -->

## 5. Scope
### In-Scope
- <!-- Specific items to modify or create -->

### Out-of-Scope
- <!-- Explicitly forbidden changes -->

## 6. Acceptance Criteria
- [ ] <!-- Criterion 1 -->
- [ ] <!-- Criterion 2 -->
- [ ] Non-destructive verification command passed with clean exit code
- [ ] Completion comment posted with branch/PR links and sanitized terminal outputs
- [ ] Left open for owner review and signoff

## 7. Verification Plan & Test Commands
```bash
# Exact commands the agent must execute to prove functionality
```

## 8. Rollback & Emergency Recovery
<!-- Step-by-step procedure to revert changes if failure occurs -->
```bash
# Rollback commands
```

## 9. Deliverables
- <!-- Branch: agent/issue-<number>-<slug> -->
- <!-- Files created or modified -->
