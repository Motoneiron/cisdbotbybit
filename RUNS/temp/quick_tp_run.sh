#!/usr/bin/env bash
# QUICK TP-сетка (02.10): SOL/2025, режимы tf1v2_tp15 и tf1v2_tp20 (параллельно).
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=quick_tp_queue.log
echo "START_QUICKTP $(date +%F_%H:%M:%S)" >> "$LOG"
"$PY" quick_tp.py tf1v2_tp15 > quick_tp_15.log 2>&1 &
P1=$!
"$PY" quick_tp.py tf1v2_tp20 > quick_tp_20.log 2>&1 &
P2=$!
wait $P1 $P2
echo "QUICKTP_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
