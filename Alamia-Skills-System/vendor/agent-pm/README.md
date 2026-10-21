# 🚀 Agent-PM: Universal Project Execution Protocol for Humans & AI Agents

> **The zero-dependency, GitOps-native task DAG state machine, context compiler, and live Kanban engine built for AI pair programmers (Antigravity IDE, Claude, OpenAI, Cursor) and human engineering teams.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Node.js](https://img.shields.io/badge/Node.js-%3E%3D16-green.svg)](https://nodejs.org/)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-0-brightgreen.svg)]()

---

## 💡 Why Agent-PM?

When using autonomous AI agents or pair-programming with LLMs, traditional project management tools (Jira, Linear, GitHub Projects) fail because:
1. **Context Window Pollution**: AI agents spend thousands of tokens searching directories, reading stale docs, or asking repetitive questions.
2. **Hallucinated Task Completion**: Agents often claim a feature is "done" without executing unit tests or verification scripts.
3. **No Local Single Source of Truth (SSOT)**: Task state lives in a remote SaaS platform disconnected from the Git branch and local filesystem.

**Agent-PM solves this with an embedded, version-controlled architecture:**
- 📂 **100% Git-Native**: Everything lives in `.project/` inside your repository as markdown and YAML files.
- ⚡ **Context Compiler (`pm context <ID>`)**: Condenses task specs, acceptance criteria, relevant files, and linked Architecture Decision Records (ADRs) into a laser-focused **2–8 KB handoff brief**.
- 🛡️ **Hard Verification Gate (`pm finish <ID>`)**: Tasks physically cannot transition to `DONE` unless their declared test command passes.
- 📊 **Built-in Zero-Dependency Kanban (`pm board`)**: An interactive, responsive Kanban board running on vanilla Node.js (`http://localhost:4200`).
- 🤖 **Antigravity IDE & AI-Agent Ready**: Includes `.agents/skills/agent-pm/` so any AI agent instantly knows how to claim, execute, and verify tasks.

---

## 📦 Quick Installation

### Option 1: Use with `npx` (No Install Required)
```bash
# In any project repository:
npx agent-pm init
```

### Option 2: Install Globally via `npm`
```bash
npm install -g agent-pm
agent-pm init
```

### Option 3: Copy as a Local Script
Copy `bin/pm.js` into your project's `scripts/pm.js` and run:
```bash
node scripts/pm.js init
```

---

## 🛠️ CLI Command Reference

| Command | Description |
| :--- | :--- |
| `pm status` | Displays an ASCII executive progress bar and breakdown of ready, in-progress, and blocked tasks. |
| `pm next [--agent=<role>]` | Resolves DAG dependencies and automatically outputs the next unblocked task. |
| `pm context <ID>` | Compiles an exact 2–8 KB context handoff containing spec, acceptance criteria, relevant files, and ADRs. |
| `pm start <ID> [--agent=<role>]` | Claims a task, moves state to `IN_PROGRESS`, and records Git commit/session in `.project/runs/`. |
| `pm verify <ID>` | Runs the automated test/build verification command specified in the task frontmatter. |
| `pm finish <ID> --evidence="..."` | Enforces the hard verification test gate and seals the task as `DONE`. |
| `pm block <ID> --reason="..."` | Marks a task as `BLOCKED` with documented blockers. |
| `pm board [--port=4200]` | Boots an instant, interactive local Kanban dashboard at `http://localhost:4200`. |
| `pm init` | Scaffolds the `.project/` directory structure with sample tasks and ADRs. |

---

## 📋 Directory Architecture (`.project/`)

```
.project/
├── project.yaml              # Project metadata, global invariants, active epics, roles
├── tasks/                    # Atomic, durable task specifications (Markdown + YAML)
│   ├── T-001-setup.md
│   ├── T-002-api-contract.md
│   └── T-003-frontend-ui.md
├── epics/                    # High-level milestones and roadmaps
├── decisions/                # Architecture Decision Records (ADRs)
└── runs/                     # Execution run logs, agent timestamps, and Git commits
    └── T-001/
        └── run-1728300000.json
```

---

## 🧪 Example Task File (`.project/tasks/T-001-setup.md`)

```markdown
---
id: T-001
title: Front-Office POS Integration API
status: ready
priority: critical
epic: EP-02-pos-integration
assigned_to: backend
depends_on: []
blocks: [T-002]
relevant_files:
  - app/Http/Controllers/Api/SalesController.php
  - routes/api.php
decisions:
  - ADR-002-pos-contract
verification: php tests/verify_sales_api.php
tags:
  - api
  - pos
---

## Objective
Implement front-office POS checkout endpoint posting double-entry vouchers.

## Acceptance Criteria
- [ ] Create `POST /api/v1/sales` endpoint
- [ ] Support both instant post and staged manager approval modes
- [ ] Return standard JSON response with `SV-` and `RV-` voucher references
```

---

## 🤖 Using Agent-PM with Antigravity IDE & AI Agents

Add this rule to your project's `AGENTS.md`:

```markdown
## Project Execution Protocol (Agent-PM)
All agents working on this codebase must follow the version-controlled task DAG in `.project/`:
1. Never scan the whole repo for context: Run `node scripts/pm.js next` or `node scripts/pm.js context <id>`.
2. Start tasks with `node scripts/pm.js start <id>`.
3. Complete tasks with `node scripts/pm.js finish <id> --evidence="Tests passed"`.
```

---

## 📄 License
MIT License. Free for open source and commercial use.
