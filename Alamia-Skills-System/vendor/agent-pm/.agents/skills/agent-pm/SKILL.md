---
name: agent-pm
description: >-
  Agent-PM is a high-velocity, single-source-of-truth project management & DAG execution protocol
  designed for AI agents and human developers. Provides zero-token-waste context compilation,
  hard verification gates, run logging, and an embedded Kanban dashboard across any project repository.
---

# Agent-PM (Project Management & Execution Protocol)

Agent-PM provides a standardized, token-efficient, zero-dependency task coordination system stored directly in the repository under `.project/`.

## Quick Reference CLI Commands

| Command | Purpose |
| :--- | :--- |
| `node scripts/pm.js status` | High-level ASCII progress bar and active task breakdown |
| `node scripts/pm.js add "<title>"` | Ingests new task/issue from user request or agent plan |
| `node scripts/pm.js next` | Resolves DAG and outputs the next unblocked, ready task |
| `node scripts/pm.js context <ID>` | Compiles exact, targeted context brief for an agent |
| `node scripts/pm.js start <ID>` | Claims task, transitions state to `IN_PROGRESS`, logs run |
| `node scripts/pm.js verify <ID>` | Executes the automated test command defined in the task spec |
| `node scripts/pm.js finish <ID>` | Executes verification gate and seals task as `DONE` |
| `node scripts/pm.js pause <ID>` | Moves a task to `ON_HOLD` / `PAUSED` status |
| `node scripts/pm.js board` | Boots instant zero-dependency Kanban UI at `http://localhost:3333` |
| `node scripts/pm.js init` | Bootstraps `.project/` folder structure in a new repository |

## Invariant for AI Agents
When a user asks for a new feature, improvement, or bug fix:
1. **Immediately Register the Task**: Run `node scripts/pm.js add "<title>" --priority=<prio> --epic=<epic> --assign=<role>` so it is tracked on the PM board.
2. **Start the Task**: Move to `IN_PROGRESS` via `node scripts/pm.js start <task_id>`.
3. **Execute & Test**: Implement the changes and run the verification command.
4. **Finish with Evidence**: Transition to `DONE` via `node scripts/pm.js finish <task_id> --evidence="..."`.
