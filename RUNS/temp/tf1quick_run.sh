#!/usr/bin/env bash
# QUICK-серия 01.10: 20 конфигов тюнинга гейта на SOL/2025 (одна пара, один год) — параллельно.
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=tf1quick_queue.log
echo "START $(date +%F_%H:%M:%S)" >> "$LOG"

MODES="q_sp8_lc q_sp8_cb q_sp13_lc q_sp13_cb q_sp21_cb q_sp34_lc q_sp34_cb q_cc21 q_sw21 q_sw13 q_th001 q_th003 q_th005 q_th010 q_th005_cb q_ss3 q_ss5 q_ss3_cb q_1d13 q_8h13"

for m in $MODES; do
  "$PY" tf1_quick.py "$m" SOL 2025 > "q_run_${m}.log" 2>&1 &
done
wait
echo "TF1QUICK_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
