#!/usr/bin/env bash
# STOP-TIMING-10 (04.10): зона-метрики (время в зоне вход-стоп) на кандидате v2.
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=stopt10_queue.log
echo "START_STOPT10 $(date +%F_%H:%M:%S)" >> "$LOG"
"$PY" stop_timing_run.py tf1v2_zone > stopt10_run.log 2>&1
echo "STOPT10_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
