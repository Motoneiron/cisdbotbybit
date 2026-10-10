#!/usr/bin/env bash
# STOP-TIMING-4 (02.10): КАНДИДАТ v2 (tf1v2) — капитальный прогон на 10 парах (6 + BTC/ETH/BNB/XRP).
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=stopt4_queue.log
echo "START_STOPT4 $(date +%F_%H:%M:%S)" >> "$LOG"
"$PY" stop_timing_run.py tf1v2 > stopt4_run.log 2>&1
echo "STOPT4_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
