# Layla — expose this machine's Layla over a secure Cloudflare tunnel (host side).
#
# Run this on the MAIN PC (the one with the model). It enables remote access with a
# bearer token, then opens a public HTTPS tunnel the laptop can connect to from
# anywhere. Security note: remote auth is REQUIRED by default when exposed (REQ-11),
# and the client IP is derived from Cloudflare's unforgeable Cf-Connecting-Ip header
# (REQ-10) — so a spoofed X-Forwarded-For cannot bypass the allowlist/auth.
#
#   powershell -ExecutionPolicy Bypass -File install\connect_tunnel.ps1
#
param([int]$Port = 8000)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

Write-Host "  Layla — secure remote tunnel (host)" -ForegroundColor Magenta

# 1) cloudflared
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "[1/3] Installing cloudflared (winget)..."
    winget install --id Cloudflare.cloudflared --accept-package-agreements --accept-source-agreements --silent
}

# 2) enable remote + ensure a bearer token in runtime_config.json
$cfgPath = Join-Path $Repo "agent\runtime_config.json"
$cfg = if (Test-Path $cfgPath) { Get-Content $cfgPath -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
$cfg | Add-Member -NotePropertyName remote_enabled -NotePropertyValue $true -Force
if (-not $cfg.remote_api_key) {
    $token = ([guid]::NewGuid().ToString("N")) + ([guid]::NewGuid().ToString("N"))
    $cfg | Add-Member -NotePropertyName remote_api_key -NotePropertyValue $token -Force
}
# remote_require_auth_always defaults on-when-exposed (REQ-11); leave it unset for auto.
$cfg | ConvertTo-Json -Depth 12 | Set-Content $cfgPath -Encoding utf8
Write-Host "[2/3] remote_enabled = true; bearer token ready."
Write-Host ""
Write-Host "  ===== GIVE THESE TO THE LAPTOP =====" -ForegroundColor Yellow
Write-Host "  Bearer token : $($cfg.remote_api_key)"
Write-Host "  (the public URL is printed by cloudflared below)"
Write-Host "  On the laptop: set llama_server_url / remote host to the URL and send"
Write-Host "  'Authorization: Bearer <token>'. See install\INSTALL.md (Connect)."
Write-Host ""

# 3) make sure Layla is running, then open the tunnel
Write-Host "[3/3] Ensure Layla is running in another terminal:  cd agent ; python serve.py"
Write-Host "      Opening Cloudflare tunnel to http://127.0.0.1:$Port ... (Ctrl+C to stop)"
Write-Host ""
cloudflared tunnel --url "http://127.0.0.1:$Port"
