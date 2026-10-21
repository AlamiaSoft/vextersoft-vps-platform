const assert = require('assert');
const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

console.log('🧪 Running Agent-PM Test Suite...');

const CLI_PATH = path.resolve(__dirname, '../bin/pm.js');
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-pm-test-'));

try {
    // 1. Test init in temp directory
    console.log('  Testing pm init in sandbox:', tempDir);
    execSync(`node "${CLI_PATH}" init`, { cwd: tempDir, stdio: 'pipe' });
    
    assert(fs.existsSync(path.join(tempDir, '.project')), '.project directory should exist');
    assert(fs.existsSync(path.join(tempDir, '.project', 'project.yaml')), 'project.yaml should exist');
    assert(fs.existsSync(path.join(tempDir, '.project', 'tasks')), 'tasks directory should exist');
    console.log('  ✅ Init test passed');

    // 2. Test status
    const statusOut = execSync(`node "${CLI_PATH}" status`, { cwd: tempDir, encoding: 'utf8' });
    assert(statusOut.includes('PROJECT STATE SUMMARY'), 'Status output should contain summary');
    console.log('  ✅ Status test passed');

    // 3. Test next task resolution
    const nextOut = execSync(`node "${CLI_PATH}" next`, { cwd: tempDir, encoding: 'utf8' });
    assert(nextOut.includes('TASK CONTEXT BRIEF'), 'Next should return a context brief');
    console.log('  ✅ Next task resolution test passed');

    // 4. Test context compilation
    const contextOut = execSync(`node "${CLI_PATH}" context T-001`, { cwd: tempDir, encoding: 'utf8' });
    assert(contextOut.includes('TASK CONTEXT BRIEF: T-001'), 'Context should return T-001 brief');
    console.log('  ✅ Context compilation test passed');

    // 5. Test task claim & start
    const startOut = execSync(`node "${CLI_PATH}" start T-001 --agent=lead`, { cwd: tempDir, encoding: 'utf8' });
    assert(startOut.includes('is now IN_PROGRESS'), 'Task should be in progress');
    console.log('  ✅ Task start & claim test passed');

    // 6. Test task verification & finish
    const finishOut = execSync(`node "${CLI_PATH}" finish T-001 --evidence="Verified in test harness"`, { cwd: tempDir, encoding: 'utf8' });
    assert(finishOut.includes('marked as DONE'), 'Task should be marked as DONE');
    console.log('  ✅ Task finish & verification gate test passed');

    console.log('\n🎉 ALL AGENT-PM TESTS PASSED (6/6)');
} finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
}
