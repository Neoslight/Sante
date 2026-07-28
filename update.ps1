<#
.SYNOPSIS
    Ingère le dernier export sous data/exports/, reconstruit les marts, puis
    lance le dashboard Streamlit.

.EXAMPLE
    .\update.ps1                # ingère + lance l'app
    .\update.ps1 -NoLaunch      # ingère seulement, sans lancer l'app
#>
param(
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== Ingestion du dernier export ===" -ForegroundColor Cyan
python -m health.ingest
if ($LASTEXITCODE -ne 0) {
    Write-Host "Échec de l'ingestion (code $LASTEXITCODE)." -ForegroundColor Red
    exit $LASTEXITCODE
}

if (-not $NoLaunch) {
    Write-Host "`n=== Lancement du dashboard ===" -ForegroundColor Cyan
    streamlit run app/Bilan_du_jour.py
}
