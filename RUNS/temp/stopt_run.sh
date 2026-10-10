#!/usr/bin/env bash
# STOP-TIMING (02.10): перегон tf1lc15_l1h с сохранением tbt (бар свипа) + htf для анализа таймингов стопов.
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=stopt_queue.log
echo "START_STOPT $(date +%F_%H:%M:%S)" >> "$LOG"
"$PY" stop_timing_run.py tf1lc15_l1h > stopt_run.log 2>&1
echo "STOPT_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
