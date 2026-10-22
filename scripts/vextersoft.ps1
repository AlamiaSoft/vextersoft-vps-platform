[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('doctor', 'prepare', 'validate', 'baseline', 'docker', 'ingress')]
    [string]$Action,
    [ValidateSet('baseline', 'docker', 'ingress')]
    [string]$Phase = 'baseline',
    [string]$Distro = 'Ubuntu-24.04',
    [string]$Inventory = 'ansible/inventory/hosts.yml',
    [ValidatePattern('^[A-Za-z0-9_-]+$')]
    [string]$HostAlias = 'vextersoft_vps',
    [string]$WindowsSshDirectory = (Join-Path $env:USERPROFILE '.ssh'),
    [string]$WindowsKeyName = 'vextersoft_vps',
    [switch]$ApproveHostChange
)
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$inventoryPath = [IO.Path]::GetFullPath((Join-Path $repoRoot $Inventory))
$playbooks = @{
    baseline = 'ansible/playbooks/01-baseline-hardening.yml'
    docker = 'ansible/playbooks/02-docker-engine.yml'
    ingress = 'ansible/playbooks/03-cloudflared-portainer.yml'
}
function Quote-Bash([string]$Value) {
    return "'" + $Value.Replace("'", "'\''") + "'"
}
function Wsl-Path([string]$Path) {
    $result = & wsl.exe --distribution $Distro --exec wslpath -u $Path
    if ($LASTEXITCODE -ne 0) { throw 'Could not resolve a local path in WSL.' }
    return [string]::Join([Environment]::NewLine, $result).Trim()
}
function Invoke-Wsl([string]$Script) {
    $normalized = $Script.Replace([string][char]13 + [string][char]10, [string][char]10)
    $payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($normalized))
    $wrapper = "printf %s $payload | base64 -d | bash"
    & wsl.exe --distribution $Distro --exec bash -lc $wrapper
    if ($LASTEXITCODE -ne 0) { throw "WSL command failed with exit code $LASTEXITCODE." }
}
function Get-Prefix {
    $wslRepo = Wsl-Path $repoRoot
    $repo = Quote-Bash $wslRepo
    $config = Quote-Bash "$wslRepo/ansible/ansible.cfg"
    $inventory = Quote-Bash (Wsl-Path $inventoryPath)
    $prefix = @'
set -Eeuo pipefail
if [ -f "$HOME/.venvs/vps-ansible/bin/activate" ]; then source "$HOME/.venvs/vps-ansible/bin/activate"; fi
cd __REPO__
export ANSIBLE_CONFIG=__CONFIG__
export ANSIBLE_HOST_KEY_CHECKING=True
export SSH_AUTH_SOCK=/tmp/vextersoft-ssh/agent.sock
INVENTORY=__INVENTORY__
HOST_ALIAS=__ALIAS__
'@
    return $prefix.Replace('__REPO__', $repo).Replace('__CONFIG__', $config).Replace('__INVENTORY__', $inventory).Replace('__ALIAS__', (Quote-Bash $HostAlias))
}
$targetDetails = @'
INVENTORY_JSON=$(ansible-inventory -i "$INVENTORY" --list)
TARGET_JSON=$(printf %s "$INVENTORY_JSON" | python3 scripts/resolve_ansible_target.py "$HOST_ALIAS")
TARGET_HOST=$(printf %s "$TARGET_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["host"])')
TARGET_USER=$(printf %s "$TARGET_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["user"])')
TARGET_PORT=$(printf %s "$TARGET_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["port"])')
TARGET_SSH_PORT=$(printf %s "$TARGET_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ssh_port"])')
printf 'Target: %s:%s (user %s; alias %s)\n' "$TARGET_HOST" "$TARGET_PORT" "$TARGET_USER" "$HOST_ALIAS"
'@
function Get-Validation([string]$SelectedPhase) {
    $playbook = Quote-Bash $playbooks[$SelectedPhase]
    $portCheck = if ($SelectedPhase -eq 'baseline') {
        @'
if [ "$TARGET_PORT" != "$TARGET_SSH_PORT" ]; then
  echo "Inventory ansible_port differs from baseline ssh_port; refusing to run." >&2
  exit 2
fi
'@
    } else { '' }
    $command = @'
__PORT_CHECK__
ansible-playbook --syntax-check -i "$INVENTORY" --limit "$HOST_ALIAS" __PLAYBOOK__
ansible -i "$INVENTORY" "$HOST_ALIAS" -m ping
'@
    return $command.Replace('__PORT_CHECK__', $portCheck).Replace('__PLAYBOOK__', $playbook)
}
function Invoke-Doctor {
    $distroOutput = & wsl.exe --list --quiet 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'WSL is unavailable or could not list distributions.' }
    $distroText = [string]::Join([string][char]10, $distroOutput) -replace [string][char]0, ''
    $distroNames = @($distroText -split '\r?\n' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if ($Distro -notin $distroNames) {
        throw "WSL distribution '$Distro' is not installed. Available distributions: $($distroNames -join ', ')"
    }
    Write-Host "WSL distribution: $Distro"
    $windowsKey = Join-Path $WindowsSshDirectory $WindowsKeyName
    $windowsKnownHosts = Join-Path $WindowsSshDirectory 'known_hosts'
    Write-Host ("Windows SSH key file: " + $(if (Test-Path -LiteralPath $windowsKey -PathType Leaf) { 'available' } else { 'missing' }))
    Write-Host ("Windows known_hosts file: " + $(if (Test-Path -LiteralPath $windowsKnownHosts -PathType Leaf) { 'available' } else { 'missing' }))
    if (-not (Test-Path -LiteralPath $inventoryPath -PathType Leaf)) {
        throw "Inventory not found: $inventoryPath"
    }
    $body = @'
ready=1
source /etc/os-release
printf 'WSL OS: %s\n' "$PRETTY_NAME"
printf 'Repository: %s\n' "$PWD"
printf 'Inventory alias: %s\n' "$HOST_ALIAS"
if command -v ansible-playbook >/dev/null 2>&1; then
  ansible-playbook --version | head -n 1
else
  echo "BLOCKED: ansible-playbook is missing."
  ready=0
fi
if ansible-inventory -i "$INVENTORY" --list >/dev/null 2>&1; then
  echo "Inventory parses successfully."
else
  echo "BLOCKED: inventory parsing failed."
  ready=0
fi
if grep -Eq '^host_key_checking[[:space:]]*=[[:space:]]*True' ansible/ansible.cfg; then
  echo "Repository host-key checking is enabled."
else
  echo "BLOCKED: host-key checking is not explicitly enabled."
  ready=0
fi
socket=/tmp/vextersoft-ssh/agent.sock
if [ -r "$HOME/.ssh/vextersoft_vps" ]; then
  echo "WSL SSH key file is available."
else
  echo "BLOCKED: WSL SSH key file is missing; run prepare."
  ready=0
fi
if SSH_AUTH_SOCK="$socket" ssh-add -l >/dev/null 2>&1; then
  echo "Configured WSL SSH agent has a loaded identity."
else
  echo "BLOCKED: WSL SSH agent is not ready; run prepare."
  ready=0
fi
if ssh-keygen -F "$TARGET_HOST" -f "$HOME/.ssh/known_hosts" >/dev/null 2>&1; then
  echo "Trusted host-key entry exists."
else
  echo "BLOCKED: host key is not trusted; establish it via the trusted bootstrap/console path, then run prepare."
  ready=0
fi
if ansible-galaxy collection list community.docker 2>/dev/null | grep -q community.docker; then
  echo "community.docker collection is installed."
else
  echo "BLOCKED: required community.docker collection is missing; run prepare."
  ready=0
fi
exit $((1-ready))
'@
    Invoke-Wsl ((Get-Prefix) + [Environment]::NewLine + $targetDetails + [Environment]::NewLine + $body)
}
function Invoke-Prepare {
    if (-not (Test-Path -LiteralPath $inventoryPath -PathType Leaf)) {
        throw "Inventory not found: $inventoryPath"
    }
    $keyWindows = Join-Path $WindowsSshDirectory $WindowsKeyName
    $knownWindows = Join-Path $WindowsSshDirectory 'known_hosts'
    foreach ($path in @($keyWindows, $knownWindows)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required SSH file is missing: $path. Establish it through the trusted bootstrap/console path."
        }
    }
    $key = Quote-Bash (Wsl-Path $keyWindows)
    $known = Quote-Bash (Wsl-Path $knownWindows)
    $body = @'
KEY_SOURCE=__KEY__
KNOWN_SOURCE=__KNOWN__
install -d -m 700 "$HOME/.ssh"
key_target="$HOME/.ssh/vextersoft_vps"
if [ ! -e "$key_target" ]; then
  install -m 600 "$KEY_SOURCE" "$key_target"
elif ! cmp -s "$KEY_SOURCE" "$key_target"; then
  echo "A different WSL SSH key exists; refusing to overwrite it." >&2
  exit 2
else
  chmod 600 "$key_target"
fi
trusted=$(mktemp)
existing=$(mktemp)
trap 'rm -f "$trusted" "$existing"' EXIT
ssh-keygen -F "$TARGET_HOST" -f "$KNOWN_SOURCE" 2>/dev/null | sed '/^#/d' > "$trusted"
if [ ! -s "$trusted" ]; then
  echo "No matching trusted host-key entry exists in Windows known_hosts." >&2
  exit 2
fi
if ssh-keygen -F "$TARGET_HOST" -f "$HOME/.ssh/known_hosts" 2>/dev/null | sed '/^#/d' > "$existing" && [ -s "$existing" ]; then
  if ! diff -q <(sort "$trusted") <(sort "$existing") >/dev/null; then
    echo "Windows and WSL host-key entries differ; refusing to replace trust data." >&2
    exit 2
  fi
else
  cat "$trusted" >> "$HOME/.ssh/known_hosts"
  chmod 600 "$HOME/.ssh/known_hosts"
fi
agent_dir=/tmp/vextersoft-ssh
agent_socket="$agent_dir/agent.sock"
install -d -m 700 "$agent_dir"
if ! SSH_AUTH_SOCK="$agent_socket" ssh-add -l >/dev/null 2>&1; then
  if [ -e "$agent_socket" ]; then rm -f "$agent_socket"; fi
  ssh-agent -a "$agent_socket" >/dev/null
fi
if [ -f "$key_target.pub" ]; then
  fingerprint=$(ssh-keygen -lf "$key_target.pub" -E sha256 | awk '{print $2}')
  if ! SSH_AUTH_SOCK="$agent_socket" ssh-add -l -E sha256 2>/dev/null | awk '{print $2}' | grep -Fxq "$fingerprint"; then
    SSH_AUTH_SOCK="$agent_socket" ssh-add "$key_target"
  fi
else
  SSH_AUTH_SOCK="$agent_socket" ssh-add "$key_target"
fi
SSH_AUTH_SOCK="$agent_socket" ssh -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -i "$key_target" -p "$TARGET_PORT" "$TARGET_USER@$TARGET_HOST" 'sudo -n id -u'
'@
    $body = $body.Replace('__KEY__', $key).Replace('__KNOWN__', $known)
    Invoke-Wsl ((Get-Prefix) + [Environment]::NewLine + $targetDetails + [Environment]::NewLine + $body)
    Invoke-Wsl ((Get-Prefix) + [Environment]::NewLine + 'ansible-galaxy collection install -r ansible/requirements.yml')
    Write-Host 'SSH identity and trusted host key prepared in WSL; key contents were not displayed.'
}
function Invoke-Validate {
    if (-not (Test-Path -LiteralPath $inventoryPath -PathType Leaf)) {
        throw "Inventory not found: $inventoryPath"
    }
    Invoke-Wsl ((Get-Prefix) + [Environment]::NewLine + $targetDetails + [Environment]::NewLine + (Get-Validation $Phase))
}
function Invoke-HostPhase {
    if (-not $ApproveHostChange) {
        throw 'Use -ApproveHostChange, then type the requested target-specific confirmation.'
    }
    $selectedPlaybook = Join-Path $repoRoot $playbooks[$Phase]
    if (-not (Test-Path -LiteralPath $selectedPlaybook -PathType Leaf)) {
        throw "Playbook not found: $selectedPlaybook"
    }
    Invoke-Validate
    Write-Host "Host-changing phase: $Phase"
    Write-Host "Inventory alias: $HostAlias"
    Write-Host "Playbook: $selectedPlaybook"
    $confirmation = "APPLY $Phase $HostAlias"
    if ((Read-Host "Type '$confirmation' to proceed") -cne $confirmation) {
        throw 'Confirmation did not match; no playbook was run.'
    }
    $playbook = Quote-Bash $playbooks[$Phase]
    $extra = if ($Phase -eq 'ingress') { ' -e cloudflare_deployment_approved=true --ask-vault-pass' } else { '' }
    $apply = @'
ansible-playbook --diff -i "$INVENTORY" --limit "$HOST_ALIAS"__EXTRA__ __PLAYBOOK__
ansible -i "$INVENTORY" "$HOST_ALIAS" -m ping__PING_VAULT__
'@
    $apply = $apply.Replace('__EXTRA__', $extra).Replace('__PING_VAULT__', '').Replace('__PLAYBOOK__', $playbook)
    Invoke-Wsl ((Get-Prefix) + [Environment]::NewLine + $targetDetails + [Environment]::NewLine + $apply)
    if ($Phase -eq 'baseline') {
        $verify = @'
ansible -i "$INVENTORY" "$HOST_ALIAS" -m shell -a 'set -e; test "$(systemctl is-active fail2ban)" = active; test -n "$(swapon --noheadings)"; sshd -T -C user="$TARGET_USER",host=127.0.0.1,addr=127.0.0.1 | grep -Eq "^passwordauthentication no$"; sshd -T -C user="$TARGET_USER",host=127.0.0.1,addr=127.0.0.1 | grep -Eq "^kbdinteractiveauthentication no$"; sshd -T -C user="$TARGET_USER",host=127.0.0.1,addr=127.0.0.1 | grep -Eq "^pubkeyauthentication yes$"; sshd -T -C user="$TARGET_USER",host=127.0.0.1,addr=127.0.0.1 | grep -Eq "^permitrootlogin (prohibit-password|no)$"; ufw status | grep -q "^Status: active"; ufw status | grep -Eq "^${TARGET_SSH_PORT}/tcp.*ALLOW IN"'
'@
    } elseif ($Phase -eq 'docker') {
        $verify = @'
ansible -i "$INVENTORY" "$HOST_ALIAS" -m shell -a 'set -e; test "$(systemctl is-active docker)" = active; test "$(systemctl is-enabled docker)" = enabled; test "$(systemctl is-active containerd)" = active; test "$(systemctl is-enabled containerd)" = enabled; docker run --rm --pull=missing hello-world'
'@
    } else {
        $verify = @'
ansible -i "$INVENTORY" "$HOST_ALIAS" -m shell -a 'set -e; for name in vextersoft-management-portainer-1 vextersoft-management-cloudflared-1; do state=$(docker inspect --format "{{ "{{" }}.State.Status{{ "}}" }} {{ "{{" }}.State.Health.Status{{ "}}" }}" "$name"); test "$state" = "running healthy"; done; docker compose -p vextersoft-management -f /opt/vextersoft/management/compose.yml ps; ss -lnt; ufw status verbose'
'@
    }
    Invoke-Wsl ((Get-Prefix) + [Environment]::NewLine + $targetDetails + [Environment]::NewLine + $verify)
}
switch ($Action) {
    doctor { Invoke-Doctor }
    prepare { Invoke-Prepare }
    validate { Invoke-Validate }
    { $_ -in @('baseline', 'docker', 'ingress') } {
        $Phase = $Action
        Invoke-HostPhase
    }
}
