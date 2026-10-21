# Developer Workflows: Alamia-Skills-System in Action

> **A comprehensive guide demonstrating how developers interact with the Alamia-Skills-System lifecycle operating model across any software project.**

---

## 1. The Interaction Model

Traditional AI pair programming forces developers into **tool and prompt micromanagement**:
- *"Read file A, check git status, see what we did in the last session."*
- *"Run our test runner on the test folder."*
- *"Review the code smells in this new function."*
- *"Write a handoff note for next time."*

With **Alamia-Skills-System**, developers communicate at the **lifecycle and strategic level**. The system autonomously resolves project state, discovers the stack, executes the correct test runner, enforces domain invariants, and chains atomic skills:

```text
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌─────────────────────┐     ┌──────────────┐
│  bootstrap   │ ──> │  implement   │ ──> │      qa      │ ──> │ architecture-review │ ──> │ session-end  │
│ (Kickoff/Ctx)│     │ (Coding/TDD) │     │ (Validation) │     │  (Drift Governance) │     │ (Next Handoff│
└──────────────┘     └──────────────┘     └──────────────┘     └─────────────────────┘     └──────────────┘
       │                    ▲                    │                                                ▲
       ▼                    │                    ▼                                                │
┌──────────────┐     ┌──────────────┐     ┌───────────────────┐                          ┌──────────────┐
│expert-consult│ ──> │ingest-critique│    │ audit-portability │                          │agent-pm state│
│(Prompt Synth)│     │(Feedback->DAG│    │(Zero Env Lock-in) │                          │(DAG Sealing) │
└──────────────┘     └──────────────┘     └───────────────────┘                          └──────────────┘
```

The system contains **zero hardcoded project assumptions**. Below are the concrete workflows demonstrating the complete developer experience.

---

## Workflow 1: Starting a Work Session (`bootstrap`)

### The Developer's Input
```text
"Bootstrap this project"
```
*(or simply `"Start session"`)*

### Behind the Scenes: What Alamia-Skills-System Does
1. **Dynamic Stack Discovery (`core/adapters/stack_detector.py`):**
   - Inspects manifests (`package.json`, `composer.json`, `pyproject.toml`, `Cargo.toml`, etc.) in root and subdirectories to identify languages, frameworks, package managers, and container setups.
2. **Dynamic Test Runner Discovery (`core/adapters/test_detector.py`):**
   - Automatically determines the test runner and command (e.g. `pytest`, `npm test`, `npx vitest`, `./vendor/bin/pest`, `cargo test`).
3. **Session Memory & PM Discovery (`core/adapters/memory_detector.py`):**
   - Scans for existing session memory across common conventions (`.project/tasks`, `docs/handoffs/`, `.ai/transient/handoffs/`, `handoffs/`, `CHANGELOG.md`).
   - Parses the latest handoff file or DAG queue and extracts active pending objectives.
4. **Git Inspection:**
   - Detects the active branch, latest commit, and uncommitted changes.
5. **Idempotent Reconciliation (`core/reconciler.py`):**
   - Generates or reconciles `.alamia/project.json` and connects lifecycle commands and vendored atomic skills (`agent-pm`, `mattpocock-skills`) without touching project business code.

### The System's Response to the Developer
```markdown
# Alamia-Skills-System: Bootstrap & Reconciliation Report

**Project:** `payment-service` | **Status:** `Case D` (Configured & Reconciled)

---

### 1. Discovered Stack & Environment
- **Primary Language:** `typescript` (Frameworks: `express, prisma`)
- **Package Manager:** `pnpm` | **Containers:** `docker-compose`

### 2. Testing Configuration
- **Runner:** `vitest` | **Command:** `pnpm test` | **Dir:** `tests/`

### 3. Discovered Project Memory
- **Handoff Location:** `.project/tasks` / `docs/handoffs/`
- **Latest Handoff:** `docs/handoffs/04-webhook-integration.md`
- **Active Pending Objectives:**
  1. Add HMAC-SHA256 signature verification to webhook endpoints
  2. Implement Redis-backed idempotency key cache
  3. Add retry backoff policy for failed provider notifications

### 4. Git State
- **Branch:** `feature/webhooks` (`9a14c2b add webhook route skeleton`)
- **Working Tree:** Clean

---
**Ready.** You can now say `implement`, `qa`, `architecture-review`, or `session-end`.
```

---

## Workflow 2: Active Feature Implementation (`implement`)

