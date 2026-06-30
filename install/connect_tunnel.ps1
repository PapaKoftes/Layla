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

# 2) enable remote + ensure a SECURE bearer token (stored as a hash; R5-safe).
#    We store tunnel_token_hash (sha256 of the token) — never the plaintext key —
#    matching services/governance/tunnel_auth.hash_token, so the deprecated
#    remote_api_key path (now gated off by default) is not needed.
$cfgPath = Join-Path $Repo "agent\runtime_config.json"
$cfg = if (Test-Path $cfgPath) { Get-Content $cfgPath -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
$cfg | Add-Member -NotePropertyName remote_enabled -NotePropertyValue $true -Force
$token = $null
if (-not $cfg.tunnel_token_hash) {
    $token = ([guid]::NewGuid().ToString("N")) + ([guid]::NewGuid().ToString("N"))
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $hash = ($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($token)) | ForEach-Object { $_.ToString("x2") }) -join ""
    $cfg | Add-Member -NotePropertyName tunnel_token_hash -NotePropertyValue $hash -Force
    $cfg | Add-Member -NotePropertyName tunnel_token_created_at -NotePropertyValue ((Get-Date).ToUniversalTime().ToString("o")) -Force
}
# remote_require_auth_always defaults on-when-exposed (REQ-11); leave it unset for auto.
$cfg | ConvertTo-Json -Depth 12 | Set-Content $cfgPath -Encoding utf8
Write-Host "[2/3] remote_enabled = true; secure bearer token stored (hash only)."
Write-Host ""
Write-Host "  ===== GIVE THESE TO THE LAPTOP =====" -ForegroundColor Yellow
if ($token) {
    Write-Host "  Bearer token : $token"
    Write-Host "  (shown once — stored only as a hash. To rotate, delete tunnel_token_hash and re-run.)"
} else {
    Write-Host "  A token hash already exists. To issue a fresh token, remove 'tunnel_token_hash'"
    Write-Host "  from agent\runtime_config.json and re-run — or use scripts\pair.py."
}
Write-Host "  Then on the laptop send 'Authorization: Bearer <token>' to the tunnel URL below."
Write-Host "  Easiest: run  python scripts\pair.py  on each PC (guided pairing + link test)."
Write-Host ""

# 3) make sure Layla is running, then open the tunnel
Write-Host "[3/3] Ensure Layla is running in another terminal:  cd agent ; python serve.py"
Write-Host "      Opening Cloudflare tunnel to http://127.0.0.1:$Port ... (Ctrl+C to stop)"
Write-Host ""
cloudflared tunnel --url "http://127.0.0.1:$Port"
