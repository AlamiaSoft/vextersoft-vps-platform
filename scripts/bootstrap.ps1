# PowerShell Interactive Bootstrap Wrapper for Windows Operators
[CmdletBinding()]
param(
    [string]$HostIp,
    [int]$Port = 22,
    [string]$AdminUser = "vexteradmin",
    [string]$KnownHosts
)

$ErrorActionPreference = "Stop"

# Resolve target host IP
if (-not $HostIp) {
    if (Test-Path ".env") {
        $envMatch = Get-Content ".env" | Where-Object { $_ -match "^VPS_IP\s*=\s*(.+)$" }
        if ($envMatch) {
            $HostIp = ($envMatch -split "=", 2)[1].Trim(" '`"")
        }
    }
}

if (-not $HostIp) {
    $HostIp = Read-Host "Enter Target VPS IP"
}

if (-not $HostIp) {
    Write-Error "Target VPS IP is required."
    exit 1
}

# Prompt root password securely
$rootPassSecure = Read-Host "Enter initial root password for $HostIp" -AsSecureString
$BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($rootPassSecure)
$rootPassPlain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)

# Prompt key passphrase securely
$keyPassSecure = Read-Host "Enter passphrase for ~/.ssh/vextersoft_vps (leave blank if none)" -AsSecureString
$BSTR_Key = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($keyPassSecure)
$keyPassPlain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR_Key)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR_Key)

Write-Host "`n[*] Starting Windows bootstrap orchestrator..." -ForegroundColor Cyan

# Set ephemeral environment variables for the sub-process only
$env:BOOTSTRAP_ROOT_PASSWORD = $rootPassPlain
if ($keyPassPlain) {
    $env:BOOTSTRAP_KEY_PASSPHRASE = $keyPassPlain
}

try {
    $pyArgs = @("scripts/bootstrap_admin.py", "--host", $HostIp, "--port", "$Port", "--admin-user", $AdminUser)
    if ($KnownHosts) {
        $pyArgs += @("--known-hosts", $KnownHosts)
    }
    python -u @pyArgs
} finally {
    # Immediately clear credentials from environment and memory
    Remove-Item Env:\BOOTSTRAP_ROOT_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:\BOOTSTRAP_KEY_PASSPHRASE -ErrorAction SilentlyContinue
    Remove-Item Env:\SSH_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:\SSH_KEY_PASSPHRASE -ErrorAction SilentlyContinue
    $rootPassPlain = $null
    $keyPassPlain = $null
}
