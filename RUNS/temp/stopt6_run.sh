#!/usr/bin/env bash
# STOP-TIMING-6 (03.10): КАНДИДАТ v2 + TP=1.5R на 10 парах (финальный TP-прогон).
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=stopt6_queue.log
echo "START_STOPT6 $(date +%F_%H:%M:%S)" >> "$LOG"
"$PY" stop_timing_run.py tf1v2_tp15 > stopt6_run.log 2>&1
echo "STOPT6_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
