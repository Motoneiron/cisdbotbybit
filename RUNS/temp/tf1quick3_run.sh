#!/usr/bin/env bash
# QUICK-ВОЛНА-3 (02.10): финалисты гейта × окна 1ч/16ч и 1ч/12ч, SOL/2025.
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=tf1quick3_queue.log
echo "START3 $(date +%F_%H:%M:%S)" >> "$LOG"
MODES="q1h16_sp13 q1h16_sp13x05 q1h16_th003 q1h16_sp34 q1h16_sp34x03 q1h12_sp21 q1h12_sp13 q1h12_sp13x05 q1h12_th003 q1h12_sp34 q1h12_sp34x03"
for m in $MODES; do
  "$PY" tf1_quick.py "$m" SOL 2025 > "q_run_${m}.log" 2>&1 &
done
wait
echo "TF1QUICK3_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
