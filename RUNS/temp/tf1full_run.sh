#!/usr/bin/env bash
# ПОЛНАЯ БАЗА кандидатов гейта (01.10): 5 конфигов × 6 пар × 3 года.
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=tf1full_queue.log
echo "START_FULL $(date +%F_%H:%M:%S)" >> "$LOG"
MODES="q_sp13_lc q_th003 q_c13_005 q_sp34_lc q_c34_003"
for m in $MODES; do
  "$PY" live_tf_grid.py "$m" > "qfull_${m}.log" 2>&1 &
done
wait
echo "TF1FULL_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
