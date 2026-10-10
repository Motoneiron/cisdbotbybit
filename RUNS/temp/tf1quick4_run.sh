#!/usr/bin/env bash
# QUICK-ВОЛНА-4 (02.10): вход 15м/30м/45м (база, sp13, th0.03), выход 16ч, SOL/2025.
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=tf1quick4_queue.log
echo "START4 $(date +%F_%H:%M:%S)" >> "$LOG"
MODES="q15m_sp21 q30m_sp21 q45m_sp21 q15m_sp13 q30m_sp13 q45m_sp13 q15m_th003 q30m_th003 q45m_th003"
for m in $MODES; do
  "$PY" tf1_quick.py "$m" SOL 2025 > "q_run_${m}.log" 2>&1 &
done
wait
echo "TF1QUICK4_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
