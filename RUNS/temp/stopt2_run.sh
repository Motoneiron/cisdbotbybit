#!/usr/bin/env bash
# STOP-TIMING-2 (02.10): кандидат БЕЗ свип-ATR (min_sweep_atr=0) + вход 1ч, с сохранением tbt/htf.
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=stopt2_queue.log
echo "START_STOPT2 $(date +%F_%H:%M:%S)" >> "$LOG"
"$PY" stop_timing_run.py tf1lc15_alloff_l1h > stopt2_run.log 2>&1
echo "STOPT2_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
