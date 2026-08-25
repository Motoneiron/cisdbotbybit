# Деплой Bybit-бота. Usage: .\scripts\deploy-with-backup.ps1
# SSH-хост: cisdbotbybit (не cisdbot / MEXC).
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$hostAlias = "cisdbotbybit"
$remote = "/opt/cisdbotbybit"

$backupCmd = @(
    "mkdir -p $remote/backups"
    "cp $remote/cisdbot.py $remote/backups/cisdbot.py.$ts 2>/dev/null || true"
    "cp $remote/ctl_server.py $remote/backups/ctl_server.py.$ts 2>/dev/null || true"
    "cp $remote/detectors/cisd_htf.py $remote/backups/cisd_htf.py.$ts 2>/dev/null || true"
    "cp $remote/backtest/psl_size.py $remote/backups/psl_size.py.$ts 2>/dev/null || true"
    "cp $remote/backtest/psl_size_model.json $remote/backups/psl_size_model.json.$ts 2>/dev/null || true"
    "ls -1t $remote/backups/cisdbot.py.* 2>/dev/null | tail -n +11 | xargs -r rm -f"
    "ls -1t $remote/backups/cisd_htf.py.* 2>/dev/null | tail -n +11 | xargs -r rm -f"
    "ls -1t $remote/backups/psl_size.py.* 2>/dev/null | tail -n +11 | xargs -r rm -f"
    "ls -1t $remote/backups/psl_size_model.json.* 2>/dev/null | tail -n +11 | xargs -r rm -f"
) -join " && "

Write-Host "Server backup..."
ssh $hostAlias $backupCmd

Write-Host "Upload..."
scp (Join-Path $root "cisdbot.py") "${hostAlias}:${remote}/"
scp (Join-Path $root "ctl_server.py") "${hostAlias}:${remote}/"
scp -r (Join-Path $root "detectors") "${hostAlias}:${remote}/"
ssh $hostAlias "mkdir -p $remote/backtest $remote/scripts"
scp (Join-Path $root "scripts\cisdbot-ctl.py") "${hostAlias}:${remote}/scripts/"
scp (Join-Path $root "backtest\__init__.py") "${hostAlias}:${remote}/backtest/"
scp (Join-Path $root "backtest\sweep_atr_filter.py") "${hostAlias}:${remote}/backtest/"
scp (Join-Path $root "backtest\volume_filter.py") "${hostAlias}:${remote}/backtest/"
scp (Join-Path $root "backtest\touch_filter.py") "${hostAlias}:${remote}/backtest/"
scp (Join-Path $root "backtest\quality_size.py") "${hostAlias}:${remote}/backtest/"
scp (Join-Path $root "backtest\psl_size.py") "${hostAlias}:${remote}/backtest/"
scp (Join-Path $root "backtest\psl_size_model.json") "${hostAlias}:${remote}/backtest/"

Write-Host "Restart..."
ssh $hostAlias "systemctl restart cisdbotbybit && sleep 2 && systemctl is-active cisdbotbybit"