### Scenario A: Working on the Next Pending Objective
The developer does not need to copy-paste tasks from previous chats:

```text
"Implement the next pending objective"
```

#### What Alamia-Skills-System Does:
1. Resolves next unblocked task (via `node scripts/pm.js next` or `.alamia/project.json` latest handoff).
2. Compiles targeted context brief (`pm.js context <id>`).
3. Reads the relevant architectural specification from the discovered architecture directory.
4. Invokes Matt Pocock's atomic skill `/tdd`:
   - Writes a unit test asserting edge cases and failure modes.
5. Implements the business logic following project conventions.
6. Executes the project's detected test runner to verify green phase.
7. Hands control back to the developer:
   > *"Implemented HMAC-SHA256 webhook signature verification. Targeted unit tests passing. Ready for `qa`."*

---

## Workflow 3: Validation & Quality Assurance (`qa`)

### The Developer's Input
```text
"Run QA"
```
*(or `"Test changes"`, `"Validate"`)*

### Behind the Scenes: What Alamia-Skills-System Does
1. Checks `.alamia/project.json` for the discovered test runner command.
2. Executes the test suite against changed modules and full regressions.
3. Runs configured linters or typecheckers (`tsc --noEmit`, `eslint`, `phpstan`, `mypy`).
4. **Failure Handling:** If a test fails, automatically invokes `/diagnosing-bugs`, isolates the root cause, and proposes the minimal fix.

### The System's Response to the Developer
```markdown
## QA Verification Matrix

| Target | Tests Run | Passed | Failed | Duration |
| :--- | :---: | :---: | :---: | :---: |
| `tests/webhooks/signature.test.ts` | 6 | 6 | 0 | 0.38s |
| `tests/api/checkout.test.ts` | 14 | 14 | 0 | 0.82s |

- **Automated Tests:** PASSED
- **Type Checking:** 0 errors clean
- **Regressions:** None detected
- **Overall QA Status:** **PASSED (Green)**
```

---

## Workflow 4: Architectural Drift Governance (`architecture-review`)

### The Developer's Input
```text
"Review architecture"
```
*(or `"Check drift"`)*

### Behind the Scenes: What Alamia-Skills-System Does
1. Checks `.alamia/project.json` for `memory.architecture_dir`.
2. Inspects `git diff` against base branch or merge-base.
3. Invokes two-axis `/code-review`:
   - **Axis 1 (Standards):** Checks against Fowler smell baseline (Feature Envy, Data Clumps, Shotgun Surgery).
   - **Axis 2 (Spec & Invariants):** Validates against the project's documented architecture rules and domain boundaries.

---

## Workflow 5: Ending a Session & Preserving Continuity (`session-end`)

### The Developer's Input
```text
"End session"
```
*(or `"Wrap up"`, `"Handoff"`)*

### Behind the Scenes: What Alamia-Skills-System Does
1. Inspects Git working tree (`git status --short`) to catalog all modifications.
2. Verifies latest test suite health and closes out completed `agent-pm` tasks with evidence.
3. Detects sequential handoffs in `docs/handoffs/` or updates worklogs.
4. Writes the next sequential handoff file recording:
   - *Objectives Achieved*
   - *Key Verification Artifacts & System State*
   - *Pending Work / Next Objectives*
5. Reports Git status cleanly without auto-pushing unless requested.

---

## Workflow 6: Expert Consultation Prompt Builder (`expert-consult`)

### The Developer's Input
```text
"Prepare an expert consultation prompt for <subsystem or problem>"
```

### Purpose & Problem Solved
When dealing with complex mathematical formulas, forensic anomaly diagnosis, intricate state machines, or regulatory logic, asking a single agent can lead to hallucinated shortcuts. Developers need a clean, condensed, architecture-first consultation prompt to feed to an expert model or senior architect.

### Behind the Scenes: What Alamia-Skills-System Does
1. Analyzes the target subsystem, service layer, and data invariants.
2. Synthesizes an **Architecture-First Consultation Brief**:
   - High-level system architecture and constraints.
   - Exact implementation summary (methods, formulas, tables).
   - Concrete problem statement or anomaly example.
   - Specific, targeted questions for the expert.
3. Saves the prompt to `docs/consultations/<topic>-prompt.md` (or artifact) for immediate copy-paste or subagent invocation.

---

## Workflow 7: Feedback & Critique Ingestion into Task DAG (`ingest-critique`)

