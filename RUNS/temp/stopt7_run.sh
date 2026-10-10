#!/usr/bin/env bash
# STOP-TIMING-7 (03.10): сетка ВЫХОДА 2..18ч (шаг 2) на кандидате v2 (вход 1ч/TP 1R).
cd /d/PYTHON/cisdbotbybit/RUNS/temp || exit 1
PY="D:/PYTHON/CISDBOT/.venv/Scripts/python.exe"
LOG=stopt7_queue.log
echo "START_STOPT7 $(date +%F_%H:%M:%S)" >> "$LOG"
for h in 2 4 6 8 10 12 14 16 18; do
  echo "H${h}_START $(date +%F_%H:%M:%S)" >> "$LOG"
  "$PY" stop_timing_run.py tf1v2_h${h} >> stopt7_run.log 2>&1
  echo "H${h}_DONE $(date +%F_%H:%M:%S)" >> "$LOG"
done
echo "STOPT7_ALLDONE $(date +%F_%H:%M:%S)" >> "$LOG"
