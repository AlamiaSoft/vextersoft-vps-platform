#!/usr/bin/env node

/**
 * ============================================================================
 * AGENT-PM: Universal Project Execution Protocol for Humans & AI Agents
 * Zero-dependency, GitOps-native task state machine and context compiler.
 * ============================================================================
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const http = require('http');

// Configuration
const PROJECT_DIR = path.resolve(process.cwd(), '.project');
const TASKS_DIR = path.join(PROJECT_DIR, 'tasks');
const EPICS_DIR = path.join(PROJECT_DIR, 'epics');
const DECISIONS_DIR = path.join(PROJECT_DIR, 'decisions');
const RUNS_DIR = path.join(PROJECT_DIR, 'runs');
const CONFIG_FILE = path.join(PROJECT_DIR, 'project.yaml');

// Allowed Lifecycle States
const STATES = {
    BACKLOG: 'backlog',
    READY: 'ready',
    CLAIMED: 'claimed',
    IN_PROGRESS: 'in_progress',
    REVIEW: 'review',
    VERIFIED: 'verified',
    DONE: 'done',
    BLOCKED: 'blocked',
    ON_HOLD: 'on_hold',
    PAUSED: 'paused',
    ABANDONED: 'abandoned'
};

// Simple YAML Parser & Serializer for Frontmatter (Zero external dependencies)
function parseFrontmatter(content) {
    if (!content.startsWith('---')) {
        return { data: {}, body: content };
    }
    const endIdx = content.indexOf('\n---', 3);
    if (endIdx === -1) {
        return { data: {}, body: content };
    }
    const rawYaml = content.substring(3, endIdx).trim();
    const body = content.substring(endIdx + 4).trim();
    const data = {};

    let currentKey = null;
    let currentArray = null;

    rawYaml.split('\n').forEach(line => {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) return;

        // Array item
        if (trimmed.startsWith('- ')) {
            if (currentArray) {
                let val = trimmed.substring(2).trim();
                if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
                    val = val.substring(1, val.length - 1);
                }
                currentArray.push(val);
            }
            return;
        }

        // Key-value
        const colonIdx = line.indexOf(':');
        if (colonIdx !== -1) {
            const key = line.substring(0, colonIdx).trim();
            let val = line.substring(colonIdx + 1).trim();

            if (val === '') {
                // Potential array or object start
                currentKey = key;
                currentArray = [];
                data[key] = currentArray;
            } else {
                currentKey = null;
                currentArray = null;
                if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
                    val = val.substring(1, val.length - 1);
                } else if (val === 'true') val = true;
                else if (val === 'false') val = false;
                else if (!isNaN(val) && val !== '') val = Number(val);
                data[key] = val;
            }
        }
    });

    return { data, body };
}

function stringifyFrontmatter(data, body) {
    let out = '---\n';
    for (const [k, v] of Object.entries(data)) {
        if (v === undefined || v === null) continue;
        if (Array.isArray(v)) {
            out += `${k}:\n`;
            v.forEach(item => {
                out += `  - "${item}"\n`;
            });
        } else if (typeof v === 'object') {
            out += `${k}:\n`;
            for (const [subK, subV] of Object.entries(v)) {
                out += `  ${subK}: "${subV}"\n`;
            }
        } else if (typeof v === 'string') {
            out += `${k}: "${v}"\n`;
        } else {
            out += `${k}: ${v}\n`;
        }
    }
    out += '---\n\n' + (body || '').trim() + '\n';
    return out;
}

// Helper: Git Info
function getGitInfo() {
    try {
        const branch = execSync('git branch --show-current', { encoding: 'utf8' }).trim();
        const commit = execSync('git rev-parse --short HEAD', { encoding: 'utf8' }).trim();
        return { branch, commit };
    } catch {
        return { branch: 'main', commit: 'untracked' };
    }
}

// Ensure Directories
function ensureStructure() {
    [PROJECT_DIR, TASKS_DIR, EPICS_DIR, DECISIONS_DIR, RUNS_DIR].forEach(dir => {
        if (!fs.existsSync(dir)) {
            fs.mkdirSync(dir, { recursive: true });
        }
    });
}

// Load All Tasks
function loadTasks() {
    if (!fs.existsSync(TASKS_DIR)) return [];
    const files = fs.readdirSync(TASKS_DIR).filter(f => f.endsWith('.md'));
    return files.map(file => {
        const filePath = path.join(TASKS_DIR, file);
        const content = fs.readFileSync(filePath, 'utf8');
        const { data, body } = parseFrontmatter(content);
        return {
            filename: file,
            filePath,
            ...data,
            id: data.id || file.replace('.md', ''),
            status: data.status || STATES.BACKLOG,
            depends_on: Array.isArray(data.depends_on) ? data.depends_on : (data.dependencies ? data.dependencies : []),
            blocks: Array.isArray(data.blocks) ? data.blocks : [],
            decision_refs: Array.isArray(data.decision_refs) ? data.decision_refs : [],
            files: Array.isArray(data.files) ? data.files : [],
            body
        };
    });
}

// Load Single Task
function loadTask(taskId) {
    const tasks = loadTasks();
    const cleanId = taskId.toUpperCase().replace(/\.MD$/, '');
    return tasks.find(t => t.id.toUpperCase() === cleanId || t.filename.toUpperCase().replace('.MD', '') === cleanId);
}

// Save Task
function saveTask(task) {
    const filename = task.filename || `${task.id}.md`;
    const filePath = path.join(TASKS_DIR, filename);
    const { filename: f, filePath: p, body, ...data } = task;
    data.updated_at = new Date().toISOString().split('T')[0];
    fs.writeFileSync(filePath, stringifyFrontmatter(data, body), 'utf8');
}

// Save Run Record
function recordRun(taskId, runData) {
    const taskRunsDir = path.join(RUNS_DIR, taskId);
    if (!fs.existsSync(taskRunsDir)) {
        fs.mkdirSync(taskRunsDir, { recursive: true });
    }
    const runs = fs.readdirSync(taskRunsDir).filter(f => f.endsWith('.json'));
    const nextNum = String(runs.length + 1).padStart(3, '0');
    const runFile = path.join(taskRunsDir, `${nextNum}.json`);
    const payload = {
        task_id: taskId,
        run_id: nextNum,
        timestamp: new Date().toISOString(),
        ...runData
    };
    fs.writeFileSync(runFile, JSON.stringify(payload, null, 2), 'utf8');
    return runFile;
}

// CLI Commands
const commands = {
    // 1. Initialize .project/
    init(args) {
        ensureStructure();
        if (!fs.existsSync(CONFIG_FILE)) {
            const defaultProject = `name: "${path.basename(process.cwd())}"\nversion: "1.0.0"\nstatus: "active"\ncreated_at: "${new Date().toISOString().split('T')[0]}"\ninvariants:\n  - "All PRs and tasks must pass automated verification tests"\nepics:\n  EP-01-core-foundation:\n    title: "Core Foundation & Architecture"\n    status: "active"\nagents:\n  - name: "lead"\n    role: "Lead Architect & Engineer"\n  - name: "backend"\n    role: "Backend API & Database Engineer"\n  - name: "frontend"\n    role: "UI & State Management Engineer"\n`;
            fs.writeFileSync(CONFIG_FILE, defaultProject, 'utf8');
        }

        const existingTasks = fs.readdirSync(TASKS_DIR).filter(f => f.endsWith('.md'));
        if (existingTasks.length === 0) {
            const sampleTask = `---
id: T-001
title: Setup Project Baseline Scaffolding
status: ready
priority: high
epic: EP-01-core-foundation
assigned_to: lead
depends_on: []
blocks: []
relevant_files:
  - package.json
  - README.md
decisions:
  - ADR-001-architecture-baseline
verification: node -v
tags:
  - scaffolding
  - setup
created_at: ${new Date().toISOString()}
updated_at: ${new Date().toISOString()}
---

## Objective
Establish the initial development repository structure and foundational dependencies.

## Acceptance Criteria
- [ ] Repository initialized with version control
- [ ] Dependencies configured and verified
- [ ] Automated build and test pipeline passes
`;
            fs.writeFileSync(path.join(TASKS_DIR, 'T-001-setup-project-baseline.md'), sampleTask, 'utf8');
        }

        const existingDecisions = fs.readdirSync(DECISIONS_DIR).filter(f => f.endsWith('.md'));
        if (existingDecisions.length === 0) {
            const sampleDecision = `# ADR-001: Architecture Baseline & Project Standards

## Status
Accepted

## Date
${new Date().toISOString().split('T')[0]}

## Context
Maintaining a single source of truth for architectural decisions prevents tribal knowledge drift.

## Decision
1. All technical tasks must reference approved ADRs when relevant.
2. Changes to core system contracts require an updated ADR.
3. Automated test gates must be executed prior to closing task specifications.
`;
            fs.writeFileSync(path.join(DECISIONS_DIR, 'ADR-001-architecture-baseline.md'), sampleDecision, 'utf8');
        }

        console.log(`✅ Initialized .project/ state machine in ${process.cwd()}`);
    },

    // 2. Executive Status Summary
    status() {
        const tasks = loadTasks();
        const counts = {};
        Object.values(STATES).forEach(s => counts[s] = 0);
        tasks.forEach(t => {
            counts[t.status] = (counts[t.status] || 0) + 1;
        });

        const total = tasks.length;
        const done = counts[STATES.DONE] || 0;
        const inProgress = (counts[STATES.IN_PROGRESS] || 0) + (counts[STATES.CLAIMED] || 0);
        const ready = counts[STATES.READY] || 0;
        const blocked = counts[STATES.BLOCKED] || 0;
        const onHold = (counts[STATES.ON_HOLD] || 0) + (counts[STATES.PAUSED] || 0);
        const pct = total > 0 ? Math.round((done / total) * 100) : 0;

        console.log(`\n========================================================================`);
        console.log(` PROJECT STATE SUMMARY: ${path.basename(process.cwd())}`);
        console.log(`========================================================================`);
        console.log(`  Progress: [${'█'.repeat(Math.floor(pct / 5))}${'░'.repeat(20 - Math.floor(pct / 5))}] ${pct}% (${done}/${total} Done)`);
        console.log(`  ----------------------------------------------------------------------`);
        console.log(`  🚀 In Progress: ${inProgress}  |  📋 Ready: ${ready}  |  🔒 Blocked: ${blocked}  |  ⏸️  On Hold: ${onHold}  |  📦 Backlog: ${counts[STATES.BACKLOG] || 0}`);
        console.log(`========================================================================\n`);

        if (inProgress > 0) {
            console.log(`ACTIVE TASKS:`);
            tasks.filter(t => [STATES.IN_PROGRESS, STATES.CLAIMED].includes(t.status)).forEach(t => {
                console.log(`  • [${t.id}] ${t.title} (${t.assigned_to || 'unassigned'})`);
            });
            console.log();
        }

        if (blocked > 0) {
            console.log(`⚠️  BLOCKED TASKS:`);
            tasks.filter(t => t.status === STATES.BLOCKED).forEach(t => {
                console.log(`  • [${t.id}] ${t.title} -> Reason: ${t.blocked_reason || 'Unspecified'}`);
            });
            console.log();
        }

        if (onHold > 0) {
            console.log(`⏸️  ON HOLD / PAUSED TASKS:`);
            tasks.filter(t => [STATES.ON_HOLD, STATES.PAUSED].includes(t.status)).forEach(t => {
                console.log(`  • [${t.id}] ${t.title} (${t.epic || 'no epic'})`);
            });
            console.log();
        }
    },

    // 3. List Tasks
    list(args) {
        const tasks = loadTasks();
        const statusFilter = args.status;
        const epicFilter = args.epic;
        const agentFilter = args.agent;

        let filtered = tasks;
        if (statusFilter) filtered = filtered.filter(t => t.status.toLowerCase() === statusFilter.toLowerCase());
        if (epicFilter) filtered = filtered.filter(t => (t.epic || '').toLowerCase() === epicFilter.toLowerCase());
        if (agentFilter) filtered = filtered.filter(t => (t.assigned_to || '').toLowerCase() === agentFilter.toLowerCase());

        console.log(`\nFound ${filtered.length} task(s):\n`);
        filtered.forEach(t => {
            const statusBadge = `[${t.status.toUpperCase()}]`.padEnd(14);
            const prioBadge = `(${t.priority || 'medium'})`.padEnd(10);
            console.log(`  ${t.id.padEnd(8)} ${statusBadge} ${prioBadge} ${t.title}`);
        });
        console.log();
    },

    // 4. DAG Next Task Resolver (The Agent Secret Weapon)
    next(args) {
        const tasks = loadTasks();
        const agentFilter = args.agent;

        // Completed task IDs
        const completedIds = new Set(tasks.filter(t => t.status === STATES.DONE).map(t => t.id.toUpperCase()));

        // Candidate tasks: status is ready or backlog, dependencies all satisfied
        const candidates = tasks.filter(t => {
            if ([STATES.DONE, STATES.ABANDONED, STATES.BLOCKED, STATES.PAUSED, STATES.ON_HOLD].includes(t.status)) return false;
            if (agentFilter && t.assigned_to && t.assigned_to.toLowerCase() !== agentFilter.toLowerCase()) return false;

            // Check if all depends_on are satisfied
            const deps = t.depends_on || [];
            const satisfied = deps.every(d => completedIds.has(d.toUpperCase()));
            return satisfied;
        });

        // Sort by priority (critical > high > medium > low) and status (in_progress > ready > backlog)
        const prioWeight = { critical: 4, high: 3, medium: 2, low: 1 };
        const statusWeight = { [STATES.IN_PROGRESS]: 4, [STATES.CLAIMED]: 3, [STATES.READY]: 2, [STATES.BACKLOG]: 1 };

        candidates.sort((a, b) => {
            const sA = statusWeight[a.status] || 0;
            const sB = statusWeight[b.status] || 0;
            if (sA !== sB) return sB - sA;
            const pA = prioWeight[a.priority || 'medium'] || 0;
            const pB = prioWeight[b.priority || 'medium'] || 0;
            return pB - pA;
        });

        const nextTask = candidates[0];
        if (!nextTask) {
            console.log(`\n🎉 No unblocked tasks waiting. All pending items are either in review, blocked, or finished!\n`);
            return;
        }

        // Print Compiled Execution Brief
        commands.context({ _: [nextTask.id] });
    },

    // 5. Context Compiler (Compiles 2-8 KB targeted context)
    context(args) {
        const taskId = args._[0];
        if (!taskId) {
            console.error('Error: Please specify task ID (e.g. pm context T-001)');
            process.exit(1);
        }
        const task = loadTask(taskId);
        if (!task) {
            console.error(`Error: Task ${taskId} not found.`);
            process.exit(1);
        }

        console.log(`\n========================================================================`);
        console.log(` TASK CONTEXT BRIEF: ${task.id} - ${task.title}`);
        console.log(`========================================================================`);
        console.log(`STATUS:        ${task.status.toUpperCase()}`);
        console.log(`PRIORITY:      ${(task.priority || 'medium').toUpperCase()}`);
        console.log(`EPIC:          ${task.epic || 'None'}`);
        console.log(`ASSIGNED TO:   ${task.assigned_to || 'Any'}`);
        console.log(`DEPENDS ON:    ${task.depends_on && task.depends_on.length ? task.depends_on.join(', ') : 'None (Ready)'}`);
        console.log(`VERIFICATION:  ${task.verification_command || (task.verification && task.verification.command) || 'Not specified'}`);

        if (task.decision_refs && task.decision_refs.length) {
            console.log(`\nARCHITECTURE DECISIONS (ADRs):`);
            task.decision_refs.forEach(adr => {
                const adrFile = path.join(DECISIONS_DIR, `${adr}.md`);
                if (fs.existsSync(adrFile)) {
                    console.log(`  • ${adr}: ${adrFile}`);
                } else {
                    console.log(`  • ${adr}`);
                }
            });
        }

        if (task.files && task.files.length) {
            console.log(`\nRELEVANT CODE FILES:`);
            task.files.forEach(f => console.log(`  • ${f}`));
        }

        console.log(`\nSPECIFICATION & ACCEPTANCE CRITERIA:`);
        console.log(task.body || 'No detailed markdown body provided.');

        console.log(`\n------------------------------------------------------------------------`);
        console.log(`AGENT WORKFLOW HANDOFF:`);
        console.log(`  1. Claim/Start:  node scripts/pm.js start ${task.id}`);
        console.log(`  2. Verify Tests: node scripts/pm.js verify ${task.id}`);
        console.log(`  3. Finish Task:  node scripts/pm.js finish ${task.id} --evidence="Certified tests pass"`);
        console.log(`========================================================================\n`);
    },

    // 6. Start Task
    start(args) {
        const taskId = args._[0];
        const agent = args.agent || 'agent';
        if (!taskId) {
            console.error('Error: Please specify task ID (e.g. pm start T-001)');
            process.exit(1);
        }
        const task = loadTask(taskId);
        if (!task) {
            console.error(`Error: Task ${taskId} not found.`);
            process.exit(1);
        }

        const git = getGitInfo();
        task.status = STATES.IN_PROGRESS;
        task.claimed_by = agent;
        task.started_at = new Date().toISOString();
        task.start_git_commit = git.commit;
        task.start_git_branch = git.branch;

        saveTask(task);
        recordRun(task.id, {
            action: 'START',
            agent,
            git_commit: git.commit,
            git_branch: git.branch
        });

        console.log(`🚀 Task ${task.id} is now IN_PROGRESS (Claimed by: ${agent}, Git: ${git.commit} on ${git.branch})`);
    },

    // 7. Verify Task
    verify(args) {
        const taskId = args._[0];
        if (!taskId) {
            console.error('Error: Please specify task ID (e.g. pm verify T-001)');
            process.exit(1);
        }
        const task = loadTask(taskId);
        if (!task) {
            console.error(`Error: Task ${taskId} not found.`);
            process.exit(1);
        }

        const cmd = typeof task.verification === 'string' ? task.verification : (task.verification_command || (task.verification && task.verification.command));
        if (!cmd) {
            console.log(`⚠️ No automated verification command specified for ${task.id}.`);
            return true;
        }

        console.log(`🧪 Running verification: ${cmd}`);
        try {
            execSync(cmd, { stdio: 'inherit' });
            console.log(`\n✅ Verification PASSED for ${task.id}`);
            return true;
        } catch (e) {
            console.error(`\n❌ Verification FAILED for ${task.id}`);
            return false;
        }
    },

    // 8. Finish Task (With Hard Verification Invariant)
    finish(args) {
        const taskId = args._[0];
        const evidence = args.evidence || 'Verification verified';
        if (!taskId) {
            console.error('Error: Please specify task ID (e.g. pm finish T-001)');
            process.exit(1);
        }
        const task = loadTask(taskId);
        if (!task) {
            console.error(`Error: Task ${taskId} not found.`);
            process.exit(1);
        }

        // Run verification if defined
        const cmd = task.verification_command || (task.verification && task.verification.command);
        if (cmd) {
            console.log(`🧪 Enforcing Verification Invariant before completion...`);
            try {
                execSync(cmd, { stdio: 'inherit' });
            } catch (err) {
                console.error(`\n❌ BLOCKED: Cannot mark ${task.id} as DONE because verification command failed!`);
                process.exit(1);
            }
        }

        const git = getGitInfo();
        task.status = STATES.DONE;
        task.completed_at = new Date().toISOString();
        task.completed_git_commit = git.commit;
        task.verification_evidence = evidence;

        saveTask(task);
        recordRun(task.id, {
            action: 'FINISH',
            git_commit: git.commit,
            evidence
        });

        console.log(`\n🎉 Task ${task.id} marked as DONE!`);
        console.log(`   Commit: ${git.commit} | Evidence: ${evidence}`);
    },

    // 9. Block Task
    block(args) {
        const taskId = args._[0];
        const reason = args.reason || args._[1] || 'Blocked pending external resolution';
        if (!taskId) {
            console.error('Error: Please specify task ID (e.g. pm block T-001 --reason="...")');
            process.exit(1);
        }
        const task = loadTask(taskId);
        if (!task) {
            console.error(`Error: Task ${taskId} not found.`);
            process.exit(1);
        }

        task.status = STATES.BLOCKED;
        task.blocked_reason = reason;
        saveTask(task);
        recordRun(task.id, {
            action: 'BLOCK',
            reason
        });

        console.log(`🔒 Task ${task.id} marked as BLOCKED: ${reason}`);
    },

    // 10. Pause / Put Task On Hold
    pause(args) {
        const taskId = args._[0];
        const reason = args.reason || args._[1] || 'Put on hold / paused';
        if (!taskId) {
            console.error('Error: Please specify task ID (e.g. pm pause T-001 --reason="...")');
            process.exit(1);
        }
        const task = loadTask(taskId);
        if (!task) {
            console.error(`Error: Task ${taskId} not found.`);
            process.exit(1);
        }

        task.status = STATES.PAUSED;
        task.pause_reason = reason;
        saveTask(task);
        recordRun(task.id, {
            action: 'PAUSE',
            reason
        });

        console.log(`⏸️  Task ${task.id} is now ON HOLD / PAUSED (Reason: ${reason})`);
    },
    hold(args) {
        return commands.pause(args);
    },

    // 11. Add New Task
    add(args) {
        const title = args._.join(' ') || args.title || 'New Task';
        const tasks = loadTasks();
        let maxId = 0;
        tasks.forEach(t => {
            const m = String(t.id).match(/^T-(\d+)/i);
            if (m) {
                const n = parseInt(m[1], 10);
                if (n > maxId) maxId = n;
            }
        });
        const nextId = `T-${String(maxId + 1).padStart(3, '0')}`;
        const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '').substring(0, 40);
        const filename = `${nextId}-${slug || 'task'}.md`;

        const newTask = {
            id: nextId,
            filename: filename,
            title,
            status: args.status || STATES.BACKLOG,
            priority: args.priority || 'medium',
            epic: args.epic || '',
            assigned_to: args.assigned_to || args.agent || 'agent',
            depends_on: args.depends ? args.depends.split(',') : [],
            blocks: [],
            relevant_files: args.files ? args.files.split(',') : [],
            verification: args.verification || '',
            created_at: new Date().toISOString().split('T')[0],
            body: args.body || args.description || `## Objective\n${title}\n\n## Acceptance Criteria\n- [ ] Implement required functionality\n- [ ] Run verification tests\n`
        };

        saveTask(newTask);
        console.log(`\n🎉 Created task ${nextId}: "${title}"`);
        console.log(`   File: .project/tasks/${filename}`);
        console.log(`   Status: ${newTask.status} | Priority: ${newTask.priority}\n`);
        return newTask;
    },

    // 12. Zero-Dependency Web Dashboard & Visual Kanban
    board(args) {
        const port = args.port || 3333;
        const server = http.createServer((req, res) => {
            // CORS headers
            res.setHeader('Access-Control-Allow-Origin', '*');
            res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
            res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

            if (req.method === 'OPTIONS') {
                res.writeHead(204);
                res.end();
                return;
            }

            // API: List Tasks
            if (req.method === 'GET' && req.url === '/api/tasks') {
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify(loadTasks()));
                return;
            }

            // API: Create Task
            if (req.method === 'POST' && req.url === '/api/tasks') {
                let body = '';
                req.on('data', chunk => { body += chunk; });
                req.on('end', () => {
                    try {
                        const data = JSON.parse(body || '{}');
                        if (!data.title) {
                            res.writeHead(400, { 'Content-Type': 'application/json' });
                            res.end(JSON.stringify({ success: false, error: 'Title is required' }));
                            return;
                        }
                        const task = commands.add({
                            _: [data.title],
                            title: data.title,
                            priority: data.priority,
                            epic: data.epic,
                            assigned_to: data.assigned_to,
                            status: data.status,
                            verification: data.verification,
                            description: data.description
                        });
                        res.writeHead(201, { 'Content-Type': 'application/json' });
                        res.end(JSON.stringify({ success: true, task }));
                    } catch (e) {
                        res.writeHead(500, { 'Content-Type': 'application/json' });
                        res.end(JSON.stringify({ success: false, error: e.message }));
                    }
                });
                return;
            }

            // HTML Dashboard
            const tasks = loadTasks();
            const total = tasks.length;
            const done = tasks.filter(t => t.status === STATES.DONE).length;
            const inProg = tasks.filter(t => [STATES.IN_PROGRESS, STATES.CLAIMED, STATES.REVIEW].includes(t.status)).length;
            const pct = total > 0 ? Math.round((done / total) * 100) : 0;

            const html = `<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agent-PM Dashboard - ${path.basename(process.cwd())}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        slate: { 850: '#111827', 950: '#030712' }
                    }
                }
            }
        }
    </script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans">
    <div class="max-w-[1500px] mx-auto px-4 py-6">
        <!-- Header -->
        <header class="flex flex-col md:flex-row md:justify-between md:items-center mb-8 border-b border-slate-800 pb-5 gap-4">
            <div>
                <div class="flex items-center gap-2">
                    <span class="p-2 bg-indigo-600 rounded-lg text-white font-bold text-sm">⚡ Agent-PM</span>
                    <h1 class="text-2xl font-bold tracking-tight text-white">${path.basename(process.cwd())}</h1>
                </div>
                <p class="text-xs text-slate-400 mt-1">Universal Human & AI Execution Protocol State</p>
            </div>
            
            <div class="flex items-center gap-4">
                <button onclick="openNewTaskModal()" class="bg-indigo-600 hover:bg-indigo-500 text-white font-semibold px-4 py-2 rounded-lg text-xs transition shadow flex items-center gap-1.5">
                    <span>➕ New Task / Issue</span>
                </button>
                <div class="text-right border-l border-slate-800 pl-4">
                    <div class="text-xs text-slate-400 font-medium">Completion Rate</div>
                    <div class="text-lg font-bold text-emerald-400">${pct}% (${done}/${total})</div>
                </div>
                <div class="w-32 bg-slate-800 h-2.5 rounded-full overflow-hidden border border-slate-700">
                    <div class="bg-emerald-500 h-full rounded-full" style="width: ${pct}%"></div>
                </div>
            </div>
        </header>

        <!-- Kanban Board Lanes (5 Columns) -->
        <div class="grid grid-cols-1 md:grid-cols-5 gap-4">
            <!-- Backlog -->
            <div class="bg-slate-900/60 p-4 rounded-xl border border-slate-800 flex flex-col">
                <div class="flex justify-between items-center mb-3 pb-2 border-b border-slate-800">
                    <h3 class="text-xs font-bold uppercase tracking-wider text-slate-400">📋 Backlog</h3>
                    <span class="text-xs bg-slate-800 px-2 py-0.5 rounded font-mono">${tasks.filter(t => t.status === 'backlog').length}</span>
                </div>
                <div class="space-y-3 flex-1 overflow-y-auto max-h-[70vh]">
                    ${renderLaneCards(tasks.filter(t => t.status === 'backlog'))}
                </div>
            </div>

            <!-- Ready / Unblocked -->
            <div class="bg-slate-900/60 p-4 rounded-xl border border-slate-800 flex flex-col">
                <div class="flex justify-between items-center mb-3 pb-2 border-b border-slate-800">
                    <h3 class="text-xs font-bold uppercase tracking-wider text-sky-400">⚡ Ready</h3>
                    <span class="text-xs bg-sky-950 text-sky-300 border border-sky-800 px-2 py-0.5 rounded font-mono">${tasks.filter(t => t.status === 'ready').length}</span>
                </div>
                <div class="space-y-3 flex-1 overflow-y-auto max-h-[70vh]">
                    ${renderLaneCards(tasks.filter(t => t.status === 'ready'))}
                </div>
            </div>

            <!-- In Progress -->
            <div class="bg-slate-900/60 p-4 rounded-xl border border-slate-800 flex flex-col">
                <div class="flex justify-between items-center mb-3 pb-2 border-b border-slate-800">
                    <h3 class="text-xs font-bold uppercase tracking-wider text-amber-400">🚀 In Progress</h3>
                    <span class="text-xs bg-amber-950 text-amber-300 border border-amber-800 px-2 py-0.5 rounded font-mono">${tasks.filter(t => ['in_progress', 'claimed', 'review'].includes(t.status)).length}</span>
                </div>
                <div class="space-y-3 flex-1 overflow-y-auto max-h-[70vh]">
                    ${renderLaneCards(tasks.filter(t => ['in_progress', 'claimed', 'review'].includes(t.status)))}
                </div>
            </div>

            <!-- On Hold / Paused / Blocked -->
            <div class="bg-slate-900/60 p-4 rounded-xl border border-slate-800 flex flex-col">
                <div class="flex justify-between items-center mb-3 pb-2 border-b border-slate-800">
                    <h3 class="text-xs font-bold uppercase tracking-wider text-purple-400">⏸️ On Hold / Paused</h3>
                    <span class="text-xs bg-purple-950 text-purple-300 border border-purple-800 px-2 py-0.5 rounded font-mono">${tasks.filter(t => ['paused', 'on_hold', 'blocked'].includes(t.status)).length}</span>
                </div>
                <div class="space-y-3 flex-1 overflow-y-auto max-h-[70vh]">
                    ${renderLaneCards(tasks.filter(t => ['paused', 'on_hold', 'blocked'].includes(t.status)))}
                </div>
            </div>

            <!-- Done / Verified -->
            <div class="bg-slate-900/60 p-4 rounded-xl border border-slate-800 flex flex-col">
                <div class="flex justify-between items-center mb-3 pb-2 border-b border-slate-800">
                    <h3 class="text-xs font-bold uppercase tracking-wider text-emerald-400">✅ Done & Verified</h3>
                    <span class="text-xs bg-emerald-950 text-emerald-300 border border-emerald-800 px-2 py-0.5 rounded font-mono">${tasks.filter(t => t.status === 'done').length}</span>
                </div>
                <div class="space-y-3 flex-1 overflow-y-auto max-h-[70vh]">
                    ${renderLaneCards(tasks.filter(t => t.status === 'done'))}
                </div>
            </div>
        </div>
    </div>

    <!-- New Task Modal -->
    <div id="newTaskModal" class="fixed inset-0 bg-black/80 hidden items-center justify-center p-4 z-50">
        <div class="bg-slate-900 border border-slate-800 text-white w-full max-w-lg p-6 rounded-2xl shadow-2xl">
            <div class="flex justify-between items-center border-b border-slate-800 pb-3 mb-4">
                <h3 class="text-lg font-bold text-indigo-400 flex items-center gap-2">
                    <span>➕ Create New Task / Issue</span>
                </h3>
                <button onclick="closeNewTaskModal()" class="text-slate-400 hover:text-white text-sm">✕</button>
            </div>

            <form onsubmit="submitNewTask(event)" class="space-y-4 text-xs">
                <div>
                    <label class="block font-semibold text-slate-300 mb-1">Task Title *</label>
                    <input type="text" id="tTitle" required placeholder="e.g. Add thermal roll width selector in POS receipt" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-sm text-white focus:outline-none focus:border-indigo-500">
                </div>

                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block font-semibold text-slate-300 mb-1">Priority</label>
                        <select id="tPriority" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-white focus:outline-none focus:border-indigo-500">
                            <option value="medium">Medium</option>
                            <option value="high">High</option>
                            <option value="critical">Critical</option>
                            <option value="low">Low</option>
                        </select>
                    </div>
                    <div>
                        <label class="block font-semibold text-slate-300 mb-1">Initial Status</label>
                        <select id="tStatus" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-white focus:outline-none focus:border-indigo-500">
                            <option value="backlog">📋 Backlog</option>
                            <option value="ready">⚡ Ready</option>
                            <option value="in_progress">🚀 In Progress</option>
                            <option value="on_hold">⏸️ On Hold / Paused</option>
                        </select>
                    </div>
                </div>

                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block font-semibold text-slate-300 mb-1">Epic ID</label>
                        <input type="text" id="tEpic" value="EP-02-pos-integration" placeholder="e.g. EP-02-pos-integration" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-white">
                    </div>
                    <div>
                        <label class="block font-semibold text-slate-300 mb-1">Assignee Role</label>
                        <select id="tAssignee" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-white">
                            <option value="frontend">Frontend</option>
                            <option value="backend">Backend</option>
                            <option value="reviewer">Reviewer / QA</option>
                            <option value="agent">Agent</option>
                        </select>
                    </div>
                </div>

                <div>
                    <label class="block font-semibold text-slate-300 mb-1">Description / Acceptance Criteria (Markdown)</label>
                    <textarea id="tDesc" rows="4" placeholder="## Objective&#10;Brief explanation...&#10;&#10;## Acceptance Criteria&#10;- [ ] Task requirement 1" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-white font-mono text-xs focus:outline-none focus:border-indigo-500"></textarea>
                </div>

                <div>
                    <label class="block font-semibold text-slate-300 mb-1">Automated Verification Command (Optional)</label>
                    <input type="text" id="tVerification" placeholder="e.g. npm run test or php artisan test" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-white font-mono">
                </div>

                <div class="flex justify-end gap-2 pt-3 border-t border-slate-800">
                    <button type="button" onclick="closeNewTaskModal()" class="bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2 rounded-lg font-semibold">Cancel</button>
                    <button type="submit" id="createTaskBtn" class="bg-indigo-600 hover:bg-indigo-500 text-white px-5 py-2 rounded-lg font-bold shadow flex items-center gap-1.5">
                        <span>Create Task</span>
                    </button>
                </div>
            </form>
        </div>
    </div>

    <script>
        function openNewTaskModal() {
            document.getElementById('newTaskModal').classList.remove('hidden');
            document.getElementById('newTaskModal').classList.add('flex');
            document.getElementById('tTitle').focus();
        }

        function closeNewTaskModal() {
            document.getElementById('newTaskModal').classList.remove('flex');
            document.getElementById('newTaskModal').classList.add('hidden');
        }

        async function submitNewTask(e) {
            e.preventDefault();
            const btn = document.getElementById('createTaskBtn');
            btn.disabled = true;
            btn.innerHTML = '<span>⏳ Creating...</span>';

            const payload = {
                title: document.getElementById('tTitle').value.trim(),
                priority: document.getElementById('tPriority').value,
                status: document.getElementById('tStatus').value,
                epic: document.getElementById('tEpic').value.trim(),
                assigned_to: document.getElementById('tAssignee').value,
                description: document.getElementById('tDesc').value.trim(),
                verification: document.getElementById('tVerification').value.trim()
            };

            try {
                const res = await fetch('/api/tasks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (data.success) {
                    window.location.reload();
                } else {
                    alert('Error creating task: ' + (data.error || 'Unknown error'));
                    btn.disabled = false;
                    btn.innerHTML = '<span>Create Task</span>';
                }
            } catch (err) {
                alert('Connection error: ' + err.message);
                btn.disabled = false;
                btn.innerHTML = '<span>Create Task</span>';
            }
        }
    </script>
</body>
</html>`;

            res.writeHead(200, { 'Content-Type': 'text/html' });
            res.end(html);
        });

        server.listen(port, () => {
            console.log(`\n🚀 Agent-PM Live Board running at: http://localhost:${port}`);
            console.log(`Press Ctrl+C to stop the server.\n`);
        });
    }
};

function renderLaneCards(tasks) {
    if (tasks.length === 0) {
        return `<div class="text-xs text-slate-600 text-center py-6">Empty</div>`;
    }
    return tasks.map(t => {
        const prioCol = t.priority === 'critical' ? 'text-red-400 bg-red-950 border-red-800' : (t.priority === 'high' ? 'text-amber-400 bg-amber-950 border-amber-800' : 'text-slate-400 bg-slate-800 border-slate-700');
        return `
        <div class="bg-slate-950 p-3.5 rounded-lg border border-slate-800 shadow hover:border-slate-700 transition">
            <div class="flex justify-between items-start gap-2 mb-1.5">
                <span class="font-mono text-[11px] font-bold text-indigo-400">${t.id}</span>
                <span class="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded border ${prioCol}">${t.priority || 'medium'}</span>
            </div>
            <div class="font-bold text-xs text-white mb-1.5">${t.title}</div>
            ${t.epic ? `<div class="text-[10px] text-slate-400 mb-2">📁 ${t.epic}</div>` : ''}
            ${t.verification_evidence ? `<div class="text-[10px] text-emerald-400 font-mono bg-emerald-950/60 p-1.5 rounded border border-emerald-900/80">✓ ${t.verification_evidence}</div>` : ''}
        </div>
        `;
    }).join('');
}

// Argument Parser
function parseArgs() {
    const raw = process.argv.slice(2);
    const cmd = raw[0] || 'status';
    const args = { _: [] };

    for (let i = 1; i < raw.length; i++) {
        const arg = raw[i];
        if (arg.startsWith('--')) {
            const eqIdx = arg.indexOf('=');
            if (eqIdx !== -1) {
                const k = arg.substring(2, eqIdx);
                const v = arg.substring(eqIdx + 1);
                args[k] = v;
            } else {
                const k = arg.substring(2);
                const next = raw[i + 1];
                if (next && !next.startsWith('--')) {
                    args[k] = next;
                    i++;
                } else {
                    args[k] = true;
                }
            }
        } else {
            args._.push(arg);
        }
    }
    return { cmd, args };
}

// Main Dispatcher
function main() {
    const { cmd, args } = parseArgs();
    if (commands[cmd]) {
        commands[cmd](args);
    } else {
        console.error(`Unknown command: ${cmd}`);
        console.log(`Available commands: init, status, list, next, context, start, verify, finish, block, add, board`);
        process.exit(1);
    }
}

main();