### The Developer's Input
```text
"Ingest feedback from docs/reviews/feedback.md into project tasks"
```

### Purpose & Problem Solved
Expert critiques, code review comments, and domain audits arrive as unstructured prose. Developers lose time manually parsing and typing individual task tickets.

### Behind the Scenes: What Alamia-Skills-System Does
1. Parses the feedback file into discrete, actionable critique points.
2. Correlates each point with affected files in the repository.
3. Automatically creates dependency-ordered `agent-pm` tasks:
   ```bash
   node scripts/pm.js add "<Issue Title>" --priority=<Prio> --epic=<Epic>
   ```
4. Updates the task DAG with explicit test verification requirements.
5. Returns a structured ingestion matrix mapping feedback items to task IDs.

---

## Workflow 8: Portability & Environment Hardening Audit (`audit-portability`)

### The Developer's Input
```text
"Audit portability"
```
*(or `"Check environment readiness"`, `"Harden deployment"`)*

### Purpose & Problem Solved
Prevents subtle environment breakage before deployment:
- Hardcoded relative query parameters (e.g. `?page=coa`) that break when hosted under subdirectories or reverse proxies.
- Hardcoded filesystem path separators (`\` vs `/`) breaking across Windows/Linux.
- Hardcoded localhost ports, static origins, or absolute file URLs.

### Behind the Scenes: What Alamia-Skills-System Does
1. Scans modified source files for hardcoded query strings, static base URLs, and OS path separators.
2. Verifies that all routes use dynamic URL builders or framework route helpers.
3. Checks environment variable fallbacks and configuration managers.
4. Generates a **Portability & Environment Audit Matrix** highlighting any detected environment lock-in.

---

## Workflow 9: Anti-Heuristic & Invariant-Guarded Implementation (`rule-first-tdd`)

### The Developer's Input
```text
"Implement task T-XXX with strict invariants"
```
*(or `"Implement X with zero heuristic guessing"`)*

### Purpose & Problem Solved
AI coding tools frequently introduce fuzzy heuristic guesses (e.g. `startsWith('4')`, `includes('tax')`, or hardcoded fallback codes) that cause subtle data corruption in enterprise software.

### Behind the Scenes: What Alamia-Skills-System Does
1. **Invariant Declaration Gate**: Identifies and logs the inviolable domain invariants before touching any production code.
2. **Negative Tests First**: Writes unit tests that explicitly attempt to violate the invariant or feed heuristic edge cases, proving the test fails.
3. **Explicit Rule Resolution**: Implements logic using strict configuration rules, explicit parameters, or user selections—eliminating all pattern-matching guesswork.
4. **Verification Gate**: Executes tests ensuring both positive assertions and negative invariant protections pass.

---

## Summary Cheatsheet

| Command | What to Say | What Alamia Does | Next Step |
| :--- | :--- | :--- | :--- |
| **`bootstrap`** | *"Bootstrap project"* / *"Start session"* | Discovers stack, tests, git state, and extracts last handoff's pending tasks. | Proceed to `implement`. |
| **`implement`** | *"Implement next task"* / *"Implement X"* | Reads architecture spec, loads context brief, writes code & tests via `/tdd`. | Proceed to `qa`. |
| **`qa`** | *"Run QA"* / *"Validate changes"* | Executes detected test runner & linters; isolates bugs with `/diagnosing-bugs`. | Proceed to `architecture-review`. |
| **`architecture-review`**| *"Review architecture"* / *"Check drift"* | Compares diff against architecture specs using two-axis `/code-review`. | Proceed to `session-end`. |
| **`session-end`** | *"End session"* / *"Wrap up"* | Verifies tests, seals PM tasks with evidence, and writes sequential handoff. | Session closed cleanly. |
| **`expert-consult`** | *"Prepare expert prompt for X"* | Compiles zero-bloat architecture-first consultation prompt for expert models. | Share with expert model. |
| **`ingest-critique`** | *"Ingest feedback from <file>"* | Parses critique into discrete issues and generates structured `agent-pm` DAG tasks. | Proceed to `implement`. |
| **`audit-portability`** | *"Audit portability"* / *"Harden"* | Scans for hardcoded URLs, path separators, and environment lock-ins. | Safe for multi-env deploy. |
| **`rule-first-tdd`** | *"Implement X with strict invariants"*| Enforces negative invariant tests first; eliminates heuristic guessing. | Proceed to `qa`. |
