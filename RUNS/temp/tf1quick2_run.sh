#!/usr/bin/env bash
# QUICK-ВОЛНА-2: комбо спан×порог, SOL/2025.
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=tf1quick2_queue.log
echo "START2 $(date +%F_%H:%M:%S)" >> "$LOG"
MODES="q_c13_003 q_c34_003 q_c13_005 q_c34_005"
for m in $MODES; do
  "$PY" tf1_quick.py "$m" SOL 2025 > "q_run_${m}.log" 2>&1 &
done
wait
echo "TF1QUICK2_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
