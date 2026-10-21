---
name: qa
description: >-
  Use this skill when the developer says "qa", "run qa", "test", or "validate".
  Executes the project's discovered test suite, static checks, regression analysis, and reports verification status.
---

# QA Lifecycle Orchestrator

The `qa` skill performs quality assurance and validation. It dynamically uses the project's detected test runner and environment.

## Operational Workflow

1. **Read Testing Profile**:
   - Inspect `.alamia/project.json` to identify:
     - `testing.runner` (e.g. `pytest`, `pest`, `vitest`, `cargo`, `go`)
     - `testing.command` (e.g. `pytest`, `npm test`, `./vendor/bin/pest`)
     - `testing.test_dirs`

2. **Execute Automated Tests**:
   - Run the project's detected test command.
   - For focused validation, target tests relevant to recent changes.
   - For full regression validation, run the complete suite.

3. **Check Static Analysis & Linters (if present)**:
   - If linters or typecheckers are configured in the project (e.g. `mypy`, `flake8`, `eslint`, `phpstan`), run them.

4. **Diagnose Failures**:
   - If any test fails, invoke the atomic skill `/diagnosing-bugs` to pinpoint root causes without haphazard patching.

5. **Enforce the completion-report gate**:
   - Compare observed results against all required acceptance criteria and blocking CI/CD checks.
   - If any required test/check is failing, pending, skipped without an approved exception, or unavailable, report **ACTION REQUIRED** and keep the work unverified/blocked. Do not issue a passing/final completion report, mark a PR review-ready, or recommend advancing to a dependent task.
   - For blocked results, report the exact check, observed output/status, impact, and next action. A progress/blocker comment is allowed and encouraged; it must not be framed as completion.
   - Only report **PASSED** when all required acceptance tests and blocking CI/CD checks are green and the evidence is available. Clearly distinguish optional/advisory checks and approved exceptions from required gates.

6. **Generate QA Verification Matrix**:
   - Report:
     - Total tests run, passed, and failed
     - Execution duration
     - Unresolved warnings or deprecations
     - Status: **PASSED** or **ACTION REQUIRED**
