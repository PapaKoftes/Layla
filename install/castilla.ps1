# Layla -- Edicion Castilla (instalador en espanol)
# Wrapper sobre fresh_install: modelo ligero (Qwen2.5-Coder-3B) + respuestas en espanol,
# ajustado a equipos con CPU antigua / poco disco (p.ej. i7-7700HQ, 16GB, ~26GB libres).
#
#   git clone https://github.com/PapaKoftes/Layla.git
#   cd Layla
#   powershell -ExecutionPolicy Bypass -File install\castilla.ps1
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Write-Host ""
Write-Host "  Layla -- Edicion Castilla" -ForegroundColor Magenta
Write-Host "  Instalacion en espanol con un modelo ligero y rapido."
Write-Host "  ------------------------------------------------------"
& powershell -ExecutionPolicy Bypass -File (Join-Path $Repo "install\fresh_install.ps1") -Prefer lite -Spanish
Write-Host ""
Write-Host "  Listo. Para iniciar Layla:" -ForegroundColor Green
Write-Host "    .\.venv\Scripts\Activate.ps1"
Write-Host "    cd agent ; python serve.py     # abre http://127.0.0.1:8000"
Write-Host ""
Write-Host "  Layla respondera en espanol (codigo y terminos tecnicos en ingles)."
