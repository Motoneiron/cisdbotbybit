#!/usr/bin/env bash
# STOP-TIMING-5 (02/03.10): кандидат v2 (tf1v2) на новых парах AVAX/NEAR/UNI/TON (догон 12 файлов).
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=stopt5_queue.log
echo "START_STOPT5 $(date +%F_%H:%M:%S)" >> "$LOG"
"$PY" stop_timing_run.py tf1v2 > stopt5_run.log 2>&1
echo "STOPT5_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
